"""Offline checks for trip constraints and grounded generation."""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.profile import trip_profile
from src.planner import plan
from src.crawler import _parse


def sample_content(days=2):
    return {
        "overview": "建议住市区公共交通便利片区，以同片区慢游为主。",
        "days": [{"main": "片区漫步与休息", "details": "上午慢游1小时，午餐在酒店片区；下午休息，晚到则取消上午安排。[1]"} for _ in range(days)],
        "budget": {"people": None, "rooms": None, "room_rate": 150,
                   "meals_per_person_day": 50, "tickets_per_person": 60,
                   "transport": {"basis": "person", "unit_price": 10, "quantity": 4}, "reserve_per_person": 50},
        "preparations": ["先确认住宿房型与证件"],
        "uncertainties": ["出发前通过景点官网确认开放安排；未开放则改在酒店片区休息"],
        "alternatives": [{"original": "室外漫步", "trigger": t, "replacement": "改在酒店片区休息，原活动移至弹性日"} for t in ["下雨", "预约失败", "晚到", "体力不足"]],
        "tips": ["优先同片区游览，避免往返"],
    }


class WorkflowTests(unittest.TestCase):
    def test_holiday_and_budget(self):
        p = trip_profile("杭州", "2026-10-01", 3, 1200, "亲子家庭")
        self.assertEqual(p["calendar"], "国庆节")
        self.assertEqual(p["rest_days"], 3)
        self.assertEqual(p["daily_budget"], 400)
        self.assertIn("亲子家庭", p["queries"][0])
        self.assertIn("1200", p["queries"][1])

    def test_season_boundary_and_unknown_calendar(self):
        p = trip_profile("杭州", "2026-11-30", 2, 1000, "情侣")
        self.assertEqual(p["season"], "秋季、冬季")
        p = trip_profile("杭州", "2099-10-01", 2, 1000, "情侣")
        self.assertIn("待确认", p["calendar"])

    def test_prompt_contains_constraints_and_evidence(self):
        p = trip_profile("杭州", "2026-12-01", 2, 1000, "情侣")
        with patch("src.planner._qwen", return_value=json.dumps(sample_content())) as model:
            result = plan(p, [], "[1] 旅行证据")
        prompt = model.call_args.args[0]
        for term in ["冬季", "情侣", "500", "[1] 旅行证据", "1晚"]:
            self.assertIn(term, prompt)
        headings = ["一、整体安排", "二、每日详细日程", "三、预算检查", "四、旅行前准备", "五、待核实清单", "六、下雨或行程变化时", "七、旅行建议"]
        self.assertEqual([result.index(h) for h in headings], sorted(result.index(h) for h in headings))
        self.assertEqual(result.count("预算检查"), 1)

    def test_missing_web_evidence_still_delivers_conditional_plan(self):
        p = trip_profile("上海", "2026-11-26", 5, 1000, "老年人")
        with patch("src.planner._qwen", return_value=json.dumps(sample_content(5))) as model:
            result = plan(p, [{"name": "不应使用的本地示例"}], "")
        model.assert_called_once()
        self.assertNotIn("不应使用的本地示例", model.call_args.args[0])
        self.assertIn("含预留计划 1000.00 元/人", result)
        self.assertIn("人数尚未提供", result)

    def test_ui_keeps_empty_crawl_diagnostics_out_of_answer(self):
        from app import generate
        with patch("app.collect_guides", return_value=[]), patch("app.plan", return_value="可用候选方案") as model:
            result = list(generate("上海", "2026-11-26", 5, 1000, "老年人"))[-1]
        model.assert_called_once()
        self.assertEqual(result, "可用候选方案")
        self.assertNotIn("参考帖子", result)
        self.assertNotIn("--login", result)

    def test_single_object_array_from_compatible_endpoint(self):
        p = trip_profile("上海", "2026-11-26", 5, 1000, "老年人")
        sample = sample_content(5)
        sample["budget"]["people"] = 2
        sample["budget"]["rooms"] = 1
        with patch("src.planner._qwen", return_value=json.dumps([sample])):
            result = plan(p, [], "[1] 上海资料")
        self.assertIn("人数尚未提供", result)
        self.assertIn("150.00元/房/晚 × 1间 × 4晚", result)
        self.assertIn("1000.00", result)

    def test_json_fence_is_parsed_without_rendering_machine_payload(self):
        p = trip_profile("上海", "2026-11-26", 5, 1000, "老年人")
        payload = "```json\n" + json.dumps(sample_content(5)) + "\n```"
        with patch("src.planner._qwen", return_value=payload):
            result = plan(p, [], "[1] 上海资料")
        self.assertIn("七、旅行建议", result)
        self.assertNotIn('"overview"', result)

    def test_nested_alternatives_array_is_not_treated_as_complete_itinerary(self):
        p = trip_profile("上海", "2026-11-26", 5, 1000, "老年人")
        payload = json.dumps(sample_content(5)["alternatives"])
        with patch("src.planner._qwen", return_value=payload), self.assertLogs("src.planner", level="ERROR"):
            result = plan(p, [], "[1] 上海资料")
        self.assertIn("本次方案暂未完成", result)
        self.assertNotIn("Traceback", result)

    def test_embedded_chinese_is_not_corrupted(self):
        page = '<title>杭州攻略</title><script>window.state={"desc":"西湖游览路线，下午去灵隐寺"}</script>'
        note = _parse("https://www.xiaohongshu.com/explore/demo", page)
        self.assertIn("西湖游览路线", note["text"])

    def test_percentage_progress_and_three_consulted_sources(self):
        from app import generate
        notes = [{"title": f"北京攻略{i}", "url": f"https://example.com/{i}", "text": "北京旅游正文"} for i in range(3)]

        def crawl(*args, **kwargs):
            kwargs["progress"](0.2, "正在检索")
            kwargs["progress"](1.0, "正文读取完成")
            return notes

        tracker = MagicMock()
        with patch("app.collect_guides", side_effect=crawl), patch("app.plan", return_value="完整行程[1]") as model:
            result = list(generate("北京", "2026-12-01", 3, 1500, "情侣", progress=tracker))[-1]
        values = [call.args[0] for call in tracker.call_args_list]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 1)
        self.assertIn("100%", tracker.call_args_list[-1].kwargs["desc"])
        for i in range(3):
            self.assertIn(f"北京攻略{i}", result)
            self.assertIn(f"https://example.com/{i}", model.call_args.args[2])

    def test_title_only_note_is_not_passed_as_read_body(self):
        from app import generate
        note = {"title": "上海五日游笔记", "url": "https://www.xiaohongshu.com/explore/demo", "text": "", "kind": "title_only"}
        with patch("app.collect_guides", return_value=[note]), patch("app.plan", return_value="完整行程") as model:
            result = list(generate("上海", "2026-11-26", 5, 1000, "老年人"))[-1]
        self.assertEqual(model.call_args.args[2], "")
        self.assertIn("仅取得标题", result)
        self.assertIn("上海五日游笔记", result)
        self.assertNotIn("### 参考帖子与攻略", result)

    def test_fixed_ui_bar_updates_during_model_stream(self):
        from app import generate_ui
        import re

        def fake_plan(*args, **kwargs):
            kwargs["on_status"]("千问已连接，正在生成回答")
            for count in (100, 1000, 3000, 6000):
                kwargs["on_progress"](count)
            return "完整行程"

        with patch("app.collect_guides", return_value=[]), patch("app.plan", side_effect=fake_plan):
            updates = list(generate_ui("北京", "2026-12-01", 3, 1500, "情侣"))
        percentages = [float(re.search(r'aria-valuenow="([\d.]+)"', bar)[1]) for bar, _ in updates]
        self.assertEqual(percentages, sorted(percentages))
        self.assertGreaterEqual(len({n for n in percentages if 65 < n < 95}), 4)
        self.assertEqual(percentages[-1], 100)
        self.assertIn("完整行程", updates[-1][1])
        self.assertTrue(any("估算进度" in bar for bar, _ in updates))

    def test_fixed_bar_preserves_validation_messages(self):
        from app import generate_ui
        result = list(generate_ui("", "2026-12-01", 3, 1500, "情侣"))
        self.assertIn("请先填写目的地", result[-1][1])

    def test_ui_yields_before_network_and_preserves_source_titles(self):
        from app import generate
        note = {"title": "杭州冬季情侣攻略", "url": "https://example.com/guide", "text": "西湖路线", "platform": "example.com"}

        def fake_plan(*args, **kwargs):
            kwargs["on_status"]("模型已连接")
            kwargs["on_text"]("正在输出的行程")
            return "完整行程[1]"

        with patch("app.collect_guides", return_value=[note]) as crawl, patch("app.plan", side_effect=fake_plan):
            stream = generate("杭州", "2026-12-01", 2, 1000, "情侣")
            self.assertIn("路线", next(stream))
            crawl.assert_not_called()
            updates = list(stream)
        self.assertTrue(any("正在输出的行程" in item for item in updates))
        self.assertIn("完整行程", updates[-1])
        self.assertNotIn("模型已连接", updates[-1])
        self.assertIn("杭州冬季情侣攻略", updates[-1])
        self.assertIn("https://example.com/guide", updates[-1])


if __name__ == "__main__":
    unittest.main()
