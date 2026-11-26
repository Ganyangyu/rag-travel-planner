"""Offline checks for Qwen's streamed final-answer response."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import planner


class QwenStreamTests(unittest.TestCase):
    def test_collects_answer_without_reasoning_or_usage(self):
        events = [
            {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
            {"choices": []},
            {"choices": [{"delta": {"content": "杭州"}}]},
            {"choices": [{"delta": {"content": "旅行建议"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        lines = [b": keepalive", b""] + [
            ("data: " + json.dumps(event, ensure_ascii=False)).encode("utf-8")
            for event in events
        ] + [b"data: [DONE]"]
        response = MagicMock()
        response.iter_lines.return_value = iter(lines)
        with patch.object(planner, "QWEN_API_KEY", "test-key"), patch.object(
            planner.requests, "post"
        ) as post:
            post.return_value.__enter__.return_value = response
            self.assertEqual(planner._qwen("测试"), "杭州旅行建议")
        payload = post.call_args.kwargs
        self.assertTrue(payload["stream"])
        self.assertTrue(payload["json"]["stream"])
        self.assertEqual(payload["json"]["enable_thinking"], planner.QWEN_ENABLE_THINKING)
        self.assertEqual(payload["json"]["model"], planner.QWEN_MODEL)
        response.raise_for_status.assert_called_once()

    def test_http_error_is_not_an_empty_answer(self):
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("403")
        with patch.object(planner, "QWEN_API_KEY", "test-key"), patch.object(
            planner.requests, "post"
        ) as post:
            post.return_value.__enter__.return_value = response
            with self.assertRaises(requests.HTTPError):
                planner._qwen("测试")

    def test_missing_key_does_not_send_request(self):
        with patch.object(planner, "QWEN_API_KEY", ""), patch.object(
            planner.requests, "post"
        ) as post:
            self.assertIsNone(planner._qwen("测试"))
            post.assert_not_called()

    def test_json_instructions_do_not_enable_incompatible_response_format(self):
        response = MagicMock()
        response.iter_lines.return_value = iter([b'data: {"choices":[{"delta":{"content":"{}"}}]}', b"data: [DONE]"])
        with patch.object(planner, "QWEN_API_KEY", "test-key"), patch.object(planner.requests, "post") as post:
            post.return_value.__enter__.return_value = response
            self.assertEqual(planner._qwen("完整行程对象", json_mode=True), "{}")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["messages"][0]["role"], "system")

    def test_live_character_progress_excludes_reasoning_and_reports_final_count(self):
        response = MagicMock()
        events = [
            {"choices": [{"delta": {"reasoning_content": "not counted"}}]},
            {"choices": [{"delta": {"content": "杭州"}}]},
            {"choices": []},
            {"choices": [{"delta": {"content": "旅行建议"}}]},
        ]
        response.iter_lines.return_value = iter([
            ("data: " + json.dumps(event)).encode() for event in events
        ] + [b"data: [DONE]"])
        counts = []
        with patch.object(planner, "QWEN_API_KEY", "test-key"), patch.object(planner.requests, "post") as post:
            post.return_value.__enter__.return_value = response
            result = planner._qwen("测试", on_progress=counts.append)
        self.assertEqual(result, "杭州旅行建议")
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[0], len("杭州"))
        self.assertEqual(counts[-1], len(result))


if __name__ == "__main__":
    unittest.main()
