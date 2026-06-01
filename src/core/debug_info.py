"""
    Read-only snapshots used by the terminal file-system monitor.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from core.format_disk import read_super_block
from core.file_system import FileSystem, FileSystemError
from dataStruct import DirBlock, GroupList, Inode
from head import (
    BLOCK_NUM,
    BLOCK_SIZE,
    DATA_BLOCK_NUM,
    DATA_BLOCK_START_ID,
    INODE_BLOCK_START_ID,
    ROOT_ID,
)
from storage.disk import open_disk
from storage.inode_io import read_inode
from storage.object_io import read_object


@dataclass(frozen=True)
class InodeDebugEntry:
    inode_id: int
    used: bool
    kind: str
    size: int = 0


@dataclass(frozen=True)
class InodeBitmapDebugInfo:
    total: int
    used: int
    free: int
    entries: list[InodeDebugEntry]


@dataclass(frozen=True)
class FreeGroupEntry:
    source: str
    block_id: int | None
    stack: list[int]
    next_group_block: int | None

    @property
    def count(self) -> int:
        return len(self.stack)


@dataclass(frozen=True)
class FreeGroupsDebugInfo:
    current_stack: list[int]
    next_allocated: int | None
    next_group_pointer: int | None
    groups: list[FreeGroupEntry]
    free_block_ids: set[int]
    group_leader_ids: set[int]
    inconsistencies: list[str]


@dataclass(frozen=True)
class BlockDebugEntry:
    block_id: int
    role: str
    data_block_id: int | None = None
    owner_inode: int | None = None
    owner_path: str | None = None


@dataclass(frozen=True)
class BlockMapDebugInfo:
    total_blocks: int
    data_blocks: int
    free_data_blocks: int
    used_data_blocks: int
    entries: list[BlockDebugEntry]
    inconsistencies: list[str]


@dataclass(frozen=True)
class FileIndexDebugInfo:
    path: str
    inode_id: int
    size: int
    direct_blocks: list[int]
    single_indirect_block: int | None
    single_indirect_data_blocks: list[int]


@dataclass(frozen=True)
class MemoryInodeDebugEntry:
    bucket_id: int
    inode_id: int
    kind: str
    size: int
    ref_count: int
    dirty: bool
    reader_holders: list[int]
    writer_holder: int | None


@dataclass(frozen=True)
class MemoryInodeDebugInfo:
    bucket_count: int
    entry_limit: int
    entries: list[MemoryInodeDebugEntry]


class FileSystemInspector:
    """Collect monitor data without mutating the mounted file system."""

    def __init__(self, fs: FileSystem):
        self.fs = fs

    def inode_bitmap(self) -> InodeBitmapDebugInfo:
        with open_disk(self.fs.path) as fp:
            super_block = read_super_block(fp)
            entries = self._inode_entries(fp, super_block)

        used = sum(entry.used for entry in entries)
        return InodeBitmapDebugInfo(
            total=super_block.inode_cnt,
            used=used,
            free=super_block.inode_cnt - used,
            entries=entries,
        )

    def free_groups(self) -> FreeGroupsDebugInfo:
        with open_disk(self.fs.path) as fp:
            super_block = read_super_block(fp)
            return self._free_groups(fp, super_block)

    def block_map(self) -> BlockMapDebugInfo:
        with open_disk(self.fs.path) as fp:
            super_block = read_super_block(fp)
            groups = self._free_groups(fp, super_block)
            used_inodes = self._used_inodes(fp, super_block)
            owner_paths = self._inode_paths(fp, used_inodes)

            roles = {
                block_id: BlockDebugEntry(block_id, "INODE_AREA")
                for block_id in range(INODE_BLOCK_START_ID, DATA_BLOCK_START_ID)
            }
            roles[0] = BlockDebugEntry(0, "SUPER")
            roles[DATA_BLOCK_START_ID] = BlockDebugEntry(
                DATA_BLOCK_START_ID,
                "RESERVED",
                data_block_id=0,
            )

            for data_block_id in groups.free_block_ids:
                self._set_data_role(roles, data_block_id, "FREE")
            for data_block_id in groups.group_leader_ids:
                self._set_data_role(roles, data_block_id, "GROUP_LINK")

            inconsistencies = list(groups.inconsistencies)
            for inode in used_inodes.values():
                owner_path = owner_paths.get(inode.inode_id)
                if inode.is_dir:
                    for data_block_id in inode.direct_blocks:
                        self._claim_data_role(
                            roles,
                            inconsistencies,
                            data_block_id,
                            "DIR_DATA",
                            inode.inode_id,
                            owner_path,
                        )
                    continue

                data_block_ids = self._file_data_block_ids(fp, inode)
                for data_block_id in data_block_ids:
                    self._claim_data_role(
                        roles,
                        inconsistencies,
                        data_block_id,
                        "FILE_DATA",
                        inode.inode_id,
                        owner_path,
                    )
                if inode.indirect_block is not None:
                    self._claim_data_role(
                        roles,
                        inconsistencies,
                        inode.indirect_block,
                        "INDEX_BLOCK",
                        inode.inode_id,
                        owner_path,
                    )

            entries = []
            for block_id in range(BLOCK_NUM):
                entry = roles.get(block_id)
                if entry is None:
                    data_block_id = block_id - DATA_BLOCK_START_ID
                    entry = BlockDebugEntry(
                        block_id,
                        "UNKNOWN",
                        data_block_id=data_block_id,
                    )
                entries.append(entry)

        free_count = len(groups.free_block_ids)
        return BlockMapDebugInfo(
            total_blocks=BLOCK_NUM,
            data_blocks=DATA_BLOCK_NUM,
            free_data_blocks=free_count,
            used_data_blocks=DATA_BLOCK_NUM - 1 - free_count,
            entries=entries,
            inconsistencies=inconsistencies,
        )

    def file_index(self, path: str) -> FileIndexDebugInfo:
        inode, _dir_block = self.fs._resolve_path(path)
        if inode.is_dir:
            raise FileSystemError(f"is a directory: {path}")

        with open_disk(self.fs.path) as fp:
            indirect_ids = self._indirect_data_block_ids(fp, inode)

        return FileIndexDebugInfo(
            path=self.fs._normalize_path(path),
            inode_id=inode.inode_id,
            size=inode.size,
            direct_blocks=list(inode.direct_blocks),
            single_indirect_block=inode.indirect_block,
            single_indirect_data_blocks=indirect_ids,
        )

    def memory_inodes(self) -> MemoryInodeDebugInfo:
        cache = self.fs.inode_cache
        entries = [
            MemoryInodeDebugEntry(
                bucket_id=cache.bucket_index(memory_inode.inode_id),
                inode_id=memory_inode.inode_id,
                kind="DIR" if memory_inode.inode.is_dir else "FILE",
                size=memory_inode.inode.size,
                ref_count=memory_inode.ref_count,
                dirty=memory_inode.dirty,
                reader_holders=sorted(memory_inode.reader_holders),
                writer_holder=memory_inode.writer_holder,
            )
            for memory_inode in cache.entries.values()
        ]
        entries.sort(key=lambda entry: (entry.bucket_id, entry.inode_id))
        return MemoryInodeDebugInfo(
            bucket_count=cache.hash_bucket_count,
            entry_limit=cache.max_entries,
            entries=entries,
        )

    def _inode_entries(self, fp, super_block) -> list[InodeDebugEntry]:
        entries = []
        for inode_id in range(super_block.inode_cnt):
            used = super_block.free_inode_bitmap._get_bit(inode_id) == 1
            if not used:
                entries.append(InodeDebugEntry(inode_id, False, "FREE"))
                continue
            inode = read_inode(fp, inode_id)
            entries.append(
                InodeDebugEntry(
                    inode_id=inode_id,
                    used=True,
                    kind="DIR" if inode.is_dir else "FILE",
                    size=inode.size,
                )
            )
        return entries

    def _free_groups(self, fp, super_block) -> FreeGroupsDebugInfo:
        current = super_block.block_group_link
        groups = []
        free_block_ids: set[int] = set()
        group_leader_ids: set[int] = set()
        inconsistencies = []
        seen_leaders = set()
        source = "SuperBlock"
        source_block_id = None

        while True:
            if not isinstance(current, GroupList):
                inconsistencies.append(f"{source} does not contain a GroupList")
                break
            if not current.stack:
                inconsistencies.append(f"{source} contains an empty stack")
                break

            next_group = current.stack[0] or None
            groups.append(
                FreeGroupEntry(
                    source=source,
                    block_id=source_block_id,
                    stack=list(current.stack),
                    next_group_block=next_group,
                )
            )

            for block_id in current.stack:
                if block_id == 0:
                    continue
                if block_id <= 0 or block_id >= DATA_BLOCK_NUM:
                    inconsistencies.append(f"invalid free data block id: {block_id}")
                    continue
                free_block_ids.add(block_id)

            if next_group is None:
                break
            if next_group in seen_leaders:
                inconsistencies.append(f"cycle detected at group leader block {next_group}")
                break

            seen_leaders.add(next_group)
            group_leader_ids.add(next_group)
            fp.seek((DATA_BLOCK_START_ID + next_group) * BLOCK_SIZE)
            try:
                current = GroupList.from_bytes(fp.read(BLOCK_SIZE))
            except Exception as exc:
                inconsistencies.append(
                    f"cannot read group leader block {next_group}: {exc}"
                )
                break
            source = f"Block {next_group}"
            source_block_id = next_group

        stack = list(super_block.block_group_link.stack)
        next_allocated = stack[-1] if stack and stack[-1] != 0 else None
        next_pointer = stack[0] if stack and stack[0] != 0 else None
        return FreeGroupsDebugInfo(
            current_stack=stack,
            next_allocated=next_allocated,
            next_group_pointer=next_pointer,
            groups=groups,
            free_block_ids=free_block_ids,
            group_leader_ids=group_leader_ids,
            inconsistencies=inconsistencies,
        )

    def _used_inodes(self, fp, super_block) -> dict[int, Inode]:
        result = {}
        for inode_id in range(super_block.inode_cnt):
            if super_block.free_inode_bitmap._get_bit(inode_id) == 1:
                result[inode_id] = read_inode(fp, inode_id)
        return result

    def _inode_paths(self, fp, used_inodes: dict[int, Inode]) -> dict[int, str]:
        paths = {ROOT_ID: "/"}
        visited = set()

        def walk(inode_id: int, path: str) -> None:
            if inode_id in visited:
                return
            visited.add(inode_id)
            inode = used_inodes.get(inode_id)
            if inode is None or not inode.is_dir or not inode.direct_blocks:
                return
            try:
                dir_block = read_object(fp, DATA_BLOCK_START_ID + inode.direct_blocks[0])
            except Exception:
                return
            if not isinstance(dir_block, DirBlock):
                return

            for name, child_id in dir_block.son_files.items():
                paths.setdefault(child_id, posixpath.join(path, name))
            for name, child_id in dir_block.son_dirs.items():
                child_path = posixpath.join(path, name)
                paths.setdefault(child_id, child_path)
                walk(child_id, child_path)

        walk(ROOT_ID, "/")
        return paths

    def _file_data_block_ids(self, fp, inode: Inode) -> list[int]:
        return list(inode.direct_blocks) + self._indirect_data_block_ids(fp, inode)

    def _indirect_data_block_ids(self, fp, inode: Inode) -> list[int]:
        if inode.indirect_block is None:
            return []
        result = read_object(fp, DATA_BLOCK_START_ID + inode.indirect_block)
        if not isinstance(result, list):
            raise FileSystemError(f"inode {inode.inode_id} has an invalid indirect block")
        return result

    def _set_data_role(
        self,
        roles: dict[int, BlockDebugEntry],
        data_block_id: int,
        role: str,
    ) -> None:
        block_id = DATA_BLOCK_START_ID + data_block_id
        roles[block_id] = BlockDebugEntry(
            block_id,
            role,
            data_block_id=data_block_id,
        )

    def _claim_data_role(
        self,
        roles: dict[int, BlockDebugEntry],
        inconsistencies: list[str],
        data_block_id: int,
        role: str,
        owner_inode: int,
        owner_path: str | None,
    ) -> None:
        if data_block_id <= 0 or data_block_id >= DATA_BLOCK_NUM:
            inconsistencies.append(
                f"inode {owner_inode} references invalid data block {data_block_id}"
            )
            return

        block_id = DATA_BLOCK_START_ID + data_block_id
        old_entry = roles.get(block_id)
        if old_entry is not None:
            inconsistencies.append(
                f"data block {data_block_id} is both {old_entry.role} and {role}"
            )
            role = "UNKNOWN"
        roles[block_id] = BlockDebugEntry(
            block_id,
            role,
            data_block_id=data_block_id,
            owner_inode=owner_inode,
            owner_path=owner_path,
        )
