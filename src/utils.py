"""
    系统工具函数,方便实现一些功能
"""


from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from head import BLOCK_SIZE, BLUE, DIRECT_CNT, LOGO, RESET

if TYPE_CHECKING:
    from core.file_system import FileSystem


INDIRECT_INDEX_TEST_BYTES = DIRECT_CNT * BLOCK_SIZE

def logo():
    logo_str = LOGO
    print(BLUE + logo_str + RESET)


def append_test_data(
    fs: "FileSystem",
    path: str,
    byte_count: int = INDIRECT_INDEX_TEST_BYTES,
    *,
    fill_byte: bytes = b"x",
) -> int:
    """Append deterministic bytes to a file for block-allocation demonstrations."""

    if byte_count < 0:
        raise ValueError("byte_count cannot be negative")
    if not isinstance(fill_byte, bytes) or len(fill_byte) != 1:
        raise ValueError("fill_byte must contain exactly one byte")
    return fs.write_file(path, fill_byte * byte_count, append=True)
