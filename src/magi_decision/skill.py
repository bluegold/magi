"""Codex skill installation helpers for MAGI."""

from __future__ import annotations

import shlex
from pathlib import Path


def project_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "skills" / "magi-review" / "SKILL.md").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def skill_install_path(scope: str) -> Path:
    root = project_root() / ".agents" / "skills" if scope == "repo" else Path.home() / ".agents" / "skills"
    return root / "magi-review"


def install_skill(scope: str) -> Path:
    root = project_root()
    source = root / "skills" / "magi-review" / "SKILL.md"
    target_dir = skill_install_path(scope)
    template = source.read_text(encoding="utf-8")
    executable_path = root / "magi.py"
    if not executable_path.exists():
        executable_path = Path(__file__).resolve()
    executable = shlex.quote(str(executable_path))
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
