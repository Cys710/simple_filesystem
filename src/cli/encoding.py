# -*- coding: utf-8 -*-
# 提供跨平台终端输出编码配置的辅助函数。
"""Terminal encoding helpers for cross-platform shell output."""

from __future__ import annotations

import os
import sys


# 配置标准输入、输出和错误流优先使用 UTF-8 编码。
def configure_terminal_encoding() -> None:
    """Prefer UTF-8 for interactive text streams when Python allows it."""
    # 设置 Python 进程的默认 I/O 编码，避免不同系统终端编码不一致。
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # 依次尝试重设标准流编码；旧版或特殊流不支持 reconfigure 时跳过。
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # 使用 replace 避免遇到无法编码字符时直接抛出异常。
            reconfigure(encoding="utf-8", errors="replace")
        except (TypeError, ValueError):
            # 某些运行环境不允许修改流编码，保持原设置继续运行。
            pass
