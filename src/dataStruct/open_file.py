from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OpenFile:
    fd: int
    inode_id: int
    path: str
    mode: str
    offset: int = 0
    readable: bool = False
    writable: bool = False

# 解析文件打开模式
def parse_open_mode(mode: str) -> tuple[bool, bool, bool, bool, int]:
    if mode not in {"r", "w", "a", "r+", "w+", "a+"}:
        raise ValueError(f"unsupported open mode: {mode}")

    readable = "r" in mode or "+" in mode
    writable = "w" in mode or "a" in mode or "+" in mode
    create = "w" in mode or "a" in mode
    truncate = "w" in mode
    append = "a" in mode
    offset = -1 if append else 0
    return readable, writable, create, truncate, offset
