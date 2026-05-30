"""
    文件系统核心 API, 提供 ls、mkdir、touch、cd 等用户操作，底层通过磁盘镜像实现持久化。
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Iterable

from head import *
from storage.disk import open_disk, read_block, write_block
from core.format_disk import format_disk, read_super_block, write_super_block
from storage.inode_io import clear_inode_slot, read_inode, write_inode
from core.mount import MountedFileSystem, mount
from dataStruct.open_file import OpenFile, parse_open_mode
from storage.object_io import ObjectIOError, pack_object, read_object, write_object

from dataStruct.data import DirBlock, SuperBlock  
from dataStruct import Inode  

# 间接索引块 安全存储的最大数据块数量
MAX_INDIRECT_BLOCK_IDS = BLOCK_SIZE // 4 - 2

# 文件错误定义
class FileSystemError(Exception):
    """文件系统错误"""

# 文件系统核心 API，提供 ls、mkdir、touch、cd 等用户操作，底层通过磁盘镜像实现持久化。
class FileSystem:

    def __init__(self, mounted: MountedFileSystem):
        self.path = mounted.path
        self.super_block = mounted.super_block
        self.cwd_inode = mounted.root_inode
        self.cwd_dir = mounted.root_dir
        self.cwd_path = BASE_NAME
        # 打开文件表，key 是文件描述符，value 是 OpenFile 对象
        self.open_file_table: dict[int, OpenFile] = {}
        self.next_fd = 3

    # format_and_mount 格式化磁盘并挂载
    @classmethod
    def format_and_mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        format_disk(path)
        return cls(mount(path))

    # mount 从磁盘镜像加载文件系统元数据并挂载
    @classmethod
    def mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        return cls(mount(path))

    # 用户操作接口：ls 返回目录下的 (name, type) 列表
    def ls(self, path: str = ".") -> list[tuple[str, int]]:

        _inode, dir_block = self._resolve_dir(path)
        return dir_block.file_name_and_types()
    
    # mkdir 创建目录，返回新目录的 inode id
    def mkdir(self, path: str) -> int:
        
        # 解析路径，获取父目录的 inode 和 DirBlock，以及新建目录的名字
        parent_inode, parent_dir, name = self._resolve_parent(path)
        if not name:
            raise FileSystemError("directory name cannot be empty")
        self._ensure_name_available(parent_dir, name)

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode_id = self._alloc_inode_id()
            data_block_id = self.super_block.get_data_block_id(fp)

            inode = Inode(inode_id, ROOT_ID)
            inode.is_dir = True
            inode.direct_blocks.append(data_block_id)
            inode.direct_blocks_size = 1

            dir_block = DirBlock(name, parent_inode.inode_id)
            dir_block.inode_id = inode_id

            parent_dir.add_new_dir(name, inode_id)

            write_inode(fp, inode_id, inode)
            write_object(fp, DATA_BLOCK_START_ID + data_block_id, dir_block)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)
        return inode_id

    # touch 创建文件，返回新文件的 inode id
    def touch(self, path: str) -> int:

        parent_inode, parent_dir, name = self._resolve_parent(path)
        if not name:
            raise FileSystemError("file name cannot be empty")
        self._ensure_name_available(parent_dir, name)

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode_id = self._alloc_inode_id()

            inode = Inode(inode_id, ROOT_ID)
            inode.is_dir = False

            parent_dir.add_new_file(name, inode_id)

            write_inode(fp, inode_id, inode)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)
        return inode_id

    # cd 切换当前目录，返回新的绝对路径
    def cd(self, path: str) -> str:

        inode, dir_block = self._resolve_dir(path)
        self.cwd_inode = inode
        self.cwd_dir = dir_block
        self.cwd_path = self._normalize_path(path)
        return self.cwd_path

    # pwd 返回当前目录的绝对路径
    def pwd(self) -> str:
        return self.cwd_path

    # open 打开文件，返回文件描述符
    def open(self, path: str, mode: str = "r") -> int:

        # 解析打开模式，获取读写权限、是否创建新文件、是否截断文件、初始偏移量等信息
        try:
            readable, writable, create, truncate, offset = parse_open_mode(mode)
        except ValueError as exc:
            raise FileSystemError(str(exc)) from exc

        # 解析路径，获取文件的 inode 和所在目录的 DirBlock
        try:
            inode, _dir_block = self._resolve_path(path)
        except FileSystemError:
            if not create:
                raise
            self.touch(path)
            inode, _dir_block = self._resolve_path(path)

        # 如果路径对应的是一个目录，则不能以文件的方式打开
        if inode.is_dir:
            raise FileSystemError(f"is a directory: {path}")

        # 如果打开模式要求截断文件，则将文件内容清空
        if truncate:
            self._write_file_inode(inode.inode_id, b"")
            inode = self._read_inode(inode.inode_id)

        # 分配一个新的文件描述符，并在打开文件表
        # 记录该文件的 inode id、路径、打开模式、当前偏移量等信息
        fd = self.next_fd
        self.next_fd += 1
        if offset < 0:
            offset = inode.size

        self.open_file_table[fd] = OpenFile(
            fd=fd,
            inode_id=inode.inode_id,
            path=self._normalize_path(path),
            mode=mode,
            offset=offset,
            readable=readable,
            writable=writable,
        )
        return fd

    # close 关闭文件，释放文件描述符
    def close(self, fd: int) -> None:
        self._get_open_file(fd)
        del self.open_file_table[fd]

    # read 从文件描述符对应的文件中读取数据，返回 bytes
    def read(self, fd: int, size: int = -1) -> bytes:
        open_file = self._get_open_file(fd)
        if not open_file.readable:
            raise FileSystemError(f"file descriptor is not readable: {fd}")
        if size is None:
            size = -1
        if size < -1:
            raise FileSystemError("read size cannot be less than -1")

        data = self._read_file_inode(open_file.inode_id)
        start = min(open_file.offset, len(data))
        end = len(data) if size == -1 else min(start + size, len(data))
        chunk = data[start:end]
        open_file.offset = end
        return chunk
    
    # write 向文件描述符对应的文件中写入数据，返回写入的字节数
    def write(self, fd: int, data: bytes | str) -> int:
        open_file = self._get_open_file(fd)
        if not open_file.writable:
            raise FileSystemError(f"file descriptor is not writable: {fd}")
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes or str")

        old_data = self._read_file_inode(open_file.inode_id)
        offset = open_file.offset
        if offset > len(old_data):
            old_data = old_data + b"\x00" * (offset - len(old_data))

        new_data = old_data[:offset] + bytes(data) + old_data[offset + len(data):]
        self._write_file_inode(open_file.inode_id, new_data)
        open_file.offset = offset + len(data)
        return len(data)

    # seek 调整文件描述符对应的文件的当前偏移量，返回新的偏移量
    def seek(self, fd: int, offset: int, whence: int = 0) -> int:
        open_file = self._get_open_file(fd)
        inode = self._read_inode(open_file.inode_id)

        if whence == 0:
            new_offset = offset
        elif whence == 1:
            new_offset = open_file.offset + offset
        elif whence == 2:
            new_offset = inode.size + offset
        else:
            raise FileSystemError(f"invalid whence: {whence}")

        if new_offset < 0:
            raise FileSystemError("file offset cannot be negative")
        open_file.offset = new_offset
        return new_offset

    # read_file 从指定路径读取文件内容，返回 bytes
    def read_file(self, path: str) -> bytes:
        fd = self.open(path, "r")
        try:
            return self.read(fd)
        finally:
            self.close(fd)

    # write_file 向指定路径写入数据，返回写入的字节数。
    # 如果 append=True，则在文件末尾追加数据；否则覆盖原有内容。
    def write_file(self, path: str, data: bytes | str, *, append: bool = False) -> int:
        fd = self.open(path, "a" if append else "w")
        try:
            return self.write(fd, data)
        finally:
            self.close(fd)

    # remove 删除指定路径的文件
    def remove(self, path: str) -> None:
        parent_inode, parent_dir, name = self._resolve_parent(path)
        if name in parent_dir.son_dirs:
            raise FileSystemError(f"is a directory: {path}")
        inode_id = parent_dir.son_files.get(name)
        if inode_id is None:
            raise FileSystemError(f"file not found: {path}")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode = read_inode(fp, inode_id)
            self._free_inode_data_blocks(fp, inode)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)
            parent_dir.remove(name, FILE_TYPE)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)

    # rmdir 删除指定路径的目录，目录必须为空
    def rmdir(self, path: str, *, recursive: bool = False) -> None:
        normalized = self._normalize_path(path)
        if normalized == BASE_NAME:
            raise FileSystemError("cannot remove root directory")

        parent_inode, parent_dir, name = self._resolve_parent(path)
        inode_id = parent_dir.son_dirs.get(name)
        if inode_id is None:
            if name in parent_dir.son_files:
                raise FileSystemError(f"not a directory: {path}")
            raise FileSystemError(f"directory not found: {path}")

        inode, dir_block = self._resolve_dir(normalized)
        if not recursive and (dir_block.son_files or dir_block.son_dirs):
            raise FileSystemError(f"directory is not empty: {path}")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode = read_inode(fp, inode.inode_id)
            if recursive:
                self._remove_dir_children(fp, dir_block)
            self._free_inode_data_blocks(fp, inode)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)
            parent_dir.remove(name, DIR_TYPE)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)


    # 以下是一些内部辅助方法：
    # 根据文件描述符获取对应的 OpenFile 对象
    def _get_open_file(self, fd: int) -> OpenFile:
        try:
            return self.open_file_table[fd]
        except KeyError as exc:
            raise FileSystemError(f"invalid file descriptor: {fd}") from exc

    # 从磁盘读取指定文件 inode 的内容，返回 bytes
    def _read_file_inode(self, inode_id: int) -> bytes:
        inode = self._read_inode(inode_id)
        if inode.is_dir:
            raise FileSystemError(f"inode {inode_id} is a directory")

        content = bytearray()
        with open_disk(self.path) as fp:
            for data_block_id in self._file_data_block_ids(fp, inode):
                block = read_block(fp, DATA_BLOCK_START_ID + data_block_id)
                content.extend(block)

        return bytes(content[: inode.size])

    # 将数据写入指定文件 inode，更新 inode 的直接索引和间接索引，并写回磁盘
    def _write_file_inode(self, inode_id: int, data: bytes | bytearray) -> None:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes or bytearray")
        data = bytes(data)
        needed_blocks = self._required_block_count(len(data))

        if needed_blocks > self._max_file_block_count():
            max_size = self._max_file_block_count() * BLOCK_SIZE
            raise FileSystemError(f"file is too large: max {max_size} bytes")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode = read_inode(fp, inode_id)
            if inode.is_dir:
                raise FileSystemError(f"inode {inode_id} is a directory")

            data_block_ids = self._file_data_block_ids(fp, inode)

            while len(data_block_ids) < needed_blocks:
                data_block_ids.append(self.super_block.get_data_block_id(fp))

            while len(data_block_ids) > needed_blocks:
                released_block_id = data_block_ids.pop()
                self.super_block.free_up_data_block(fp, released_block_id)
            self._set_file_data_block_ids(fp, inode, data_block_ids)

            for index, data_block_id in enumerate(data_block_ids):
                start = index * BLOCK_SIZE
                end = start + BLOCK_SIZE
                write_block(fp, DATA_BLOCK_START_ID + data_block_id, data[start:end])

            inode.size = len(data)
            inode.direct_blocks_size = len(inode.direct_blocks)
            write_inode(fp, inode.inode_id, inode)
            write_super_block(fp, self.super_block)

    # _alloc_inode_id 从超级块的 inode 位图中分配一个新的 inode id
    def _alloc_inode_id(self) -> int:
        for inode_id in range(self.super_block.inode_cnt):
            if self.super_block.free_inode_bitmap._get_bit(inode_id) == 0:
                self.super_block.free_inode_bitmap._set_bit(inode_id, 1)
                self.super_block.free_inode_cnt -= 1
                return inode_id
        raise FileSystemError("no free inode available")

    # _free_inode_id 释放一个 inode id
    # 将其在超级块的 inode 位图中标记为可用，并增加空闲 inode 计数
    def _free_inode_id(self, inode_id: int) -> None:
        if self.super_block.free_inode_bitmap._get_bit(inode_id) == 0:
            raise FileSystemError(f"inode is already free: {inode_id}")
        self.super_block.free_inode_bitmap._set_bit(inode_id, 0)
        self.super_block.free_inode_cnt += 1
    
    # _free_inode_data_blocks 释放 inode 占用的数据块，并清空 inode 的直接索引列表和大小信息
    # 间接索引的释放暂不支持，因为目前还没有实现间接索引
    def _free_inode_data_blocks(self, fp, inode: Inode) -> None:
        for data_block_id in self._file_data_block_ids(fp, inode):
            self.super_block.free_up_data_block(fp, data_block_id)
        if inode.indirect_block is not None:
            self.super_block.free_up_data_block(fp, inode.indirect_block)
        inode.direct_blocks.clear()
        inode.direct_blocks_size = 0
        inode.indirect_block = None
        inode.size = 0

    # _required_block_count 计算存储指定字节数需要的数据块数量
    def _required_block_count(self, byte_count: int) -> int:
        if byte_count == 0:
            return 0
        # 向上取整计算需要的块数
        return (byte_count + BLOCK_SIZE - 1) // BLOCK_SIZE
    
    # 一个文件最多可以使用的数据块数量，受直接索引和间接索引的限制
    def _max_file_block_count(self) -> int:
        return DIRECT_CNT + MAX_INDIRECT_BLOCK_IDS

    # 直接索引 + 一级间接索引 -> 数据块 id 列表
    def _file_data_block_ids(self, fp, inode: Inode) -> list[int]:
        data_block_ids = list(inode.direct_blocks)
        if inode.indirect_block is None:
            return data_block_ids

        indirect_ids = read_object(fp, DATA_BLOCK_START_ID + inode.indirect_block)
        if not isinstance(indirect_ids, list):
            raise FileSystemError(f"inode {inode.inode_id} has an invalid indirect block")
        return data_block_ids + indirect_ids

    # 根据给定的数据块 id 列表更新 inode 的直接索引和一级间接索引
    def _set_file_data_block_ids(self, fp, inode: Inode, data_block_ids: list[int]) -> None:
        direct_ids = data_block_ids[:DIRECT_CNT]
        indirect_ids = data_block_ids[DIRECT_CNT:]

        inode.direct_blocks = direct_ids
        inode.direct_blocks_size = len(direct_ids)

        if indirect_ids:
            if len(indirect_ids) > MAX_INDIRECT_BLOCK_IDS:
                raise FileSystemError("too many indirect data blocks")
            try:
                pack_object(indirect_ids)
            except ObjectIOError as exc:
                raise FileSystemError("indirect block is too large") from exc
            if inode.indirect_block is None:
                inode.indirect_block = self.super_block.get_data_block_id(fp)
            write_object(fp, DATA_BLOCK_START_ID + inode.indirect_block, indirect_ids)
        elif inode.indirect_block is not None:
            old_indirect_block = inode.indirect_block
            inode.indirect_block = None
            self.super_block.free_up_data_block(fp, old_indirect_block)

    # 递归删除目录下的所有子目录和文件，释放它们占用的 inode 和数据块
    def _remove_dir_children(self, fp, dir_block: DirBlock) -> None:
        
        for _name, inode_id in list(dir_block.son_files.items()):
            inode = read_inode(fp, inode_id)
            self._free_inode_data_blocks(fp, inode)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)

        for _name, inode_id in list(dir_block.son_dirs.items()):
            inode = read_inode(fp, inode_id)
            child_dir = read_object(fp, DATA_BLOCK_START_ID + inode.direct_blocks[0])
            if not isinstance(child_dir, DirBlock):
                raise FileSystemError(f"inode {inode_id} does not point to a DirBlock")
            self._remove_dir_children(fp, child_dir)
            self._free_inode_data_blocks(fp, inode)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)

        dir_block.son_files.clear()
        dir_block.son_dirs.clear()
        dir_block.counts = 0

    # _ensure_name_available 检查目录中是否已经存在同名的文件或目录
    def _ensure_name_available(self, dir_block: DirBlock, name: str) -> None:
        if name in dir_block.son_dirs or name in dir_block.son_files:
            raise FileSystemError(f"name already exists: {name}")

    # _resolve_parent 解析路径，返回父目录的 inode、DirBlock 和新建项的名字
    def _resolve_parent(self, path: str) -> tuple[Inode, DirBlock, str]:
        normalized = self._normalize_path(path)
        # 不可以创建根目录
        if normalized == BASE_NAME:
            raise FileSystemError("cannot create root directory")
        # 分离出父目录路径和新建项名字
        parent_path, name = posixpath.split(normalized)
        if not parent_path:
            parent_path = BASE_NAME
        # 解析父目录路径，获取父目录的 inode 和 DirBlock
        parent_inode, parent_dir = self._resolve_dir(parent_path)
        return parent_inode, parent_dir, name

    # _resolve_dir 解析路径，返回目录的 inode 和 DirBlock
    def _resolve_dir(self, path: str) -> tuple[Inode, DirBlock]:
        # 解析路径并返回对应的 inode 和 dir_block
        inode, dir_block = self._resolve_path(path)
        if not inode.is_dir:
            raise FileSystemError(f"not a directory: {path}")
        return inode, dir_block

    # _resolve_path 解析路径，返回最后一个组件的 inode 和 DirBlock
    def _resolve_path(self, path: str) -> tuple[Inode, DirBlock | None]:
        # 标准化路径，处理 "." 和 ".." 等特殊组件
        normalized = self._normalize_path(path)
        if normalized == BASE_NAME:
            return self._read_root()

        inode, dir_block = self._read_root()

        parts = [part for part in normalized.strip(BASE_NAME).split("/") if part]
        # 逐级解析路径组件，更新 inode 和 dir_block
        for part in parts:
            # 找子目录
            inode_id = dir_block.son_dirs.get(part) if dir_block else None
            # 没有子目录就找文件
            if inode_id is None:
                if dir_block and part in dir_block.son_files:
                    file_inode = self._read_inode(dir_block.son_files[part])
                    return file_inode, None
                raise FileSystemError(f"path not found: {path}")

            inode = self._read_inode(inode_id)
            dir_block = self._read_dir(inode)

        return inode, dir_block

    # _normalize_path 将输入路径转换为绝对路径，处理 "." 和 ".." 等特殊组件
    def _normalize_path(self, path: str) -> str:
        # 当前路径
        if not path or path == ".":
            return self.cwd_path
        # 绝对路径 raw
        if path.startswith(BASE_NAME):
            base = BASE_NAME
            raw = path
        else:
            base = self.cwd_path
            raw = posixpath.join(base, path)

        normalized = posixpath.normpath(raw)
        if normalized == ".":
            return BASE_NAME
        if not normalized.startswith(BASE_NAME):
            normalized = BASE_NAME + normalized
        return normalized

    # _read_root 读取根目录的 inode 和 DirBlock
    def _read_root(self) -> tuple[Inode, DirBlock]:
        inode = self._read_inode(ROOT_ID)
        return inode, self._read_dir(inode)

    # _read_inode 从磁盘读取指定 inode id 的 Inode 对象
    def _read_inode(self, inode_id: int) -> Inode:
        with open_disk(self.path) as fp:
            return read_inode(fp, inode_id)

    # _read_dir 从磁盘读取指定目录 inode 的 DirBlock 对象
    def _read_dir(self, inode: Inode) -> DirBlock:
        if not inode.is_dir:
            raise FileSystemError(f"inode {inode.inode_id} is not a directory")
        if not inode.direct_blocks:
            raise FileSystemError(f"directory inode {inode.inode_id} has no data block")

        with open_disk(self.path) as fp:
            dir_block = read_object(fp, DATA_BLOCK_START_ID + inode.direct_blocks[0])

        if not isinstance(dir_block, DirBlock):
            raise FileSystemError(f"inode {inode.inode_id} does not point to a DirBlock")

        return dir_block

    # _write_dir 将 DirBlock 对象写回磁盘对应目录 inode 的数据块
    def _write_dir(self, fp, inode: Inode, dir_block: DirBlock) -> None:
        if not inode.direct_blocks:
            raise FileSystemError(f"directory inode {inode.inode_id} has no data block")
        write_object(fp, DATA_BLOCK_START_ID + inode.direct_blocks[0], dir_block)

    # _refresh_cwd_if_changed 如果当前目录被修改了（例如在当前目录下创建了新文件），则刷新 cwd_dir 以保持一致
    def _refresh_cwd_if_changed(self, inode_id: int, dir_block: DirBlock) -> None:
        if self.cwd_inode.inode_id == inode_id:
            self.cwd_dir = dir_block
