"""OpenAI Responses API integration for MAGI."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable


def extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    if parts:
        return "\n".join(parts)
    raise ValueError("Responses APIの応答からテキストを取得できませんでした")


def call_openai(prompt: str, model: str, on_delta: Callable[[str], None] | None = None) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEYが設定されていません。確認には--mockを使えます")
    body_data = {
        "model": model,
        "input": prompt,
        "reasoning": {"effort": "low"},
    }
    if on_delta is not None:
        body_data["stream"] = True
    body = json.dumps(body_data).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if on_delta is None:
                return extract_text(json.load(response))
            text_parts: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("type") == "response.output_text.delta":
                    delta = event.get("delta", "")
                    text_parts.append(delta)
                    on_delta(delta)
            return "".join(text_parts)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error ({error.code}): {detail[:500]}") from error
