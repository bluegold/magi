#!/usr/bin/env python3
"""Compatibility launcher for the MAGI package."""

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from magi_decision.cli import install_skill, main, uninstall_skill
from magi_decision.core import decision_status, load_request

__all__ = ["decision_status", "install_skill", "load_request", "main", "uninstall_skill"]


if __name__ == "__main__":
    raise SystemExit(main())
