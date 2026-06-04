from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Iterator

from dataStruct import Inode
from head import INODE_HASH_BUCKETS, MEMORY_INODE_LIMIT
from storage.disk import open_disk
from storage.inode_io import read_inode, write_inode


# 定义内存 inode 表相关操作的基础异常。
class InodeCacheError(Exception):
    """内存 inode 表操作错误。"""


# 定义 inode 被引用或锁定时抛出的异常。
class InodeBusyError(InodeCacheError):
    """inode 仍在使用中，当前操作不能继续。"""


# 保存磁盘 inode 在内存中的副本及运行时状态。
@dataclass(eq=False)
class MemoryInode:
    """磁盘 inode 的内存副本及其运行时状态，不会被序列化。"""

    inode: Inode
    ref_count: int = 0
    dirty: bool = False
    hash_prev: MemoryInode | None = None
    hash_next: MemoryInode | None = None
    reader_holders: set[int] = field(default_factory=set)
    writer_holder: int | None = None

    # 返回当前内存 inode 对应的磁盘 inode 编号。
    @property
    def inode_id(self) -> int:
        return self.inode.inode_id

    # 判断当前 inode 是否被任意读者或写者锁定。
    @property
    def is_locked(self) -> bool:
        return bool(self.reader_holders) or self.writer_holder is not None


