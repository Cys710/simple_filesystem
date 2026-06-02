# -*- coding: utf-8 -*-
"""Terminal encoding helpers for cross-platform shell output."""

from __future__ import annotations

import os
import sys


def configure_terminal_encoding() -> None:
    """Prefer UTF-8 for interactive text streams when Python allows it."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (TypeError, ValueError):
            pass
