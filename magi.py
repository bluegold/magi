#!/usr/bin/env python3
"""Minimal MAGI decision engine for Codex skill integration."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


PERSONAS = {
    "MELCHIOR": "技術責任者。実装可能性、保守性、性能、依存関係を重視する。",
    "BALTHASAR": "リスク審査役。失敗条件、セキュリティ、運用負荷、反対材料を厳しく探す。",
    "CASPER": "利用者・事業責任者。目的への適合性、利用者価値、期限、費用対効果を重視する。",
}


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


def make_prompt(request: dict[str, Any], persona_name: str) -> str:
    criteria = json.dumps(request["criteria"], ensure_ascii=False)
    constraints = json.dumps(request.get("constraints", []), ensure_ascii=False)
    options = json.dumps(request.get("options", []), ensure_ascii=False)
    return f"""あなたはMAGIの{persona_name}です。{PERSONAS[persona_name]}

対象:
{request['subject']}

背景:
{request.get('context', 'なし')}

判定基準と重み:
{criteria}

制約:
{constraints}

選択肢:
{options}

各criteriaを0から100で評価し、根拠を短く示してください。
最後に推奨案、確信度(0から1)、最大の懸念、追加確認事項を示してください。
事実と推測を分け、情報不足は明記してください。"""


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


def call_openai(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEYが設定されていません。確認には--mockを使えます")
    body = json.dumps({
        "model": model,
        "input": prompt,
        "reasoning": {"effort": "low"},
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return extract_text(json.load(response))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error ({error.code}): {detail[:500]}") from error


def mock_response(persona_name: str, request: dict[str, Any]) -> str:
    criteria = ", ".join(item["name"] for item in request["criteria"])
    return (f"{persona_name}のモック判定。基準({criteria})を確認した。\n"
            "推奨案: 条件付き採用\n確信度: 0.50\n"
            "最大の懸念: 根拠資料が不足している。\n追加確認事項: 期限と互換性を検証する。")


def run_agent(name: str, request: dict[str, Any], model: str, mock: bool) -> dict[str, str]:
    prompt = make_prompt(request, name)
    return {"persona": name, "analysis": mock_response(name, request) if mock else call_openai(prompt, model)}


def make_judge_prompt(request: dict[str, Any], analyses: list[dict[str, str]]) -> str:
    return f"""あなたはMAGIの統合判定役です。
対象: {request['subject']}
判定基準: {json.dumps(request['criteria'], ensure_ascii=False)}
制約: {json.dumps(request.get('constraints', []), ensure_ascii=False)}
選択肢: {json.dumps(request.get('options', []), ensure_ascii=False)}

3者の分析:
{json.dumps(analyses, ensure_ascii=False, indent=2)}

意見を単純多数決せず、根拠の質、criteriaとの整合性、意見の相違を比較してください。
次の形式で日本語回答してください:
結論:
確信度:
判断理由:
各criteriaの評価:
意見が割れた点:
追加確認事項:
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="MAGI multi-perspective decision engine")
    parser.add_argument("request", help="判定依頼JSON")
    parser.add_argument("--mock", action="store_true", help="APIを呼ばずに実行")
    parser.add_argument("--model", default=os.environ.get("MAGI_MODEL", "gpt-5.4-mini"))
    args = parser.parse_args()
    try:
        request = load_request(args.request)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(run_agent, name, request, args.model, args.mock) for name in PERSONAS]
            analyses = [future.result() for future in futures]
        judge = mock_response("JUDGE", request) if args.mock else call_openai(make_judge_prompt(request, analyses), args.model)
        print(json.dumps({"request": request, "analyses": analyses, "judgment": judge}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"MAGI error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
