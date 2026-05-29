from __future__ import annotations

"""
    对象序列化工具和对象IO -> 对象磁盘
    object.py 用于实现对象的序列化和反序列化，以及对象的IO操作，提供了一个 ObjectDisk 类作为接口
    封装了对象的写入和读取功能，支持将对象存储在一个或多个连续块中。
"""

import pickle
from typing import Any, BinaryIO

from storage.disk import BLOCK_SIZE, Disk, DiskIOError, read_block, write_block

# 对象序列化格式：HEADER_SIZE字节的头部 + 负载数据
# 头部存储负载数据的长度,头部长度为8字节
HEADER_SIZE = 8

class ObjectIOError(Exception):
    """对象序列化IO错误"""

# 序列化对象为字节数据
def serialize_object(obj: Any) -> bytes:
    return pickle.dumps(obj)

# 反序列化字节数据为对象
def deserialize_object(data: bytes) -> Any:

    return pickle.loads(data)

# 将对象序列化为块数据，返回字节数据
def pack_object(obj: Any, *, block_count: int = 1) -> bytes:

    if block_count <= 0:
        raise ValueError("block_count must be positive")
    
    # 计算大小并验证是否超过块容量
    payload = serialize_object(obj)
    capacity = block_count * BLOCK_SIZE
    required = HEADER_SIZE + len(payload)

    if required > capacity:
        raise ObjectIOError(
            f"serialized object needs {required} bytes, capacity is {capacity}"
        )

    # 将头部和负载数据组合成块数据，头部存储负载数据的长度，块数据不足时用0填充
    header = len(payload).to_bytes(HEADER_SIZE, byteorder="big", signed=False)
    return (header + payload).ljust(capacity, b"\x00")

# 从块数据中读取一个对象，返回对象
def unpack_object(data: bytes) -> Any:

    if len(data) < HEADER_SIZE:
        raise ObjectIOError("object data is shorter than the header")
    
    # 从头部读取负载数据的长度，并验证是否超过可用数据
    payload_size = int.from_bytes(data[:HEADER_SIZE], byteorder="big", signed=False)
    payload_start = HEADER_SIZE
    payload_end = payload_start + payload_size

    if payload_size <= 0:
        raise ObjectIOError("object payload size must be positive")
    if payload_end > len(data):
        raise ObjectIOError(
            f"payload size {payload_size} exceeds available data {len(data) - HEADER_SIZE}"
        )

    return deserialize_object(data[payload_start:payload_end])

# 将一个对象写入一个或多个连续块中
def write_object(
    fp: BinaryIO,           # 文件对象(磁盘对象)
    start_block_id: int,    # 起始块ID
    obj: Any,               # 要写入的对象
    *,          
    block_count: int = 1,   # 占用的块数
) -> None:
    packed = pack_object(obj, block_count=block_count)

    for index in range(block_count):
        block = packed[index * BLOCK_SIZE : (index + 1) * BLOCK_SIZE]
        write_block(fp, start_block_id + index, block)

# 从一个或多个连续块中读取一个对象，返回对象
def read_object(
    fp: BinaryIO,           # 文件对象(磁盘对象)
    start_block_id: int,    # 起始块ID
    *,
    block_count: int = 1,   # 占用的块数
) -> Any:

    if block_count <= 0:
        raise ValueError("block_count must be positive")

    data = b"".join(
        read_block(fp, start_block_id + index) for index in range(block_count)
    )
    return unpack_object(data)

# ObjectDisk 类是 Disk 的子类，提供了对象读写的便利方法
class ObjectDisk(Disk):

    def write_object(self, start_block_id: int, obj: Any, *, block_count: int = 1) -> None:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        write_object(self.fp, start_block_id, obj, block_count=block_count)

    def read_object(self, start_block_id: int, *, block_count: int = 1) -> Any:
        if self.fp is None:
            raise DiskIOError("disk is not open")
        return read_object(self.fp, start_block_id, block_count=block_count)