# 管理内存 inode 缓存、哈希链、引用计数和访问锁。
class InodeCache:
    """通过 Hash 链管理运行期间的内存 inode、引用计数和访问锁。"""

    # 初始化 inode 缓存的磁盘路径、哈希桶和容量限制。
    def __init__(
        self,
        path: str | Path,
        *,
        hash_bucket_count: int = INODE_HASH_BUCKETS,
        max_entries: int = MEMORY_INODE_LIMIT,
    ):
        if hash_bucket_count <= 0:
            raise ValueError("hash_bucket_count must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")

        self.path = Path(path)
        self.hash_bucket_count = hash_bucket_count
        self.max_entries = max_entries
        self.buckets: list[MemoryInode | None] = [None] * hash_bucket_count
        self.entries: dict[int, MemoryInode] = {}
        self._lock = RLock()

    # 根据 inode 编号计算其所在的哈希桶下标。
    def bucket_index(self, inode_id: int) -> int:
        return inode_id % self.hash_bucket_count

    # 在哈希链中查找指定编号的内存 inode。
    def find(self, inode_id: int) -> MemoryInode | None:
        with self._lock:
            current = self.buckets[self.bucket_index(inode_id)]
            while current is not None:
                if current.inode_id == inode_id:
                    return current
                current = current.hash_next
            return None

    # 获取 inode 的内存副本，未缓存时从磁盘读取并加入缓存。
    def iget(self, inode_id: int) -> MemoryInode:
        """获取 inode 的共享内存副本，并增加一次引用。"""

        with self._lock:
            memory_inode = self.find(inode_id)
            if memory_inode is None:
                self._ensure_capacity()
                with open_disk(self.path) as fp:
                    inode = read_inode(fp, inode_id)
                memory_inode = MemoryInode(inode=inode)
                self._insert(memory_inode)

            memory_inode.ref_count += 1
            return memory_inode

    # 释放一次 inode 引用，并在最后一个引用释放时写回脏数据。
    def iput(self, memory_inode: MemoryInode) -> None:
        """释放一次引用；最后一个引用释放时写回脏 inode。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            if memory_inode.ref_count <= 0:
                raise InodeCacheError(
                    f"inode {memory_inode.inode_id} has no active reference"
                )

            memory_inode.ref_count -= 1
            if memory_inode.ref_count == 0 and memory_inode.dirty:
                self._write_back(memory_inode)

    # 将指定内存 inode 标记为需要写回磁盘。
    def mark_dirty(self, memory_inode: MemoryInode) -> None:
        with self._lock:
            self._ensure_tracked(memory_inode)
            memory_inode.dirty = True

    # 为 holder 获取共享读锁，存在写锁时拒绝。
    def acquire_read(self, memory_inode: MemoryInode, holder_id: int) -> None:
        """获取共享读锁。存在写锁时拒绝。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            if memory_inode.writer_holder is not None:
                raise InodeBusyError(
                    f"inode {memory_inode.inode_id} is locked for writing"
                )
            memory_inode.reader_holders.add(holder_id)

    # 为 holder 获取独占写锁，存在任意访问锁时拒绝。
    def acquire_write(self, memory_inode: MemoryInode, holder_id: int) -> None:
        """获取独占写锁。存在任何其他访问锁时拒绝。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            if memory_inode.writer_holder is not None:
                raise InodeBusyError(
                    f"inode {memory_inode.inode_id} is already locked for writing"
                )
            if memory_inode.reader_holders:
                raise InodeBusyError(
                    f"inode {memory_inode.inode_id} is locked for reading"
                )
            memory_inode.writer_holder = holder_id

    # 释放 holder 在指定 inode 上持有的读锁或写锁。
    def release_access(self, memory_inode: MemoryInode, holder_id: int) -> None:
        """释放 holder 持有的读锁或写锁。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            memory_inode.reader_holders.discard(holder_id)
            if memory_inode.writer_holder == holder_id:
                memory_inode.writer_holder = None

    # 确认指定 inode 没有活动引用或访问锁。
    def ensure_unused(self, inode_id: int) -> None:
        """删除 inode 前确认它没有活动引用或访问锁。"""

        with self._lock:
            memory_inode = self.find(inode_id)
            if memory_inode is None:
                return
            if memory_inode.ref_count > 0 or memory_inode.is_locked:
                raise InodeBusyError(f"inode {inode_id} is still in use")

    # 从缓存中移除未被使用的 inode。
    def discard(self, inode_id: int) -> None:
        """从缓存移除已删除 inode；仍被使用时拒绝删除。"""

        with self._lock:
            memory_inode = self.find(inode_id)
            if memory_inode is None:
                return
            if memory_inode.ref_count > 0 or memory_inode.is_locked:
                raise InodeBusyError(f"inode {inode_id} is still in use")
            self._unlink(memory_inode)

    # 将缓存中所有脏 inode 写回磁盘。
    def flush(self) -> None:
        with self._lock:
            for memory_inode in list(self.entries.values()):
                if memory_inode.dirty:
                    self._write_back(memory_inode)

    # 以上下文管理器形式持有 inode 引用，退出时自动释放。
    @contextmanager
    def hold(self, inode_id: int) -> Iterator[MemoryInode]:
        memory_inode = self.iget(inode_id)
        try:
            yield memory_inode
        finally:
            self.iput(memory_inode)

    # 确保缓存仍有容量，必要时淘汰未使用的 inode。
    def _ensure_capacity(self) -> None:
        if len(self.entries) < self.max_entries:
            return

        for memory_inode in list(self.entries.values()):
            if memory_inode.ref_count == 0 and not memory_inode.is_locked:
                if memory_inode.dirty:
                    self._write_back(memory_inode)
                self._unlink(memory_inode)
                return

        raise InodeCacheError("memory inode table is full")

    # 确认传入的内存 inode 仍由当前缓存管理。
    def _ensure_tracked(self, memory_inode: MemoryInode) -> None:
        if self.entries.get(memory_inode.inode_id) is not memory_inode:
            raise InodeCacheError(f"inode {memory_inode.inode_id} is not cached")

    # 将新的内存 inode 插入对应哈希桶的链表头部。
    def _insert(self, memory_inode: MemoryInode) -> None:
        bucket_id = self.bucket_index(memory_inode.inode_id)
        head = self.buckets[bucket_id]
        memory_inode.hash_next = head
        if head is not None:
            head.hash_prev = memory_inode
        self.buckets[bucket_id] = memory_inode
        self.entries[memory_inode.inode_id] = memory_inode

    # 将内存 inode 从哈希链和缓存索引中移除。
    def _unlink(self, memory_inode: MemoryInode) -> None:
        bucket_id = self.bucket_index(memory_inode.inode_id)
        if memory_inode.hash_prev is None:
            self.buckets[bucket_id] = memory_inode.hash_next
        else:
            memory_inode.hash_prev.hash_next = memory_inode.hash_next
        if memory_inode.hash_next is not None:
            memory_inode.hash_next.hash_prev = memory_inode.hash_prev

        self.entries.pop(memory_inode.inode_id, None)
        memory_inode.hash_prev = None
        memory_inode.hash_next = None

    # 将内存 inode 的数据写回磁盘并清除脏标记。
    def _write_back(self, memory_inode: MemoryInode) -> None:
        with open_disk(self.path) as fp:
            write_inode(fp, memory_inode.inode_id, memory_inode.inode)
        memory_inode.dirty = False
