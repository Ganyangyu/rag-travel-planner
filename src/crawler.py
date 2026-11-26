"""Discover public travel guides and extract article bodies for retrieval."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
import logging
import hashlib
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit, urljoin, quote, parse_qs
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from .config import XHS_COOKIE


HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = (3, 7)
logger = logging.getLogger(__name__)
XHS_PROFILE = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "RAGTravelPlanner" / "xhs-browser"
_browser_lock = Lock()


def _browser_context(playwright, headless=True):
    # A dedicated Edge profile keeps the user's normal browser session untouched.
    context = playwright.chromium.launch_persistent_context(
        str(XHS_PROFILE), channel="msedge", headless=headless, viewport={"width": 1280, "height": 900},
    )
    # Bootstrap new installations with the owner's explicitly shared group session.
    # Keep an existing personal login; XHS_COOKIE explicitly overrides either one.
    has_session = any(c["name"] == "web_session" for c in context.cookies("https://www.xiaohongshu.com"))
    if XHS_COOKIE and (not has_session or os.getenv("XHS_COOKIE")):
        values = [part.strip().split("=", 1) for part in XHS_COOKIE.split(";") if "=" in part]
        context.add_cookies([
            {"name": name, "value": value, "domain": ".xiaohongshu.com", "path": "/", "secure": True}
            for name, value in values
        ])
    return context


def _xhs_snapshot(url: str, html: str) -> dict:
    """Classify a rendered page without treating an empty result as a login failure."""
    soup = BeautifulSoup(html, "html.parser")
    for hidden in soup.select("script, style, [hidden], [style*='display: none'], [style*='display:none']"):
        hidden.decompose()
    text = soup.get_text(" ", strip=True)
    params = parse_qs(urlsplit(url).query)
    code = params.get("error_code", [""])[0]
    cards = _xhs_cards(url, soup)
    matches = len(soup.select("section.note-item, .note-item, [data-note-id]"))
    state = "loading"
    if code or "当前网络存在风险" in text or "访问受限" in text or "访问过于频繁" in text:
        state = "restricted"
    elif any(word in text for word in ("安全验证", "请完成验证", "拖动滑块", "验证码验证")):
        state = "verification"
    elif soup.select_one(".login-container, .login-modal, .login-mask") or any(word in text for word in ("登录后查看", "登录后搜索", "登录后浏览", "扫码登录")):
        state = "login_required"
    elif cards:
        state = "cards"
    elif any(word in text for word in ("没有找到相关", "暂无搜索结果", "没有相关结果", "暂无相关结果", "未找到相关笔记")):
        state = "empty"
    elif matches:
        state = "card_parse_failed"
    return {"state": state, "code": code if code.isdigit() else "", "card_matches": matches,
            "parsed": len(cards), "cards": cards, "path": urlsplit(url).path}


def _xhs_cards(base_url: str, soup) -> list[dict]:
    cards, seen = [], set()
    for anchor in soup.select("a[href]"):
        url = urljoin(base_url, anchor["href"])
        if not re.search(r"/(?:explore|search_result)/[a-f0-9]{24}(?:[?/#]|$)", url, re.I) or url in seen:
            continue
        seen.add(url)
        container = anchor.find_parent("section") or anchor.find_parent(class_="note-item") or anchor
        title_node = container.select_one(".title, .note-title, [class*='title']")
        title = _clean(title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True))
        cards.append({"title": title[:180] or "未取得标题的小红书笔记", "url": url})
    return cards


def _wait_xhs(page, timeout=6000) -> dict:
    deadline = monotonic() + timeout / 1000
    last_state, stable_since = None, monotonic()
    while True:
        try:
            snapshot = _xhs_snapshot(page.url, page.content())
        except Exception as exc:
            # A redirect can replace the document between URL and content reads.
            if "navigat" not in str(exc).lower() or monotonic() >= deadline:
                raise
            page.wait_for_timeout(150)
            continue
        if snapshot["state"] != last_state:
            last_state, stable_since = snapshot["state"], monotonic()
        # Login shells can flash before the application redirects or renders cards.
        stable = snapshot["state"] not in {"login_required", "empty"} or monotonic() - stable_since >= 0.8
        if snapshot["state"] not in {"loading", "card_parse_failed"} and stable:
            return snapshot
        if monotonic() >= deadline:
            if snapshot["state"] == "loading":
                snapshot["state"] = "render_timeout"
            return snapshot
        page.wait_for_timeout(150)


def _xhs_error(page) -> str:
    snapshot = _xhs_snapshot(page.url, page.content())
    if snapshot["state"] in {"restricted", "verification", "login_required"}:
        return f"小红书访问状态：{snapshot['state']}，代码 {snapshot['code'] or '无'}"
    return ""


def _xhs_links(page, timeout=6000) -> list[str]:
    return [card["url"] for card in _wait_xhs(page, timeout)["cards"]]


def _read_xhs_detail(page, card: dict, keyword: str) -> dict:
    """Keep real card metadata even when the detail body is unavailable."""
    note = {**card, "text": "", "platform": "www.xiaohongshu.com", "kind": "title_only",
            "query": keyword, "fetched_on": date.today().isoformat(), "detail_state": "body_missing"}
    try:
        page.goto(card["url"], timeout=8000, wait_until="domcontentloaded")
        snapshot = _xhs_snapshot(page.url, page.content())
        if snapshot["state"] in {"restricted", "verification", "login_required"}:
            note["detail_state"] = snapshot["state"]
            return note
        try:
            page.locator("#detail-desc").wait_for(state="visible", timeout=4000)
        except Exception as exc:
            if type(exc).__name__ != "TimeoutError":
                raise
        body = page.locator("#detail-desc")
        title = page.locator("#detail-title")
        if title.count() and title.first.is_visible():
            note["title"] = _clean(title.first.inner_text()) or note["title"]
        if body.count() and body.first.is_visible():
            note["text"] = body.first.inner_text().strip()[:10000]
        if not note["text"]:
            note_id = re.search(r"/(?:explore|search_result)/([a-f0-9]{24})", card["url"], re.I)
            if note_id:
                # Read the state the normal page already loaded, never evaluate script text.
                entry = page.evaluate("""id => {
                    const state = window.__INITIAL_STATE__;
                    const entry = state?.note?.noteDetailMap?.[id];
                    const note = entry?.note;
                    return note ? {title: note.title, desc: note.desc, id: note.noteId || note.note_id || id} : null;
                }""", note_id[1])
                if isinstance(entry, dict) and entry.get("id") == note_id[1] and isinstance(entry.get("desc"), str):
                    note["text"] = entry["desc"].strip()[:10000]
                    note["title"] = _clean(entry.get("title", "")) or note["title"]
        if note["text"]:
            note["kind"], note["detail_state"] = "article", "body_read"
    except Exception as exc:
        note["detail_state"] = "network_timeout" if type(exc).__name__ == "TimeoutError" else "detail_error"
    return note


def search_xhs_browser(keyword: str, limit: int = 3, report=None) -> list[dict]:
    """Search current trip keywords and report sanitized stage/count diagnostics."""
    def status(message):
        if report:
            report(message)
        else:
            logger.info(message)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        status("XHS stage=setup state=browser_missing cards=0 parsed=0 bodies=0")
        return []
    notes = []
    with _browser_lock:
        try:
            with sync_playwright() as playwright:
                with _browser_context(playwright) as context:
                    page = context.pages[0] if context.pages else context.new_page()
                    def search_response(response):
                        if urlsplit(response.url).path != "/api/sns/web/v1/search/notes":
                            return
                        business = "unknown"
                        try:
                            payload = response.json()
                            code = payload.get("code")
                            business = str(code) if isinstance(code, int) else "unknown"
                        except Exception:
                            pass
                        status(f"XHS stage=search_response http={response.status} business_code={business}")

                    # Observe requests made by the site's normal search UI; do not replay
                    # private endpoints, fabricate signatures or log cookies/response bodies.
                    page.on("response", search_response)
                    keywords = [keyword]
                    if len(keyword.split()) > 2:
                        keywords.append(keyword.split()[0] + " 旅游攻略")
                    for current in keywords:
                        status(f"XHS stage=search keyword={current!r}")
                        try:
                            page.goto("https://www.xiaohongshu.com/search_result?keyword=" + quote(current), timeout=10000, wait_until="domcontentloaded")
                        except Exception as exc:
                            state = "network_timeout" if type(exc).__name__ == "TimeoutError" else "navigation_error"
                            status(f"XHS stage=navigation state={state} cards=0 parsed=0 bodies=0")
                            break
                        snapshot = _wait_xhs(page)
                        status(f"XHS stage=search_page state={snapshot['state']} path={snapshot['path']} code={snapshot['code'] or '-'} cards={snapshot['card_matches']} parsed={snapshot['parsed']} bodies=0")
                        if snapshot["state"] in {"restricted", "verification", "login_required"}:
                            break
                        if not snapshot["cards"]:
                            continue
                        for index, card in enumerate(snapshot["cards"][:limit], 1):
                            note = _read_xhs_detail(page, card, current)
                            notes.append(note)
                            status(f"XHS stage=detail index={index} state={note['detail_state']} title={'yes' if note['title'] else 'no'} body_chars={len(note['text'])}")
                        break
        except Exception as exc:
            status(f"XHS stage=browser state={type(exc).__name__} cards=0 parsed=0 bodies=0")
    status(f"XHS stage=done parsed={len(notes)} bodies={sum(n['kind'] == 'article' for n in notes)} title_only={sum(n['kind'] == 'title_only' for n in notes)}")
    return notes


def login_xhs() -> None:
    """One-time manual login in the dedicated browser; never asks for a note URL."""
    from playwright.sync_api import sync_playwright

    with _browser_lock, sync_playwright() as playwright:
        with _browser_context(playwright, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.xiaohongshu.com", timeout=20000, wait_until="domcontentloaded")
            print("请在打开的小红书窗口中手动登录。若提示网络风险，请切换可靠网络后重试。", flush=True)
            input("完成登录后回到这里按 Enter 保存专用浏览器会话：")
            page.goto("https://www.xiaohongshu.com/search_result?keyword=" + quote("上海旅游攻略"), timeout=15000, wait_until="domcontentloaded")
            if error := _xhs_error(page):
                print(error + "；尚未验证搜索可用，不能视为登录抓取成功。", flush=True)
                return
            try:
                links = _xhs_links(page, timeout=10000)
                page.goto(links[0], timeout=15000, wait_until="domcontentloaded")
                page.locator("#detail-desc").wait_for(timeout=8000)
                text = page.locator("#detail-desc").inner_text().strip()
                title = page.locator("#detail-title").inner_text() if page.locator("#detail-title").count() else page.title()
                print(f"会话已保存，搜索及正文读取验证成功：{title}（{len(text)}字）。", flush=True)
            except Exception as exc:
                print(f"会话已保存，但正文验证未通过（{type(exc).__name__}）。请再次登录并检查网页提示。", flush=True)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse(url: str, html: str | bytes) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[property="og:title"]')
    title = _clean(meta.get("content", "") if meta else soup.title.get_text() if soup.title else "")
    embedded = []
    if "xiaohongshu.com" in urlsplit(url).netloc:
        for script in soup.find_all("script"):
            # Decode string literals as JSON so Chinese characters remain intact.
            for literal in re.findall(r'"(?:desc|note_desc)"\s*:\s*("(?:\\.|[^"\\])*")', script.get_text()):
                try:
                    embedded.append(json.loads(literal))
                except json.JSONDecodeError:
                    continue
    for node in soup.select("script, style, nav, footer, header, aside, form, noscript"):
        node.decompose()
    body = soup.select_one("#detail-desc, .note-content, article, main, .entry-content, #article-content, .article-content")
    if body is None:
        # Paragraphs avoid treating the whole navigation shell as article text.
        paragraphs = [_clean(p.get_text(" ", strip=True)) for p in soup.select("p")]
        body_text = "\n".join(p for p in paragraphs if len(p) >= 25)
    else:
        body_text = body.get_text("\n", strip=True)
    text = "\n".join(dict.fromkeys(_clean(x) for x in embedded + body_text.splitlines() if _clean(x)))
    return {
        "title": title[:180], "url": url, "text": text[:10000],
        "platform": urlsplit(url).netloc, "kind": "article",
        "fetched_on": date.today().isoformat(),
        "hashtags": sorted(set(re.findall(r"#[\u4e00-\u9fffA-Za-z0-9_]+", text)))[:20],
    }


def crawl_note(url: str) -> dict | None:
    """Fetch a discovered public article; login and verification pages are failures."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", "text/html"):
            return None
        note = _parse(response.url, response.content)
        blocked = ("安全验证", "访问验证", "验证码", "页面不存在", "访问受限", "登录后查看")
        if any(term in note["title"] for term in blocked) or len(note["text"]) < 120:
            return None
        return note
    except requests.RequestException:
        return None


