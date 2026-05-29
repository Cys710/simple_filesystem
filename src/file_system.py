"""
    文件系统核心 API，提供 ls、mkdir、touch、cd 等用户操作，底层通过磁盘镜像实现持久化。
"""

from __future__ import annotations

import posixpath
import sys
from pathlib import Path
from typing import Iterable

from head import *
from disk import open_disk
from format_disk import format_disk, read_super_block, write_super_block
from inode_io import read_inode, write_inode
from init import MountedFileSystem, mount
from object_io import read_object, write_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = SRC_DIR / "data"

for import_path in (str(SRC_DIR), str(DATA_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from data import DirBlock, SuperBlock  
from Inode import Inode  



class FileSystemError(Exception):
    """Base error for FileSystem operations."""


class PathNotFoundError(FileSystemError):
    """Raised when a path component does not exist."""


class NotDirectoryError(FileSystemError):
    """Raised when a directory operation targets a file."""


class AlreadyExistsError(FileSystemError):
    """Raised when creating a name that already exists."""


class NoFreeInodeError(FileSystemError):
    """Raised when no inode is available."""

# 文件系统核心 API，提供 ls、mkdir、touch、cd 等用户操作，底层通过磁盘镜像实现持久化。
class FileSystem:

    def __init__(self, mounted: MountedFileSystem):
        self.path = mounted.path
        self.super_block = mounted.super_block
        self.cwd_inode = mounted.root_inode
        self.cwd_dir = mounted.root_dir
        self.cwd_path = BASE_NAME

    @classmethod
    def format_and_mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        format_disk(path)
        return cls(mount(path))

    @classmethod
    def mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        return cls(mount(path))

    # 用户操作接口：ls 返回目录下的 (name, type) 列表
    def ls(self, path: str = ".") -> list[tuple[str, int]]:

        _inode, dir_block = self._resolve_dir(path)
        return dir_block.file_name_and_types()
    
    # mkdir 创建目录，返回新目录的 inode id
    def mkdir(self, path: str) -> int:

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

    # 以下是一些内部辅助方法：

    # _alloc_inode_id 从超级块的 inode 位图中分配一个新的 inode id
    def _alloc_inode_id(self) -> int:
        for inode_id in range(self.super_block.inode_cnt):
            if self.super_block.free_inode_bitmap._get_bit(inode_id) == 0:
                self.super_block.free_inode_bitmap._set_bit(inode_id, 1)
                self.super_block.free_inode_cnt -= 1
                return inode_id
        raise NoFreeInodeError("no free inode available")

    # _ensure_name_available 检查目录中是否已经存在同名的文件或目录
    def _ensure_name_available(self, dir_block: DirBlock, name: str) -> None:
        if name in dir_block.son_dirs or name in dir_block.son_files:
            raise AlreadyExistsError(f"name already exists: {name}")

    # _resolve_parent 解析路径，返回父目录的 inode、DirBlock 和新建项的名字
    def _resolve_parent(self, path: str) -> tuple[Inode, DirBlock, str]:
        normalized = self._normalize_path(path)
        if normalized == BASE_NAME:
            raise FileSystemError("cannot create root")

        parent_path, name = posixpath.split(normalized)
        if not parent_path:
            parent_path = BASE_NAME

        parent_inode, parent_dir = self._resolve_dir(parent_path)
        return parent_inode, parent_dir, name

    # _resolve_dir 解析路径，返回目录的 inode 和 DirBlock，如果路径指向的是文件则抛出 NotDirectoryError
    def _resolve_dir(self, path: str) -> tuple[Inode, DirBlock]:
        inode, dir_block = self._resolve_path(path)
        if not inode.is_dir:
            raise NotDirectoryError(f"not a directory: {path}")
        return inode, dir_block

    # _resolve_path 解析路径，返回最后一个组件的 inode 和 DirBlock（如果是目录的话），如果路径不存在则抛出 PathNotFoundError
    def _resolve_path(self, path: str) -> tuple[Inode, DirBlock | None]:
        normalized = self._normalize_path(path)
        if normalized == BASE_NAME:
            return self._read_root()

        inode, dir_block = self._read_root() if normalized.startswith(BASE_NAME) else (
            self.cwd_inode,
            self.cwd_dir,
        )

        parts = [part for part in normalized.strip(BASE_NAME).split("/") if part]
        if not normalized.startswith(BASE_NAME):
            parts = [part for part in path.split("/") if part and part != "."]

        for part in parts:
            if part == "..":
                raise FileSystemError("cd .. is not implemented yet")

            inode_id = dir_block.son_dirs.get(part) if dir_block else None
            if inode_id is None:
                if dir_block and part in dir_block.son_files:
                    file_inode = self._read_inode(dir_block.son_files[part])
                    return file_inode, None
                raise PathNotFoundError(f"path not found: {path}")

            inode = self._read_inode(inode_id)
            dir_block = self._read_dir(inode)

        return inode, dir_block

    # _normalize_path 将输入路径转换为绝对路径，处理 "." 和 ".." 等特殊组件
    def _normalize_path(self, path: str) -> str:
        if not path or path == ".":
            return self.cwd_path
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
            raise NotDirectoryError(f"inode {inode.inode_id} is not a directory")
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


# def names(entries: Iterable[tuple[str, int]]) -> list[str]:
#     """Small helper for tests/demos that only need names."""

#     return [name for name, _type in entries]
