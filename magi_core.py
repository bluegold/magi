"""Compatibility imports for the moved MAGI core module."""

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from magi_decision.core import decision_status, load_request

__all__ = ["decision_status", "load_request"]
