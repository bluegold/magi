#!/usr/bin/env python3
"""Minimal MAGI decision engine for Codex skill integration."""

from __future__ import annotations

import argparse
import concurrent.futures
import curses
import json
import os
import queue
import sys
import threading
import time
import unicodedata
from typing import Any, Callable
from .core import decision_status, load_request
from .orchestrator import PERSONAS, make_judge_prompt, mock_response, run_agent
from .provider import call_openai
from .skill import install_skill, uninstall_skill


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