def _search(keyword: str) -> list[dict]:
    """Bing RSS returns indexed article URLs without a search API key."""
    try:
        response = requests.get("https://www.bing.com/search", params={"q": keyword, "format": "rss"}, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return [
            {"title": item.findtext("title", ""), "url": item.findtext("link", ""),
             "text": item.findtext("description", ""), "query": keyword}
            for item in ET.fromstring(response.content).findall(".//item")
            if item.findtext("link", "").startswith("https://")
        ]
    except (requests.RequestException, ET.ParseError):
        return []


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def _distinct_articles(notes: list[dict]) -> list[dict]:
    """Do not count tracking variants or duplicated article bodies as new evidence."""
    result, urls, bodies = [], set(), set()
    for note in notes:
        if note.get("kind") == "title_only" or not note.get("text", "").strip():
            continue
        url = _canonical(note["url"])
        body = hashlib.sha256(re.sub(r"\s+", "", note["text"]).encode("utf-8")).hexdigest()
        if url not in urls and body not in bodies:
            urls.add(url)
            bodies.add(body)
            result.append(note)
    return result


def _directory_guides(location: str) -> list[dict]:
    """Discover current user posts through a travel directory, not local POIs."""
    index_url = "https://hk.trip.com/travel-guide/"
    try:
        response = requests.get(index_url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        city = location.removesuffix("市")
        link = next((a for a in soup.select('a[href*="/destination/"]')
                     if a.get_text(strip=True) == city), None)
        if link is None:
            return []
        url = urljoin(index_url, link["href"])
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        guide = _parse(response.url, response.content)
        guide["query"] = f"{location} 旅游攻略"
        guide["kind"] = "destination_guide"
        soup = BeautifulSoup(response.content, "html.parser")
        # Only follow posts in this destination, not cross-city recommendations.
        destination = urlsplit(response.url).path.rstrip('/').split('/')[-1]
        post_urls = list(dict.fromkeys(urljoin(response.url, a["href"])
                         for a in soup.select('a[href*="/moments/detail/"]')
                         if f"/moments/detail/{destination}-" in a["href"]))[:8]
        with ThreadPoolExecutor(max_workers=8) as pool:
            posts = [note for note in pool.map(crawl_note, post_urls) if note]
        for post in posts:
            post["kind"] = "travel_post"
            post["query"] = guide["query"]
        return _distinct_articles(posts + ([guide] if location in guide["title"] + guide["text"] else []))
    except requests.RequestException:
        return []


def collect_guides(queries: list[str], location: str, limit: int = 5, report=None, progress=None) -> list[dict]:
    """Collect at least three readable guides when public sources permit it."""
    if not queries:
        return []
    target = 3
    limit = max(target, limit)

    def stage(value, message):
        if report:
            report(message)
        if progress:
            progress(value, message)

    stage(0.0, "正在检索小红书和公开旅游攻略")
    with ThreadPoolExecutor(max_workers=4) as pool:
        xhs_future = pool.submit(search_xhs_browser, re.sub(r"site:\S+", "", queries[0]).strip(), 3, report)
        batches = list(pool.map(_search, queries[:3]))
        xhs_notes = xhs_future.result()
    stage(0.25, "正在筛选城市相关链接并读取正文")
    candidates = {}
    for batch in batches:
        for hit in batch:
            if location in hit["title"] + hit["text"]:
                candidates.setdefault(_canonical(hit["url"]), hit)
    if len(candidates) < target:
        stage(0.35, "相关攻略不足三篇，正在放宽检索并补充其他平台")
        broad_queries = [f"{location}旅游攻略", f"{location} 自由行 景点 路线",
                         f"{location} 游记 携程 马蜂窝 去哪儿"]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for batch in pool.map(_search, broad_queries):
                for hit in batch:
                    if location in hit["title"] + hit["text"]:
                        candidates.setdefault(_canonical(hit["url"]), hit)
    hits = list(candidates.values())[:12]
    with ThreadPoolExecutor(max_workers=8) as pool:
        articles = [None] * len(hits)
        pending = {pool.submit(crawl_note, hit["url"]): i for i, hit in enumerate(hits)}
        for completed, future in enumerate(as_completed(pending), 1):
            articles[pending[future]] = future.result()
            stage(0.40 + 0.24 * completed / len(hits), f"已处理 {completed}/{len(hits)} 个网页正文")
    for hit, article in zip(hits, articles):
        if article:
            article["query"] = hit["query"]
    ranked = _distinct_articles(xhs_notes + [n for n in articles if n and location in n["title"] + n["text"]])
    stage(0.65, f"已取得 {len(ranked)} 篇不同正文，正在检查资料覆盖")
    if len(ranked) < target:
        stage(0.7, "正在从 Trip.com 公开目录读取同城旅行帖补足三篇")
        ranked = _distinct_articles(ranked + _directory_guides(location))
    terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|\d+", " ".join(queries)))
    for note in ranked:
        note["score"] = sum(term in note["title"] + note["text"] for term in terms)
    ranked.sort(key=lambda n: ("xiaohongshu.com" in n["platform"], n.get("kind") == "travel_post", n["score"]), reverse=True)
    readable = ranked[:limit]
    if len(readable) < target:
        stage(1.0, f"公开来源不足：实际取得 {len(readable)} 篇正文，未达到三篇目标")
    else:
        stage(1.0, f"网页检索完成：已取得 {len(readable)} 篇不同正文")
    title_only = [n for n in xhs_notes if n.get("kind") == "title_only"]
    return readable + title_only[:limit]


def format_notes(notes: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {n['title']}\n来源：{n['url']}（正文抓取于 {n.get('fetched_on', '')}，非实时价格）\n{_excerpt(n)}"
        for i, n in enumerate(notes, 1) if n.get("kind") != "title_only" and n.get("text")
    )


def _excerpt(note: dict) -> str:
    """Keep relevant passages rather than truncating away later itinerary advice."""
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|\d+", note.get("query", ""))
    passages = note["text"].splitlines()
    ordered = sorted(enumerate(passages), key=lambda p: sum(t in p[1] for t in terms), reverse=True)
    selected, size = [], 0
    for index, passage in ordered:
        if size + len(passage) > 1800:
            continue
        selected.append((index, passage))
        size += len(passage)
    return "\n".join(text for _, text in sorted(selected)) or note["text"][:1800]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="小红书专用浏览器登录")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--diagnose", action="store_true", help="复现两个上海关键词并输出脱敏分阶段诊断")
    args = parser.parse_args()
    if args.login:
        login_xhs()
    elif args.diagnose:
        for keyword in ("上海五日游", "上海 外滩 豫园"):
            search_xhs_browser(keyword, report=print)
