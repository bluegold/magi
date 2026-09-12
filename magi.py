#!/usr/bin/env python3
"""Minimal MAGI decision engine for Codex skill integration."""

from __future__ import annotations

import argparse
import concurrent.futures
import curses
import json
import os
import queue
import shlex
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable
from pathlib import Path

from magi_core import decision_status, load_request


PERSONAS = {
    "MELCHIOR": "技術責任者。実装可能性、保守性、性能、依存関係を重視する。",
    "BALTHASAR": "リスク審査役。失敗条件、セキュリティ、運用負荷、反対材料を厳しく探す。",
    "CASPER": "利用者・事業責任者。目的への適合性、利用者価値、期限、費用対効果を重視する。",
}


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WFA" else 1 for char in text)


def wrap_display(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for source_line in text.splitlines() or [""]:
        current = ""
        current_width = 0
        for char in source_line:
            char_width = 2 if unicodedata.east_asian_width(char) in "WFA" else 1
            if current and current_width + char_width > width:
                lines.append(current)
                current = ""
                current_width = 0
            current += char
            current_width += char_width
        lines.append(current)
    return lines


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


def skill_install_path(scope: str) -> Path:
    if scope == "repo":
        root = Path(__file__).resolve().parent / ".agents" / "skills"
    else:
        root = Path.home() / ".agents" / "skills"
    return root / "magi-review"


def install_skill(scope: str) -> Path:
    source = Path(__file__).resolve().parent / "skills" / "magi-review" / "SKILL.md"
    target_dir = skill_install_path(scope)
    template = source.read_text(encoding="utf-8")
    executable = shlex.quote(str(Path(__file__).resolve()))
    if "{{MAGI_EXECUTABLE}}" not in template:
        raise RuntimeError("スキルテンプレートに{{MAGI_EXECUTABLE}}がありません")
    installed = template.replace("{{MAGI_EXECUTABLE}}", executable)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(installed, encoding="utf-8")
    return target_dir


def uninstall_skill(scope: str) -> Path:
    target_dir = skill_install_path(scope)
    skill_file = target_dir / "SKILL.md"
    if skill_file.exists():
        skill_file.unlink()
    try:
        target_dir.rmdir()
    except OSError:
        pass
    return target_dir


def run_tui(request: dict[str, Any], model: str, mock: bool) -> tuple[list[dict[str, str]], str]:
    """Run MAGI with one live pane per persona and one pane for the judge."""
    events: queue.Queue[tuple[str, str]] = queue.Queue()
    names = [*PERSONAS, "JUDGE"]
    buffers = {name: "" for name in names}
    statuses = {name: "待機中" for name in names}
    scroll = {name: 0 for name in names}
    focused = [0]
    result: dict[str, Any] = {}

    def emit(name: str, delta: str) -> None:
        events.put((name, delta))

    def draw(stdscr: Any, current_phase: str) -> None:
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        title = f"MAGI TUI  |  {current_phase}  |  Ctrl-Cで終了"
        stdscr.addnstr(0, 0, title, max(0, width - 1), curses.A_BOLD)
        pane_width = max(12, width // 3)
        judge_expanded = current_phase.startswith("JUDGE") or current_phase == "完了"
        judge_y = max(4, height // 2) if judge_expanded else max(4, height - 4)
        pane_height = max(2, judge_y - 2)
        for index, name in enumerate(PERSONAS):
            x = index * pane_width
            pane_title = f" {name} [{statuses[name]}] "
            title_attr = curses.A_REVERSE | (curses.A_BOLD if focused[0] == index else 0)
            stdscr.addnstr(1, x, pane_title, max(0, pane_width - 1), title_attr)
            lines = wrap_display(buffers[name], max(1, pane_width - 2))
            visible_height = pane_height - 1
            max_scroll = max(0, len(lines) - visible_height)
            scroll[name] = min(scroll[name], max_scroll)
            line_end = len(lines) - scroll[name]
            line_start = max(0, line_end - visible_height)
            visible = lines[line_start:line_end]
            for line_no, line in enumerate(visible, start=2):
                if line_no < judge_y:
                    stdscr.addnstr(line_no, x, line, max(0, pane_width - 1))
        judge_attr = curses.A_REVERSE | (curses.A_BOLD if focused[0] == len(PERSONAS) else 0)
        stdscr.addnstr(judge_y, 0, f" JUDGE [{statuses['JUDGE']}] ", max(0, width - 1), judge_attr)
        judge_lines = wrap_display(buffers["JUDGE"], max(1, width - 2))
        judge_height = max(1, height - judge_y - 1)
        judge_max_scroll = max(0, len(judge_lines) - judge_height)
        scroll["JUDGE"] = min(scroll["JUDGE"], judge_max_scroll)
        judge_end = len(judge_lines) - scroll["JUDGE"]
        judge_start = max(0, judge_end - judge_height)
        for line_no, line in enumerate(judge_lines[judge_start:judge_end], start=judge_y + 1):
            if line_no < height:
                stdscr.addnstr(line_no, 0, line, max(0, width - 1))
        stdscr.refresh()

    def handle_key(stdscr: Any) -> bool:
        key = stdscr.getch()
        if key < 0:
            return False
        if key in (ord("q"), 27):
            return True
        if key in (9, curses.KEY_RIGHT):
            focused[0] = (focused[0] + 1) % len(names)
        elif key == curses.KEY_LEFT:
            focused[0] = (focused[0] - 1) % len(names)
        else:
            name = names[focused[0]]
            if key in (curses.KEY_UP, ord("k")):
                scroll[name] += 1
            elif key in (curses.KEY_DOWN, ord("j")):
                scroll[name] = max(0, scroll[name] - 1)
            elif key == curses.KEY_PPAGE:
                scroll[name] += 8
            elif key == curses.KEY_NPAGE:
                scroll[name] = max(0, scroll[name] - 8)
            elif key == curses.KEY_HOME:
                scroll[name] = 10**9
            elif key == curses.KEY_END:
                scroll[name] = 0
        return False

    def drain() -> None:
        while True:
            try:
                name, delta = events.get_nowait()
            except queue.Empty:
                return
            buffers[name] += delta
            statuses[name] = "生成中"

    def run(stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.nodelay(True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                name: pool.submit(
                    run_agent,
                    name,
                    request,
                    model,
                    mock,
                    lambda delta, persona=name: emit(persona, delta),
                )
                for name in PERSONAS
            }
            while not all(future.done() for future in futures.values()):
                drain()
                draw(stdscr, "3者を並列評価中")
                handle_key(stdscr)
                time.sleep(0.05)
            drain()
            agent_results: dict[str, dict[str, str]] = {}
            for name, future in futures.items():
                agent_results[name] = future.result()
                statuses[name] = decision_status(agent_results[name]["analysis"])
            analyses = [agent_results[name] for name in PERSONAS]
            if mock:
                def mock_judge() -> str:
                    judgment = mock_response("JUDGE", request)
                    emit("JUDGE", judgment)
                    return judgment

                judge_future = pool.submit(mock_judge)
            else:
                statuses["JUDGE"] = "生成中"
                judge_future = pool.submit(
                    call_openai,
                    make_judge_prompt(request, analyses),
                    model,
                    lambda delta: emit("JUDGE", delta),
                )
            while not judge_future.done():
                drain()
                draw(stdscr, "JUDGEが統合中")
                handle_key(stdscr)
                time.sleep(0.05)
            drain()
            judge = judge_future.result()
            statuses["JUDGE"] = "完了"
            result["analyses"] = analyses
            result["judgment"] = judge
            height, width = stdscr.getmaxyx()
            prompt = "完了しました。qまたはEscで終了、Tab/矢印で確認できます。"
            while not handle_key(stdscr):
                draw(stdscr, "完了")
                stdscr.addnstr(max(0, height - 1), 0, prompt, max(0, width - 1), curses.A_BOLD)
                stdscr.refresh()
                time.sleep(0.05)

    curses.wrapper(run)
    return result["analyses"], result["judgment"]


def main() -> int:
    parser = argparse.ArgumentParser(description="MAGI multi-perspective decision engine")
    parser.add_argument("request", nargs="?", help="判定依頼JSON")
    install_group = parser.add_mutually_exclusive_group()
    install_group.add_argument("--install", action="store_true", help="Codexスキルをインストール")
    install_group.add_argument("--uninstall", action="store_true", help="Codexスキルをアンインストール")
    parser.add_argument("--scope", choices=("user", "repo"), default="user", help="スキルの配置先")
    parser.add_argument("--mock", action="store_true", help="APIを呼ばずに実行")
    parser.add_argument("--stream", action="store_true", help="各人格の回答をstderrへ逐次表示")
    parser.add_argument("--tui", action="store_true", help="人格ごとのペインで逐次表示")
    parser.add_argument("--model", default=os.environ.get("MAGI_MODEL", "gpt-5.4-mini"))
    args = parser.parse_args()
    if args.stream and args.tui:
        parser.error("--streamと--tuiは同時に指定できません")
    if (args.install or args.uninstall) and args.request:
        parser.error("--install/--uninstallと判定依頼JSONは同時に指定できません")
    if not (args.install or args.uninstall) and not args.request:
        parser.error("判定依頼JSON、--install、または--uninstallを指定してください")
    try:
        if args.install:
            print(f"Installed skill: {install_skill(args.scope)}")
            return 0
        if args.uninstall:
            print(f"Uninstalled skill: {uninstall_skill(args.scope)}")
            return 0
        request = load_request(args.request)
        if args.tui:
            analyses, judge = run_tui(request, args.model, args.mock)
            print(json.dumps({"request": request, "analyses": analyses, "judgment": judge}, ensure_ascii=False, indent=2))
            return 0
        output_lock = threading.Lock()

        def show_delta(persona: str, delta: str) -> None:
            with output_lock:
                print(f"[{persona}] {delta}", end="", file=sys.stderr, flush=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(
                    run_agent,
                    name,
                    request,
                    args.model,
                    args.mock,
                    (lambda delta, persona=name: show_delta(persona, delta)) if args.stream else None,
                )
                for name in PERSONAS
            ]
            analyses = [future.result() for future in futures]
        if args.stream:
            print("\n[JUDGE] ", end="", file=sys.stderr, flush=True)
        if args.mock:
            judge = mock_response("JUDGE", request)
            if args.stream:
                print(judge, end="", file=sys.stderr, flush=True)
        else:
            judge = call_openai(
                make_judge_prompt(request, analyses),
                args.model,
                (lambda delta: print(delta, end="", file=sys.stderr, flush=True)) if args.stream else None,
            )
        if args.stream:
            print(file=sys.stderr)
        print(json.dumps({"request": request, "analyses": analyses, "judgment": judge}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"MAGI error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
