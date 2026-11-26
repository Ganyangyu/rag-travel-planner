"""Gradio entry point for the RAG travel planner."""

import gradio as gr
from datetime import date
from queue import Queue, Empty
from threading import Thread
from time import monotonic
import logging
import re
import math
from html import escape

from src.crawler import collect_guides, format_notes
from src.profile import trip_profile
from src.planner import plan


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def generate(location: str, start: str, days: int, budget: float, audience: str, progress=gr.Progress()):
    # Progress is based on completed workflow stages, not a time-to-completion claim.
    progress(0, desc="0% · 准备出行条件")
    if not location.strip():
        yield "请先填写目的地。"
        return
    if budget is None or budget <= 0:
        yield "请输入大于零的人均预算。"
        return
    try:
        profile = trip_profile(location.strip(), start.strip(), int(days), float(budget), audience)
    except ValueError:
        yield "请使用 YYYY-MM-DD 格式的有效出发日期。"
        return

    events = Queue()
    started = monotonic()

    def status(message):
        logger.info(message)
        if message == "千问已连接，正在生成回答":
            events.put(("progress", (0.65, "千问已连接，正在生成行程")))
        match = re.search(r"XHS stage=detail index=(\d+)", message)
        if match:
            events.put(("progress", (0.15 + 0.07 * min(int(match[1]), 3), f"已读取 {match[1]} 篇笔记")))

    def crawl_progress(fraction, message):
        events.put(("progress", (0.10 + 0.45 * fraction, message)))

    def work():
        try:
            status("正在自动搜索并抓取旅行攻略……")
            try:
                notes = collect_guides(profile["queries"], profile["city"], report=status, progress=crawl_progress)
            except Exception:
                logger.exception("网络检索失败，继续生成需核实的候选方案")
                notes = []
            titles_only = [n for n in notes if n.get("kind") == "title_only"]
            notes = [n for n in notes if n.get("kind") != "title_only" and n.get("text", "").strip()]
            status(f"已取得 {len(notes)} 篇正文，正在调用千问生成行程……")
            events.put(("status", "正在整理路线与预算"))
            events.put(("progress", (0.60, "正在整合攻略并核算行程")))
            last_update = 0

            def update(text):
                nonlocal last_update
                now = monotonic()
                if now - last_update >= 0.1:
                    events.put(("answer", text))
                    last_update = now

            def model_progress(characters):
                # The model has no known total output length; label this estimate.
                fraction = 0.65 + 0.28 * (1 - math.exp(-characters / 4000))
                events.put(("progress", (fraction, f"正在生成行程（估算进度，已接收 {characters} 字符）")))

            answer = plan(profile, [], format_notes(notes), on_text=update, on_status=status, on_progress=model_progress)
            events.put(("progress", (0.95, "正在检查预算与参考来源")))
            # Only list sources actually cited; do not expose empty reference areas.
            answer = re.sub(r"\[(\d+)\](?!\()", lambda m: m[0] if 1 <= int(m[1]) <= len(notes) else "", answer)
            cited = {int(n) for n in re.findall(r"\[(\d+)\](?!\()", answer)}
            sources = "\n".join(
                f"- [{i}] [{n['title']}]({n['url']})"
                + ("（整合参考，未作具体事实引用）" if i not in cited else "")
                for i, n in enumerate(notes, 1)
            )
            if sources:
                answer += "\n\n### 参考帖子与攻略\n" + sources
            if 0 < len(notes) < 3:
                answer += f"\n\n本次仅取得 {len(notes)} 篇可读攻略，未达到三篇交叉参考；票务、开放安排和费用请按待核实清单确认。"
            if titles_only:
                answer += "\n\n### 发现的帖子（仅取得标题，未作为正文引用）\n" + "\n".join(
                    f"- [{n['title']}]({n['url']})：仅取得标题" for n in titles_only
                )
            logger.info("本次处理结束，用时 %.1f 秒", monotonic() - started)
            events.put(("done", answer))
        except Exception:
            logger.exception("旅行规划失败")
            events.put(("done", "本次方案暂未完成，请稍后重试。可先确定住宿片区和抵离时间；票务与开放安排以场所官方信息为准。"))

    yield "正在整理适合此次出行的路线，请稍候……"
    progress(0.10, desc="10% · 正在搜索多平台攻略")
    Thread(target=work, daemon=True).start()
    answer, current, displayed = "", "正在查找适合此次出行的攻略", 0.10
    while True:
        try:
            kind, value = events.get(timeout=0.25)
        except Empty:
            kind, value = "tick", ""
        if kind == "done":
            progress(1, desc="100% · 本次处理已完成")
            yield value
            return
        if kind == "answer":
            answer = value
            current = "正在生成行程"
        elif kind == "status":
            current = value
        elif kind == "progress":
            fraction, message = value
            displayed = max(displayed, fraction)
            progress(displayed, desc=message)
            current = message
        yield answer or f"{current}（已用时 {monotonic() - started:.0f} 秒）"


def progress_html(fraction: float, description: str) -> str:
    percent = round(fraction * 100, 1)
    label = f"{percent:g}%"
    return (
        '<div style="display:flex;align-items:center;gap:12px;padding:8px 0">'
        f'<div role="progressbar" aria-label="行程生成进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent}" '
        'style="flex:1;height:10px;border-radius:6px;background:#e5e7eb;overflow:hidden">'
        f'<div style="width:{percent}%;height:100%;background:#f97316;transition:width .2s linear"></div></div>'
        f'<strong style="min-width:56px;text-align:right;font-variant-numeric:tabular-nums">{label}</strong></div>'
        f'<div style="font-size:13px;opacity:.8">{escape(description)}</div>'
    )


def generate_ui(location, start, days, budget, audience):
    fraction, description = 0.0, "准备开始"

    def track(value, desc=""):
        nonlocal fraction, description
        fraction, description = max(fraction, value), desc

    for answer in generate(location, start, days, budget, audience, progress=track):
        visible = fraction >= 0.95 or answer.startswith(("请先", "请输入", "请使用"))
        yield progress_html(fraction, description), answer if visible else ""


with gr.Blocks(title="RAG 旅游规划助手", analytics_enabled=False) as demo:
    gr.Markdown("# RAG 旅游规划助手\n根据城市、季节假期、预算和人群自动搜索攻略，整合来源生成行程。预算包含目的地内住宿、餐饮、门票和市内交通。")
    with gr.Row():
        location = gr.Textbox(label="目的地", value="杭州")
        start = gr.Textbox(label="出发日期（YYYY-MM-DD）", value=date.today().isoformat())
    with gr.Row():
        days = gr.Slider(1, 7, value=2, step=1, label="天数")
        budget = gr.Number(value=1000, label="全程预算（元/人）")
        audience = gr.Dropdown(["个人","情侣","亲子家庭","老年人"], value="情侣", label="出行人群")
    button = gr.Button("生成行程", variant="primary")
    progress_display = gr.HTML(progress_html(0, "等待生成"))
    output = gr.Markdown()
    inputs = [location, start, days, budget, audience]
    button.click(generate_ui, inputs, [progress_display, output], api_name=False, show_progress="hidden")
    # Preserve the existing /generate endpoint and its single text response.
    api_entry = gr.Button(visible=False)
    api_entry.click(generate, inputs, output, api_name="generate")


if __name__ == "__main__":
    demo.queue().launch(inbrowser=True, prevent_thread_lock=True, show_error=True)
    print("\nRAG 助手已就绪，请在自动打开的网页中填写出行信息。\n按 Ctrl+C 退出。", flush=True)
    demo.block_thread()
