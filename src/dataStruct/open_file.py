from __future__ import annotations

from dataclasses import dataclass

from core.inode_cache import MemoryInode


@dataclass
class OpenFile:
    fd: int
    memory_inode: MemoryInode
    path: str
    mode: str
    offset: int = 0
    readable: bool = False
    writable: bool = False
    lock_mode: str = "read"

    @property
    def inode_id(self) -> int:
        return self.memory_inode.inode_id

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
