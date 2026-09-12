"""Parallel persona orchestration for MAGI decisions."""

from __future__ import annotations

import json
from typing import Any, Callable

from .provider import call_openai


PERSONAS = {
    "MELCHIOR": "技術責任者。実装可能性、保守性、性能、依存関係を重視する。",
    "BALTHASAR": "リスク審査役。失敗条件、セキュリティ、運用負荷、反対材料を厳しく探す。",
    "CASPER": "利用者・事業責任者。目的への適合性、利用者価値、期限、費用対効果を重視する。",
}


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


def mock_response(persona_name: str, request: dict[str, Any]) -> str:
    criteria = ", ".join(item["name"] for item in request["criteria"])
    return (f"{persona_name}のモック判定。基準({criteria})を確認した。\n"
            "推奨案: 条件付き採用\n確信度: 0.50\n"
            "最大の懸念: 根拠資料が不足している。\n追加確認事項: 期限と互換性を検証する。")


def run_agent(
    name: str,
    request: dict[str, Any],
    model: str,
    mock: bool,
    on_delta: Callable[[str], None] | None = None,
) -> dict[str, str]:
    prompt = make_prompt(request, name)
    if mock:
        analysis = mock_response(name, request)
        if on_delta is not None:
            on_delta(analysis)
        return {"persona": name, "analysis": analysis}
    return {
        "persona": name,
        "analysis": call_openai(prompt, model, on_delta),
    }


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
