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


class InodeCacheError(Exception):
    """内存 inode 表操作错误。"""


class InodeBusyError(InodeCacheError):
    """inode 仍在使用中，当前操作不能继续。"""


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

    @property
    def inode_id(self) -> int:
        return self.inode.inode_id

    @property
    def is_locked(self) -> bool:
        return bool(self.reader_holders) or self.writer_holder is not None


class InodeCache:
    """通过 Hash 链管理运行期间的内存 inode、引用计数和访问锁。"""

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

    def bucket_index(self, inode_id: int) -> int:
        return inode_id % self.hash_bucket_count

    def find(self, inode_id: int) -> MemoryInode | None:
        with self._lock:
            current = self.buckets[self.bucket_index(inode_id)]
            while current is not None:
                if current.inode_id == inode_id:
                    return current
                current = current.hash_next
            return None

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

    def mark_dirty(self, memory_inode: MemoryInode) -> None:
        with self._lock:
            self._ensure_tracked(memory_inode)
            memory_inode.dirty = True

    def acquire_read(self, memory_inode: MemoryInode, holder_id: int) -> None:
        """获取共享读锁。存在写锁时拒绝。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            if memory_inode.writer_holder is not None:
                raise InodeBusyError(
                    f"inode {memory_inode.inode_id} is locked for writing"
                )
            memory_inode.reader_holders.add(holder_id)

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

    def release_access(self, memory_inode: MemoryInode, holder_id: int) -> None:
        """释放 holder 持有的读锁或写锁。"""

        with self._lock:
            self._ensure_tracked(memory_inode)
            memory_inode.reader_holders.discard(holder_id)
            if memory_inode.writer_holder == holder_id:
                memory_inode.writer_holder = None

    def ensure_unused(self, inode_id: int) -> None:
        """删除 inode 前确认它没有活动引用或访问锁。"""

        with self._lock:
            memory_inode = self.find(inode_id)
            if memory_inode is None:
                return
            if memory_inode.ref_count > 0 or memory_inode.is_locked:
                raise InodeBusyError(f"inode {inode_id} is still in use")

    def discard(self, inode_id: int) -> None:
        """从缓存移除已删除 inode；仍被使用时拒绝删除。"""

        with self._lock:
            memory_inode = self.find(inode_id)
            if memory_inode is None:
                return
            if memory_inode.ref_count > 0 or memory_inode.is_locked:
                raise InodeBusyError(f"inode {inode_id} is still in use")
            self._unlink(memory_inode)

    def flush(self) -> None:
        with self._lock:
            for memory_inode in list(self.entries.values()):
                if memory_inode.dirty:
                    self._write_back(memory_inode)

    @contextmanager
    def hold(self, inode_id: int) -> Iterator[MemoryInode]:
        memory_inode = self.iget(inode_id)
        try:
            yield memory_inode
        finally:
            self.iput(memory_inode)

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

    def _ensure_tracked(self, memory_inode: MemoryInode) -> None:
        if self.entries.get(memory_inode.inode_id) is not memory_inode:
            raise InodeCacheError(f"inode {memory_inode.inode_id} is not cached")

    def _insert(self, memory_inode: MemoryInode) -> None:
        bucket_id = self.bucket_index(memory_inode.inode_id)
        head = self.buckets[bucket_id]
        memory_inode.hash_next = head
        if head is not None:
            head.hash_prev = memory_inode
        self.buckets[bucket_id] = memory_inode
        self.entries[memory_inode.inode_id] = memory_inode

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

    def _write_back(self, memory_inode: MemoryInode) -> None:
        with open_disk(self.path) as fp:
            write_inode(fp, memory_inode.inode_id, memory_inode.inode)
        memory_inode.dirty = False
