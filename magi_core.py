"""Pure request validation and decision parsing for MAGI."""

from __future__ import annotations

import json
import re
from typing import Any


def decision_status(text: str) -> str:
    """Extract a compact decision badge from an agent's answer."""
    match = re.search(
        r"(?:推奨案|推奨|結論)\s*[:：]\s*\**\s*(条件付き採用|採用|見送り|承認|否決)",
        text,
    )
    if not match:
        return "完了"
    return {
        "採用": "承認",
        "承認": "承認",
        "見送り": "否決",
        "否決": "否決",
        "条件付き採用": "条件付き",
    }[match.group(1)]


def load_request(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        request = json.load(file)
    required = ("subject", "criteria")
    missing = [key for key in required if not request.get(key)]
    if missing:
        raise ValueError(f"必須項目がありません: {', '.join(missing)}")
    if not isinstance(request["criteria"], list):
        raise ValueError("criteriaは配列で指定してください")
    if any(not item.get("name") for item in request["criteria"]):
        raise ValueError("criteriaの各要素にはnameが必要です")
    return request
