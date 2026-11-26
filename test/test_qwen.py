"""Smoke test for the configured Qwen-compatible API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import QWEN_API_KEY, QWEN_MODEL
from src.planner import _qwen


def main() -> int:
    if not QWEN_API_KEY:
        print("SKIP: DASHSCOPE_API_KEY/DASHSCOPE_APIKEY is not configured")
        return 0
    try:
        answer = _qwen("请只回复：千问连接成功")
        if not answer:
            print(f"FAIL: {QWEN_MODEL} returned an empty response")
            return 1
        print(f"PASS: {QWEN_MODEL} returned: {answer[:120]}")
        return 0
    except Exception as exc:
        print(f"FAIL: Qwen request failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
