from __future__ import annotations

"""
    第一层：磁盘部分 -> 文件句柄
    disk.py 用于实现磁盘的读写操作，提供了一个 Disk 类作为接口
    封装了磁盘的创建、格式化、打开、关闭以及块读写等功能。
    磁盘读写的大小为 簇大小（块大小）
"""

from pathlib import Path
from typing import BinaryIO

from head import BLOCK_NUM, BLOCK_SIZE, DISK_SIZE, DISK_NAME

class DiskIOError(Exception):
    """磁盘操作错误"""

# 字符串路径转换为 Path 对象
def _normalize_path(path: str | Path = DISK_NAME) -> Path:
    return Path(path)

# 验证块ID是否合法
def validate_block_id(block_id: int) -> None:
    if not isinstance(block_id, int):
        raise TypeError("block_id must be an int")
    if block_id < 0 or block_id >= BLOCK_NUM:
        raise DiskIOError(
            f"block_id must be in range [0, {BLOCK_NUM - 1}], got {block_id}"
        )

# 创建磁盘文件，写入空数据
def create_disk(path: str | Path = DISK_NAME, *, overwrite: bool = False) -> Path:

    disk_path = _normalize_path(path)
    # 如果磁盘文件已存在且不允许覆盖，则抛出错误
    if disk_path.exists() and not overwrite:
        raise FileExistsError(f"disk image already exists: {disk_path}")

    parent = disk_path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)

    # 创建磁盘文件,设置大小为 DISK_SIZE
    with disk_path.open("wb") as fp:
        fp.truncate(DISK_SIZE)

    return disk_path

# 格式化磁盘，创建一个新的磁盘文件，覆盖原有数据
def format_disk(path: str | Path = DISK_NAME) -> Path:
    return create_disk(path, overwrite=True)

# 打开磁盘文件，返回一个二进制文件对象（文件句柄）
def open_disk(path: str | Path = DISK_NAME, mode: str = "r+b") -> BinaryIO:

    disk_path = _normalize_path(path)
    if not disk_path.exists():
        raise DiskIOError(f"disk image does not exist: {disk_path}")

    return disk_path.open(mode)

# 从磁盘文件中读取一个块的数据，返回字节数据
def read_block(fp: BinaryIO, block_id: int) -> bytes:

    validate_block_id(block_id)
    fp.seek(block_id * BLOCK_SIZE)
    data = fp.read(BLOCK_SIZE)

    if len(data) != BLOCK_SIZE:
        raise DiskIOError(
            f"could not read full block {block_id}: expected {BLOCK_SIZE}, got {len(data)}"
        )

    return data

# 磁盘文件写入一个块的数据
def write_block(fp: BinaryIO, block_id: int, data: bytes | bytearray) -> None:

    validate_block_id(block_id)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes or bytearray")
    if len(data) > BLOCK_SIZE:
        raise DiskIOError(
            f"data is larger than one block: {len(data)} > {BLOCK_SIZE}"
        )

    # 将数据写入指定块，数据不足一个块时用0填充
    fp.seek(block_id * BLOCK_SIZE)
    fp.write(bytes(data).ljust(BLOCK_SIZE, b"\x00"))
    fp.flush()

# Disk 类封装了磁盘操作
class Disk:

    def __init__(self, path: str | Path = DISK_NAME):
        self.path = _normalize_path(path)
        self.fp: BinaryIO | None = None

    def create(self, *, overwrite: bool = False) -> Path:
        return create_disk(self.path, overwrite=overwrite)

    def format(self) -> Path:
        return format_disk(self.path)

    def open(self) -> "Disk":
        self.fp = open_disk(self.path)
        return self

    def close(self) -> None:
        if self.fp is not None:
            self.fp.close()
            self.fp = None

    def read_block(self, block_id: int) -> bytes:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        return read_block(self.fp, block_id)

    def write_block(self, block_id: int, data: bytes | bytearray) -> None:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        write_block(self.fp, block_id, data)

    def __enter__(self) -> "Disk":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()