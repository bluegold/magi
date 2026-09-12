"""Installed command entry point.

The implementation remains import-compatible with the root ``magi.py``
launcher while the internal modules are migrated incrementally.
"""

from magi import main

__all__ = ["main"]
