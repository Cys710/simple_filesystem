"""
    Inode IO 模块
    负责实现 inode 的读写操作，提供了固定大小的 inode slot 来存储序列化后的 inode 对象。
    每个 inode slot 大小为 256 字节，其中前 2 字节存储序列化数据的长度，剩余部分用于存储序列化数据，块数据不足时用 0 填充。
    通过 inode_id 定位到对应的 inode slot，进行读写操作。
"""

from __future__ import annotations

from typing import Any, BinaryIO

from disk import DiskIOError, read_block, write_block
from object_io import deserialize_object, serialize_object
from head import INODE_NUM, INODE_SIZE, INODE_BLOCK_START_ID,BLOCK_SIZE

# 每个块可以存储的 inode 数量
INODES_PER_BLOCK = BLOCK_SIZE // INODE_SIZE
assert INODES_PER_BLOCK == 16, "256 bytes means 16 inodes per block"

# inode slot 头部大小（用于存储序列化数据长度）
INODE_SLOT_HEADER_SIZE = 2

class InodeIOError(Exception):
    """Inode IO 操作错误"""

# 验证inode_id是否合法
def validate_inode_id(inode_id: int) -> None:
    if not isinstance(inode_id, int):
        raise TypeError("inode_id must be an int")
    if inode_id < 0 or inode_id >= INODE_NUM:
        raise InodeIOError(
            f"inode_id must be in range [0, {INODE_NUM - 1}], got {inode_id}"
        )

# 定位inode_id对应的块ID、槽位索引和块内偏移
def locate_inode(inode_id: int) -> tuple[int, int, int]:
    """Return ``(block_id, slot_index, offset_in_block)`` for an inode id."""

    validate_inode_id(inode_id)
    # 计算inode_id对应的块ID、槽位索引和块内偏移
    inode_block_offset = inode_id // INODES_PER_BLOCK       # 块编号
    slot_index = inode_id % INODES_PER_BLOCK                # 槽位索引
    block_id = INODE_BLOCK_START_ID + inode_block_offset    # 块ID
    offset = slot_index * INODE_SIZE                        # 块内偏移
    return block_id, slot_index, offset

# 将一个inode对象序列化成一个固定256字节的槽位数据
def pack_inode_slot(inode: Any) -> bytes:

    payload = serialize_object(inode)
    capacity = INODE_SIZE - INODE_SLOT_HEADER_SIZE

    # 如果序列化后的数据超过槽位容量，则抛出错误
    if len(payload) > capacity:
        raise InodeIOError(
            f"serialized inode needs {len(payload)} bytes, capacity is {capacity}"
        )
    # 将序列化数据的长度写入槽位头部，后面跟上序列化数据，不足部分用0填充
    header = len(payload).to_bytes(
        INODE_SLOT_HEADER_SIZE, byteorder="big", signed=False
    )
    return (header + payload).ljust(INODE_SIZE, b"\x00")

# 从一个256字节的槽位数据中反序列化出一个inode对象
def unpack_inode_slot(slot: bytes) -> Any:

    if len(slot) != INODE_SIZE:
        raise InodeIOError(
            f"inode slot must be {INODE_SIZE} bytes, got {len(slot)}"
        )
    # 获取槽位头部存储的序列化数据长度
    payload_size = int.from_bytes(
        slot[:INODE_SLOT_HEADER_SIZE], byteorder="big", signed=False
    )

    if payload_size == 0:
        raise InodeIOError("inode slot is empty")

    # 计算序列化数据在槽位中的起始和结束位置，进行反序列化
    payload_start = INODE_SLOT_HEADER_SIZE
    payload_end = payload_start + payload_size

    if payload_end > INODE_SIZE:
        raise InodeIOError(
            f"payload size {payload_size} exceeds slot capacity"
        )

    return deserialize_object(slot[payload_start:payload_end])

# 清空一个inode slot，将其内容全部置零，但不改变邻近槽位的数据
def clear_inode_slot(fp: BinaryIO, inode_id: int) -> None:

    block_id, _slot_index, offset = locate_inode(inode_id)
    block = bytearray(read_block(fp, block_id))
    block[offset : offset + INODE_SIZE] = b"\x00" * INODE_SIZE
    write_block(fp, block_id, block)

# 将一个inode对象写入其固定槽位中，覆盖原有数据
def write_inode(fp: BinaryIO, inode_id: int, inode: Any) -> None:

    block_id, _slot_index, offset = locate_inode(inode_id)
    slot = pack_inode_slot(inode)

    block = bytearray(read_block(fp, block_id))
    block[offset : offset + INODE_SIZE] = slot
    write_block(fp, block_id, block)

# 从磁盘文件中读取一个inode对象，返回反序列化后的对象
def read_inode(fp: BinaryIO, inode_id: int) -> Any:

    block_id, _slot_index, offset = locate_inode(inode_id)
    block = read_block(fp, block_id)
    slot = block[offset : offset + INODE_SIZE]
    return unpack_inode_slot(slot)

# Inode磁盘混合类，提供了基于Disk类的inode读写接口
class InodeDiskMixin:

    fp: BinaryIO | None

    def write_inode(self, inode_id: int, inode: Any) -> None:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        write_inode(self.fp, inode_id, inode)

    def read_inode(self, inode_id: int) -> Any:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        return read_inode(self.fp, inode_id)

    def clear_inode_slot(self, inode_id: int) -> None:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        clear_inode_slot(self.fp, inode_id)