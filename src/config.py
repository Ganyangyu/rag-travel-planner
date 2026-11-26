"""Application configuration kept in environment variables."""

import os
import json
from pathlib import Path


_shared_path = Path(__file__).resolve().parent.parent / "shared_access.json"
_shared = json.loads(_shared_path.read_text(encoding="utf-8")) if _shared_path.exists() else {}

QWEN_API_KEY = os.getenv("DASHSCOPE_APIKEY") or os.getenv("DASHSCOPE_API_KEY") or _shared.get("model_api_key", "")
XHS_COOKIE = os.getenv("XHS_COOKIE") or _shared.get("xhs_cookie", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen4-max")
QWEN_ENABLE_THINKING = os.getenv("QWEN_ENABLE_THINKING", "false").lower() == "true"
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1",
)
