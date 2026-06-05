"""
    文件系统核心 API, 提供 ls、mkdir、touch、cd 等用户操作，底层通过磁盘镜像实现持久化。
"""

from __future__ import annotations

import fnmatch
import posixpath
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from head import *
from storage.disk import open_disk, read_block, write_block
from core.format_disk import format_disk, read_super_block, write_super_block
from storage.inode_io import clear_inode_slot, read_inode, write_inode
from core.mount import MountedFileSystem, mount
from core.inode_cache import InodeCache, InodeCacheError, MemoryInode
from dataStruct.open_file import OpenFile, parse_open_mode
from storage.object_io import ObjectIOError, pack_object, read_object, write_object

from dataStruct.data import DirBlock, SuperBlock
from dataStruct import Inode
from dataStruct.Inode import DEFAULT_DIR_MODE, DEFAULT_FILE_MODE, PRIVATE_DIR_MODE
from user import User

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
        self.current_user: User | None = None
        self.inode_cache = InodeCache(self.path)
        self._cwd_memory_inode = self.iget(ROOT_ID)
        self.cwd_inode = self._cwd_memory_inode.inode
        self.cwd_dir = mounted.root_dir
        self.cwd_path = BASE_NAME
        # 打开文件表，key 是文件描述符，value 是 OpenFile 对象
        self.open_file_table: dict[int, OpenFile] = {}
        self.next_fd = 3
        self._closed = False

    # format_and_mount 格式化磁盘并挂载
    @classmethod
    def format_and_mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        format_disk(path)
        return cls(mount(path))

    # mount 从磁盘镜像加载文件系统元数据并挂载
    @classmethod
    def mount(cls, path: str | Path = DISK_NAME) -> "FileSystem":
        return cls(mount(path))

    # iget 获取指定 inode 的共享内存副本，并增加一次引用
    def iget(self, inode_id: int) -> MemoryInode:
        try:
            return self.inode_cache.iget(inode_id)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # iput 释放一次内存 inode 引用
    def iput(self, memory_inode: MemoryInode) -> None:
        try:
            self.inode_cache.iput(memory_inode)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # sync 将全部脏 inode 写回磁盘
    def sync(self) -> None:
        try:
            self.inode_cache.flush()
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # shutdown 关闭 fd、写回脏 inode，并释放当前目录引用
    def shutdown(self) -> None:
        if self._closed:
            return
        self.close_all()
        self.sync()
        self.iput(self._cwd_memory_inode)
        self._closed = True

    # close_all 关闭全部文件描述符
    def close_all(self) -> None:
        for fd in list(self.open_file_table):
            self.close(fd)

    # 用户操作接口：ls 返回目录下的 (name, type) 列表
    def ls(self, path: str = ".") -> list[tuple[str, int]]:

        inode, dir_block = self._resolve_dir(path)
        self._check_permission(inode, "r")
        self._check_permission(inode, "x")
        return dir_block.file_name_and_types()

    # mkdir 创建目录，返回新目录的 inode id
    def mkdir(self, path: str) -> int:

        # 解析路径，获取父目录的 inode 和 DirBlock，以及新建目录的名字
        parent_inode, parent_dir, name = self._resolve_parent(path)
        if not name:
            raise FileSystemError("directory name cannot be empty")
        self._ensure_name_available(parent_dir, name)
        self._ensure_dir_entry_capacity(parent_dir)
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode_id = self._alloc_inode_id()
            data_block_id = self.super_block.get_data_block_id(fp)

            inode = Inode(inode_id, self._current_user_id(), DEFAULT_DIR_MODE)
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
        self._ensure_dir_entry_capacity(parent_dir)
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode_id = self._alloc_inode_id()

            inode = Inode(inode_id, self._current_user_id(), DEFAULT_FILE_MODE)
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
        self._check_permission(inode, "x")
        new_cwd_memory_inode = self.iget(inode.inode_id)
        self.iput(self._cwd_memory_inode)
        self._cwd_memory_inode = new_cwd_memory_inode
        self.cwd_inode = new_cwd_memory_inode.inode
        self.cwd_dir = dir_block
        self.cwd_path = self._normalize_path(path)
        return self.cwd_path

    # pwd 返回当前目录的绝对路径
    def pwd(self) -> str:
        return self.cwd_path

    # login 校验用户名和密码，并记录当前用户会话
    def login(self, username: str, password: str) -> None:
        user = self.super_block.users.get(username)
        if user is None or not user.login(username, password):
            raise FileSystemError("invalid username or password")
        self.current_user = user

    # logout 清除当前用户会话
    def logout(self) -> None:
        self.current_user = None

    # whoami 返回当前登录用户名；未登录时返回 guest
    def whoami(self) -> str:
        return self.current_user.name if self.current_user is not None else "guest"

    # useradd 由 root 创建新用户，并为用户创建 /home/<username>
    def useradd(self, username: str, password: str) -> int:
        self._require_root_user()
        self._validate_username(username)
        if username in self.super_block.users:
            raise FileSystemError(f"user already exists: {username}")
        self._ensure_user_capacity()

        user_id = self._next_user_id()
        home_path = f"/home/{username}"
        old_user = self.current_user
        self.current_user = self.super_block.users["root"]
        try:
            self._ensure_dir_exists("/home")
            self.mkdir(home_path)
            home_inode, _home_dir = self._resolve_dir(home_path)
            with self._hold_inode(home_inode.inode_id) as memory_inode:
                memory_inode.inode.owner_id = user_id
                memory_inode.inode.user_id = user_id
                memory_inode.inode.mode = PRIVATE_DIR_MODE
                self._mark_inode_dirty(memory_inode)
            user = User(username, password, user_id, home_path)
            self.super_block.users[username] = user
            self._write_super_block_to_disk()
        finally:
            self.current_user = old_user
        return user_id

    # passwd 修改用户密码；root 可改任意用户，普通用户只能改自己
    def passwd(self, username: str, new_password: str) -> None:
        self._require_login()
        if username not in self.super_block.users:
            raise FileSystemError(f"user not found: {username}")
        if not self._is_root_user() and self.current_user.name != username:
            raise FileSystemError("permission denied")

        self.super_block.users[username].set_password(new_password)
        if self.current_user and self.current_user.name == username:
            self.current_user = self.super_block.users[username]
        self._write_super_block_to_disk()

    # users 返回所有用户名，按 user_id 排序
    def users(self) -> list[str]:
        self._require_root_user()
        return [
            user.name
            for user in sorted(
                self.super_block.users.values(),
                key=lambda item: item.user_id,
            )
        ]

    # su 校验目标用户密码，并切换当前会话；若有 home 目录则切换过去
    def su(self, username: str, password: str) -> None:
        self.login(username, password)
        home_path = self.current_user.home_path
        if home_path:
            try:
                self.cd(home_path)
            except FileSystemError:
                pass

    # chmod 修改文件或目录权限，只有 root 或 owner 可修改
    def chmod(self, path: str, mode: int | str) -> None:
        inode, _dir_block = self._resolve_path(path)
        mode_value = self._parse_mode(mode)
        if not self._is_root_user() and self._current_user_id() != self._inode_owner_id(inode):
            raise FileSystemError("permission denied")
        with self._hold_inode(inode.inode_id) as memory_inode:
            memory_inode.inode.mode = mode_value
            self._mark_inode_dirty(memory_inode)

    # stat 返回文件或目录的关键元数据
    def stat(self, path: str) -> dict[str, object]:
        inode, _dir_block = self._resolve_path(path)
        return {
            "inode_id": inode.inode_id,
            "type": "dir" if inode.is_dir else "file",
            "owner_id": self._inode_owner_id(inode),
            "mode": self._mode_to_string(self._inode_mode(inode)),
            "size": inode.size,
        }

    def tree(self, path: str = ".") -> list[str]:
        inode, dir_block = self._resolve_path(path)
        normalized = self._normalize_path(path)
        label = normalized if normalized == BASE_NAME else normalized.rstrip("/")
        if inode.is_dir:
            self._check_permission(inode, "r")
            self._check_permission(inode, "x")
            lines = [f"{label}/" if label != BASE_NAME else label]
            lines.extend(self._tree_lines(normalized, dir_block, ""))
            return lines
        return [label]

    def find(self, pattern: str, path: str = ".") -> list[str]:
        inode, dir_block = self._resolve_path(path)
        if not inode.is_dir:
            raise FileSystemError(f"not a directory: {path}")

        normalized = self._normalize_path(path)
        self._check_permission(inode, "r")
        self._check_permission(inode, "x")

        matches = []
        self._find_matches(normalized, dir_block, pattern, matches)
        return matches

    def link(self, source_path: str, target_path: str) -> None:
        source_inode, _dir_block = self._resolve_path(source_path)
        if source_inode.is_dir:
            raise FileSystemError(f"is a directory: {source_path}")

        parent_inode, parent_dir, name = self._resolve_parent(target_path)
        if not name:
            raise FileSystemError("link name cannot be empty")
        self._ensure_name_available(parent_dir, name)
        self._ensure_dir_entry_capacity(parent_dir)
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")

        with open_disk(self.path) as fp:
            parent_dir.add_new_file(name, source_inode.inode_id)
            self._write_dir(fp, parent_inode, parent_dir)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)

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

        if readable:
            self._check_permission(inode, "r")
        if writable:
            self._check_permission(inode, "w")

        # 分配文件描述符并让打开文件表持有内存 inode 的长期引用。
        fd = self.next_fd
        self.next_fd += 1
        memory_inode = self.iget(inode.inode_id)
        try:
            lock_mode = "write" if writable else "read"
            if writable:
                self.inode_cache.acquire_write(memory_inode, fd)
            else:
                self.inode_cache.acquire_read(memory_inode, fd)

            # 必须先成功获取写锁，再截断文件。
            if truncate:
                self._write_file_memory_inode(memory_inode, b"")
            if offset < 0:
                offset = memory_inode.inode.size

            self.open_file_table[fd] = OpenFile(
                fd=fd,
                memory_inode=memory_inode,
                path=self._normalize_path(path),
                mode=mode,
                offset=offset,
                readable=readable,
                writable=writable,
                lock_mode=lock_mode,
            )
        except InodeCacheError as exc:
            self.inode_cache.release_access(memory_inode, fd)
            self.iput(memory_inode)
            raise FileSystemError(str(exc)) from exc
        except Exception:
            self.inode_cache.release_access(memory_inode, fd)
            self.iput(memory_inode)
            raise
        return fd

    # close 关闭文件，释放文件描述符
    def close(self, fd: int) -> None:
        open_file = self._get_open_file(fd)
        try:
            self.inode_cache.release_access(open_file.memory_inode, fd)
            self.iput(open_file.memory_inode)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc
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

        data = self._read_file_memory_inode(open_file.memory_inode)
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

        old_data = self._read_file_memory_inode(open_file.memory_inode)
        offset = open_file.offset
        if offset > len(old_data):
            old_data = old_data + b"\x00" * (offset - len(old_data))

        new_data = old_data[:offset] + bytes(data) + old_data[offset + len(data):]
        self._write_file_memory_inode(open_file.memory_inode, new_data)
        open_file.offset = offset + len(data)
        return len(data)

    # seek 调整文件描述符对应的文件的当前偏移量，返回新的偏移量
    def seek(self, fd: int, offset: int, whence: int = 0) -> int:
        open_file = self._get_open_file(fd)
        inode = open_file.memory_inode.inode

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
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")
        if name in parent_dir.son_dirs:
            raise FileSystemError(f"is a directory: {path}")
        inode_id = parent_dir.son_files.get(name)
        if inode_id is None:
            raise FileSystemError(f"file not found: {path}")
        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            self._remove_file_link(fp, parent_dir, name, inode_id)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)

    # cp 复制文件，支持跨目录复制
    def cp(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        # 解析源文件路径
        src_inode, src_dir = self._resolve_path(src)
        if src_inode.is_dir:
            if src_dir is None:
                raise FileSystemError(f"path not found: {src}")
            self._cp_dir(src, src_inode, src_dir, dst, overwrite=overwrite)
            return

        # 检查源文件读取权限
        self._check_permission(src_inode, "r")

        # 读取源文件内容，并遵守源文件的共享读锁规则
        src_data = self.read_file(src)

        # 解析目标路径
        try:
            dst_inode, dst_dir = self._resolve_dir(dst)
            # 如果目标是目录，则在目录下创建同名文件
            dst_parent_inode = dst_inode
            dst_parent_dir = dst_dir
            dst_name = posixpath.basename(self._normalize_path(src))
            dst_is_dir = True
        except FileSystemError:
            # 如果目标不是目录，则解析父目录
            dst_parent_inode, dst_parent_dir, dst_name = self._resolve_parent(dst)
            dst_is_dir = False

        # 检查目标父目录写入和执行权限
        self._check_permission(dst_parent_inode, "w")
        self._check_permission(dst_parent_inode, "x")
        if dst_name not in dst_parent_dir.son_files:
            self._ensure_dir_entry_capacity(dst_parent_dir)

        # 检查目标是否已存在
        if dst_name in dst_parent_dir.son_files:
            if not overwrite:
                raise FileSystemError(f"file already exists: {dst}")
            existing_inode_id = dst_parent_dir.son_files[dst_name]
            with open_disk(self.path) as fp:
                self.super_block = read_super_block(fp)
                self._remove_file_link(fp, dst_parent_dir, dst_name, existing_inode_id)
                write_super_block(fp, self.super_block)

        # 创建新文件并写入数据
        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode_id = self._alloc_inode_id()

            inode = Inode(inode_id, self._current_user_id(), src_inode.mode)
            inode.is_dir = False

            dst_parent_dir.add_new_file(dst_name, inode_id)

            write_inode(fp, inode_id, inode)
            self._write_dir(fp, dst_parent_inode, dst_parent_dir)
            write_super_block(fp, self.super_block)

        # 构建目标文件路径
        if dst_is_dir:
            target_path = posixpath.join(dst, posixpath.basename(self._normalize_path(src)))
        else:
            target_path = dst

        # 写入文件内容
        self.write_file(self._normalize_path(target_path), src_data)

        self._refresh_cwd_if_changed(dst_parent_inode.inode_id, dst_parent_dir)

    # mv 移动或重命名文件
    def mv(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        # 解析源文件路径
        src_inode, src_dir = self._resolve_path(src)
        if src_inode.is_dir:
            if src_dir is None:
                raise FileSystemError(f"path not found: {src}")
            self._mv_dir(src, src_inode, src_dir, dst, overwrite=overwrite)
            return

        # 检查源文件读取权限（需要读取源文件内容）
        self._check_permission(src_inode, "r")

        # 解析源文件父目录
        src_parent_inode, src_parent_dir, src_name = self._resolve_parent(src)

        # 检查源文件父目录写入权限（需要从源目录删除文件）
        self._check_permission(src_parent_inode, "w")
        self._check_permission(src_parent_inode, "x")

        # 解析目标路径
        try:
            dst_inode, dst_dir = self._resolve_dir(dst)
            # 如果目标是目录，则在目录下使用同名文件
            dst_parent_inode = dst_inode
            dst_parent_dir = dst_dir
            dst_name = posixpath.basename(self._normalize_path(src))
            dst_is_dir = True
        except FileSystemError:
            # 如果目标不是目录，则解析父目录
            dst_parent_inode, dst_parent_dir, dst_name = self._resolve_parent(dst)
            dst_is_dir = False

        # 检查目标父目录写入和执行权限
        self._check_permission(dst_parent_inode, "w")
        self._check_permission(dst_parent_inode, "x")

        # 如果源和目标相同，直接返回
        if src_parent_inode.inode_id == dst_parent_inode.inode_id and src_name == dst_name:
            return
        if src_parent_inode.inode_id != dst_parent_inode.inode_id and dst_name not in dst_parent_dir.son_files:
            self._ensure_dir_entry_capacity(dst_parent_dir)

        # 检查目标是否已存在
        if dst_name in dst_parent_dir.son_files:
            if not overwrite:
                raise FileSystemError(f"file already exists: {dst}")
            existing_inode_id = dst_parent_dir.son_files[dst_name]
            with open_disk(self.path) as fp:
                self.super_block = read_super_block(fp)
                self._remove_file_link(fp, dst_parent_dir, dst_name, existing_inode_id)
                write_super_block(fp, self.super_block)

        # 移动文件
        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)

            if src_parent_inode.inode_id == dst_parent_inode.inode_id:
                # 同一个目录内重命名
                src_parent_dir.son_files.pop(src_name)
                src_parent_dir.son_files[dst_name] = src_inode.inode_id
                self._write_dir(fp, src_parent_inode, src_parent_dir)
            else:
                # 不同目录间移动：从源目录删除，添加到目标目录
                src_parent_dir.remove(src_name, FILE_TYPE)
                self._write_dir(fp, src_parent_inode, src_parent_dir)

                # 添加到目标目录
                dst_parent_dir.add_new_file(dst_name, src_inode.inode_id)
                self._write_dir(fp, dst_parent_inode, dst_parent_dir)

            write_super_block(fp, self.super_block)

        # 如果移动到了不同目录，需要刷新两个目录的缓存
        self._refresh_cwd_if_changed(src_parent_inode.inode_id, src_parent_dir)
        self._refresh_cwd_if_changed(dst_parent_inode.inode_id, dst_parent_dir)

    # rename 重命名文件或目录（仅支持同一父目录内改名；跨目录请用 mv）
    def rename(self, src: str, new_name: str, *, overwrite: bool = False) -> None:
        if not new_name:
            raise FileSystemError("new name cannot be empty")
        if "/" in new_name:
            raise FileSystemError("rename does not support path; use mv for moving across directories")

        normalized_src = self._normalize_path(src)
        if normalized_src == BASE_NAME:
            raise FileSystemError("cannot rename root directory")

        parent_inode, parent_dir, old_name = self._resolve_parent(normalized_src)
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")

        src_is_file = old_name in parent_dir.son_files
        src_is_dir = old_name in parent_dir.son_dirs
        if not src_is_file and not src_is_dir:
            raise FileSystemError(f"path not found: {src}")

        if old_name == new_name:
            return

        if new_name in parent_dir.son_files or new_name in parent_dir.son_dirs:
            if not overwrite:
                raise FileSystemError(f"file already exists: {new_name}")
            if src_is_dir:
                raise FileSystemError("cannot overwrite when renaming a directory")
            if new_name in parent_dir.son_dirs:
                raise FileSystemError("cannot overwrite a directory")

            existing_inode_id = parent_dir.son_files[new_name]
            with open_disk(self.path) as fp:
                self.super_block = read_super_block(fp)
                self._remove_file_link(fp, parent_dir, new_name, existing_inode_id)
                write_super_block(fp, self.super_block)

        with open_disk(self.path) as fp:
            if src_is_file:
                inode_id = parent_dir.son_files.pop(old_name)
                parent_dir.son_files[new_name] = inode_id
            else:
                inode_id = parent_dir.son_dirs.pop(old_name)
                parent_dir.son_dirs[new_name] = inode_id
            self._write_dir(fp, parent_inode, parent_dir)
            if src_is_dir:
                dir_inode = read_inode(fp, inode_id)
                if not dir_inode.direct_blocks:
                    raise FileSystemError(f"directory inode {inode_id} has no data block")
                dir_block = read_object(fp, DATA_BLOCK_START_ID + dir_inode.direct_blocks[0])
                if not isinstance(dir_block, DirBlock):
                    raise FileSystemError(f"inode {inode_id} does not point to a DirBlock")
                dir_block.name = new_name
                write_object(fp, DATA_BLOCK_START_ID + dir_inode.direct_blocks[0], dir_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)

    def _set_mode_like(self, inode_id: int, source: Inode) -> None:
        with self._hold_inode(inode_id) as memory_inode:
            memory_inode.inode.mode = self._inode_mode(source)
            self._mark_inode_dirty(memory_inode)

    def _cp_dir(self, src: str, src_inode: Inode, src_dir: DirBlock, dst: str, *, overwrite: bool) -> None:
        src_path = self._normalize_path(src).rstrip("/")
        if src_path == BASE_NAME:
            raise FileSystemError("cannot copy root directory")
        self._check_permission(src_inode, "r")
        self._check_permission(src_inode, "x")

        try:
            dst_dir_inode, _dst_dir_block = self._resolve_dir(dst)
            self._check_permission(dst_dir_inode, "w")
            self._check_permission(dst_dir_inode, "x")
            dst_path = posixpath.join(self._normalize_path(dst).rstrip("/"), posixpath.basename(src_path))
        except FileSystemError:
            dst_path = self._normalize_path(dst).rstrip("/")

        self._cp_dir_exact(src_path, src_inode, src_dir, dst_path, overwrite=overwrite)

    def _cp_dir_exact(self, src_path: str, src_inode: Inode, src_dir: DirBlock, dst_path: str, *, overwrite: bool) -> None:
        try:
            dst_inode, dst_dir = self._resolve_dir(dst_path)
        except FileSystemError:
            try:
                existing_inode, _existing_dir = self._resolve_path(dst_path)
            except FileSystemError:
                existing_inode = None
            if existing_inode is not None and not existing_inode.is_dir:
                if not overwrite:
                    raise FileSystemError(f"file already exists: {dst_path}")
                self.remove(dst_path)
            try:
                self.mkdir(dst_path)
            except Exception as exc:
                raise FileSystemError(str(exc)) from exc
            dst_inode, dst_dir = self._resolve_dir(dst_path)
            self._set_mode_like(dst_inode.inode_id, src_inode)

        for name in list(src_dir.son_files.keys()):
            self.cp(posixpath.join(src_path, name), posixpath.join(dst_path, name), overwrite=overwrite)

        for name in list(src_dir.son_dirs.keys()):
            child_src_path = posixpath.join(src_path, name)
            child_inode, child_dir = self._resolve_dir(child_src_path)
            self._check_permission(child_inode, "r")
            self._check_permission(child_inode, "x")
            if child_dir is None:
                raise FileSystemError(f"path not found: {child_src_path}")
            self._cp_dir_exact(child_src_path, child_inode, child_dir, posixpath.join(dst_path, name), overwrite=overwrite)

    def _mv_dir(self, src: str, src_inode: Inode, src_dir: DirBlock, dst: str, *, overwrite: bool) -> None:
        src_path = self._normalize_path(src).rstrip("/")
        if src_path == BASE_NAME:
            raise FileSystemError("cannot move root directory")
        if self._is_cwd_or_ancestor(src_path):
            raise FileSystemError(f"cannot move current directory or its ancestor: {src}")

        src_parent_inode, src_parent_dir, src_name = self._resolve_parent(src_path)
        self._check_permission(src_parent_inode, "w")
        self._check_permission(src_parent_inode, "x")
        if src_name not in src_parent_dir.son_dirs:
            if src_name in src_parent_dir.son_files:
                raise FileSystemError(f"not a directory: {src}")
            raise FileSystemError(f"path not found: {src}")

        try:
            dst_inode, dst_dir = self._resolve_dir(dst)
            dst_parent_inode = dst_inode
            dst_parent_dir = dst_dir
            dst_name = posixpath.basename(src_path)
            dst_path = posixpath.join(self._normalize_path(dst).rstrip("/"), dst_name)
        except FileSystemError:
            dst_parent_inode, dst_parent_dir, dst_name = self._resolve_parent(dst)
            dst_path = self._normalize_path(dst).rstrip("/")

        self._check_permission(dst_parent_inode, "w")
        self._check_permission(dst_parent_inode, "x")

        if dst_path == src_path or dst_path.startswith(src_path.rstrip("/") + "/"):
            raise FileSystemError("cannot move a directory into itself")

        if src_parent_inode.inode_id == dst_parent_inode.inode_id and src_name == dst_name:
            return

        if dst_name in dst_parent_dir.son_files:
            if not overwrite:
                raise FileSystemError(f"file already exists: {dst}")
            existing_inode_id = dst_parent_dir.son_files[dst_name]
            with open_disk(self.path) as fp:
                self.super_block = read_super_block(fp)
                self._remove_file_link(fp, dst_parent_dir, dst_name, existing_inode_id)
                write_super_block(fp, self.super_block)

        if dst_name in dst_parent_dir.son_dirs:
            if not overwrite:
                raise FileSystemError(f"directory already exists: {dst}")
            self.rmdir(dst_path, recursive=True)
            parent_path = posixpath.dirname(dst_path) or BASE_NAME
            dst_parent_inode, dst_parent_dir = self._resolve_dir(parent_path)

        with open_disk(self.path) as fp:
            if src_parent_inode.inode_id == dst_parent_inode.inode_id:
                inode_id = src_parent_dir.son_dirs.pop(src_name)
                src_parent_dir.son_dirs[dst_name] = inode_id
                self._write_dir(fp, src_parent_inode, src_parent_dir)
            else:
                inode_id = src_parent_dir.son_dirs.pop(src_name)
                self._write_dir(fp, src_parent_inode, src_parent_dir)
                dst_parent_dir.add_new_dir(dst_name, inode_id)
                self._write_dir(fp, dst_parent_inode, dst_parent_dir)

            dir_inode = read_inode(fp, inode_id)
            if not dir_inode.direct_blocks:
                raise FileSystemError(f"directory inode {inode_id} has no data block")
            dir_block = read_object(fp, DATA_BLOCK_START_ID + dir_inode.direct_blocks[0])
            if not isinstance(dir_block, DirBlock):
                raise FileSystemError(f"inode {inode_id} does not point to a DirBlock")
            dir_block.name = dst_name
            dir_block.parent_inode_id = dst_parent_inode.inode_id
            write_object(fp, DATA_BLOCK_START_ID + dir_inode.direct_blocks[0], dir_block)

        self._refresh_cwd_if_changed(src_parent_inode.inode_id, src_parent_dir)
        self._refresh_cwd_if_changed(dst_parent_inode.inode_id, dst_parent_dir)

    # rmdir 删除指定路径的目录，目录必须为空
    def rmdir(self, path: str, *, recursive: bool = False) -> None:
        normalized = self._normalize_path(path)
        if normalized == BASE_NAME:
            raise FileSystemError("cannot remove root directory")
        if self._is_cwd_or_ancestor(normalized):
            raise FileSystemError(f"cannot remove current directory or its ancestor: {path}")

        parent_inode, parent_dir, name = self._resolve_parent(path)
        self._check_permission(parent_inode, "w")
        self._check_permission(parent_inode, "x")
        inode_id = parent_dir.son_dirs.get(name)
        if inode_id is None:
            if name in parent_dir.son_files:
                raise FileSystemError(f"not a directory: {path}")
            raise FileSystemError(f"directory not found: {path}")

        inode, dir_block = self._resolve_dir(normalized)
        if not recursive and (dir_block.son_files or dir_block.son_dirs):
            raise FileSystemError(f"directory is not empty: {path}")
        self._ensure_inode_not_in_use(inode_id)
        if recursive:
            self._ensure_dir_tree_not_in_use(dir_block)

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode = read_inode(fp, inode.inode_id)
            if recursive:
                subtree_link_counts = self._collect_subtree_file_links(fp, dir_block)
                total_link_counts = {
                    file_inode_id: self._count_file_references(fp, file_inode_id)
                    for file_inode_id in subtree_link_counts
                }
                self._remove_dir_children(
                    fp,
                    dir_block,
                    subtree_link_counts,
                    total_link_counts,
                    set(),
                )
            self._free_inode_data_blocks(fp, inode)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)
            parent_dir.remove(name, DIR_TYPE)
            self._write_dir(fp, parent_inode, parent_dir)
            write_super_block(fp, self.super_block)

        self._refresh_cwd_if_changed(parent_inode.inode_id, parent_dir)


    # 以下是一些内部辅助方法：

    # 当前用户 ID，如果没有用户登录则返回 root 用户 ID
    def _current_user_id(self) -> int:
        return self.current_user.user_id if self.current_user is not None else ROOT_ID

    # # 有效用户 ID，等同于当前用户 ID；如果没有用户登录则返回 root 用户 ID
    # def _effective_user_id(self) -> int:
    #     return self.current_user.user_id if self.current_user is not None else ROOT_ID

    # 获取owner_id
    def _inode_owner_id(self, inode: Inode) -> int:
        if not hasattr(inode, "owner_id"):
            inode.owner_id = getattr(inode, "user_id", ROOT_ID)
        return inode.owner_id

    # 获取mode
    def _inode_mode(self, inode: Inode) -> int:
        if not hasattr(inode, "mode"):
            inode.mode = DEFAULT_DIR_MODE if inode.is_dir else DEFAULT_FILE_MODE
        return inode.mode

    # 检查当前用户是否有指定权限，否则抛出权限错误；root 用户拥有所有权限
    def _check_permission(self, inode: Inode, permission: str) -> None:
        if self._is_root_user() or self.current_user is None:
            return

        bit_map = {"r": 4, "w": 2, "x": 1}
        if permission not in bit_map:
            raise FileSystemError(f"invalid permission: {permission}")

        mode = self._inode_mode(inode)
        owner_id = self._inode_owner_id(inode)
        user_id = self._current_user_id()
        shift = 3 if user_id == owner_id else 0

        if not ((mode >> shift) & bit_map[permission]):
            raise FileSystemError("permission denied")

    # 解析mode
    def _parse_mode(self, mode: int | str) -> int:
        if isinstance(mode, str):
            if len(mode) != 2 or any(ch not in "01234567" for ch in mode):
                raise FileSystemError(f"invalid mode: {mode}")
            mode_value = int(mode, 8)
        elif isinstance(mode, int):
            mode_value = mode
        else:
            raise TypeError("mode must be int or str")
        if mode_value < 0 or mode_value > 0o77:
            raise FileSystemError(f"invalid mode: {mode}")
        return mode_value

    # mode 转换为字符串形式的权限表示，例如 0o75 -> "75"
    def _mode_to_string(self, mode: int) -> str:
        return format(mode, "02o")

    # _write_super_block_to_disk 将当前内存中的超级块写回磁盘
    def _write_super_block_to_disk(self) -> None:
        with open_disk(self.path) as fp:
            write_super_block(fp, self.super_block)

    # 检查是否有用户登录
    def _require_login(self) -> None:
        if self.current_user is None:
            raise FileSystemError("login required")

    # 检查当前用户是否是 root 用户
    def _is_root_user(self) -> bool:
        return self.current_user is not None and self.current_user.user_id == ROOT_ID

    # 检查当前用户是否是 root 用户，否则抛出权限错误
    def _require_root_user(self) -> None:
        self._require_login()
        if not self._is_root_user():
            raise FileSystemError("permission denied")

    # 验证用户名是否合法
    def _validate_username(self, username: str) -> None:
        if not username:
            raise FileSystemError("username cannot be empty")
        if username in {".", ".."} or "/" in username:
            raise FileSystemError(f"invalid username: {username}")

    # 用户ID分配
    def _next_user_id(self) -> int:
        used_ids = {user.user_id for user in self.super_block.users.values()}
        user_id = 1
        while user_id in used_ids:
            user_id += 1
        return user_id

    def _ensure_user_capacity(self) -> None:
        if len(self.super_block.users) >= MAX_USER_COUNT:
            raise FileSystemError(f"user limit reached: max {MAX_USER_COUNT} users")

    def _ensure_dir_entry_capacity(self, dir_block: DirBlock) -> None:
        entry_count = len(dir_block.son_files) + len(dir_block.son_dirs)
        if entry_count >= MAX_DIR_ENTRY_COUNT:
            raise FileSystemError(
                f"directory entry limit reached: max {MAX_DIR_ENTRY_COUNT} entries"
            )
    
    # 确保目录存在，如果不存在则创建
    def _ensure_dir_exists(self, path: str) -> None:
        try:
            self._resolve_dir(path)
        except FileSystemError:
            self.mkdir(path)

    # 根据文件描述符获取对应的 OpenFile 对象
    def _get_open_file(self, fd: int) -> OpenFile:
        try:
            return self.open_file_table[fd]
        except KeyError as exc:
            raise FileSystemError(f"invalid file descriptor: {fd}") from exc

    # _hold_inode 临时持有一次 inode 引用，并确保异常时也会释放
    @contextmanager
    def _hold_inode(self, inode_id: int) -> Iterator[MemoryInode]:
        try:
            with self.inode_cache.hold(inode_id) as memory_inode:
                yield memory_inode
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # _mark_inode_dirty 标记内存 inode 已被修改
    def _mark_inode_dirty(self, memory_inode: MemoryInode) -> None:
        try:
            self.inode_cache.mark_dirty(memory_inode)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # _ensure_inode_not_in_use 删除前检查 inode 是否仍存在活动引用或访问锁
    def _ensure_inode_not_in_use(self, inode_id: int) -> None:
        try:
            self.inode_cache.ensure_unused(inode_id)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # _discard_cached_inode 删除磁盘 inode 前移除缓存中的旧副本
    def _discard_cached_inode(self, inode_id: int) -> None:
        try:
            self.inode_cache.discard(inode_id)
        except InodeCacheError as exc:
            raise FileSystemError(str(exc)) from exc

    # 从磁盘读取指定文件 inode 的内容，返回 bytes
    def _read_file_inode(self, inode_id: int) -> bytes:
        with self._hold_inode(inode_id) as memory_inode:
            return self._read_file_memory_inode(memory_inode)

    # 根据内存 inode 读取文件内容
    def _read_file_memory_inode(self, memory_inode: MemoryInode) -> bytes:
        inode = memory_inode.inode
        if inode.is_dir:
            raise FileSystemError(f"inode {inode.inode_id} is a directory")

        content = bytearray()
        with open_disk(self.path) as fp:
            for data_block_id in self._file_data_block_ids(fp, inode):
                block = read_block(fp, DATA_BLOCK_START_ID + data_block_id)
                content.extend(block)

        return bytes(content[: inode.size])

    # 将数据写入指定文件 inode，更新 inode 的直接索引和间接索引，并写回磁盘
    def _write_file_inode(self, inode_id: int, data: bytes | bytearray) -> None:
        with self._hold_inode(inode_id) as memory_inode:
            self._write_file_memory_inode(memory_inode, data)

    # 将数据写入内存 inode 指向的文件，并将 inode 标记为脏
    def _write_file_memory_inode(
        self,
        memory_inode: MemoryInode,
        data: bytes | bytearray,
    ) -> None:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes or bytearray")
        data = bytes(data)
        needed_blocks = self._required_block_count(len(data))

        if needed_blocks > self._max_file_block_count():
            max_size = self._max_file_block_count() * BLOCK_SIZE
            raise FileSystemError(f"file is too large: max {max_size} bytes")

        with open_disk(self.path) as fp:
            self.super_block = read_super_block(fp)
            inode = memory_inode.inode
            if inode.is_dir:
                raise FileSystemError(f"inode {inode.inode_id} is a directory")

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
            inode.modify_time = time.time()
            self._mark_inode_dirty(memory_inode)
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

    def _remove_file_link(
        self,
        fp,
        parent_dir: DirBlock,
        name: str,
        inode_id: int,
        *,
        total_references: int | None = None,
        removed_references: int = 1,
        released_file_inodes: set[int] | None = None,
    ) -> None:
        if total_references is None:
            total_references = self._count_file_references(fp, inode_id)

        should_release_inode = total_references <= removed_references
        already_released = released_file_inodes is not None and inode_id in released_file_inodes

        if should_release_inode and not already_released:
            self._ensure_inode_not_in_use(inode_id)
            with self._hold_inode(inode_id) as memory_inode:
                self._free_inode_data_blocks(fp, memory_inode.inode)
            self._discard_cached_inode(inode_id)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)
            if released_file_inodes is not None:
                released_file_inodes.add(inode_id)

        parent_dir.remove(name, FILE_TYPE)

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
    def _remove_dir_children(
        self,
        fp,
        dir_block: DirBlock,
        subtree_link_counts: dict[int, int],
        total_link_counts: dict[int, int],
        released_file_inodes: set[int],
    ) -> None:
        for name, inode_id in list(dir_block.son_files.items()):
            self._remove_file_link(
                fp,
                dir_block,
                name,
                inode_id,
                total_references=total_link_counts.get(inode_id, 1),
                removed_references=subtree_link_counts.get(inode_id, 1),
                released_file_inodes=released_file_inodes,
            )

        for name, inode_id in list(dir_block.son_dirs.items()):
            with self._hold_inode(inode_id) as memory_inode:
                child_dir = self._read_dir_from_fp(fp, memory_inode.inode)
                self._remove_dir_children(
                    fp,
                    child_dir,
                    subtree_link_counts,
                    total_link_counts,
                    released_file_inodes,
                )
                self._free_inode_data_blocks(fp, memory_inode.inode)
            self._discard_cached_inode(inode_id)
            self._free_inode_id(inode_id)
            clear_inode_slot(fp, inode_id)
            dir_block.remove(name, DIR_TYPE)

        dir_block.son_files.clear()
        dir_block.son_dirs.clear()
        dir_block.counts = 0

    # _ensure_dir_tree_not_in_use 递归删除前检查整棵子树，避免部分删除
    def _ensure_dir_tree_not_in_use(self, dir_block: DirBlock) -> None:
        for inode_id in dir_block.son_files.values():
            self._ensure_inode_not_in_use(inode_id)

        for inode_id in dir_block.son_dirs.values():
            self._ensure_inode_not_in_use(inode_id)
            inode = self._read_inode(inode_id)
            self._ensure_dir_tree_not_in_use(self._read_dir(inode))

    # _is_cwd_or_ancestor 判断路径是否为 cwd 或 cwd 的祖先目录
    def _is_cwd_or_ancestor(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        return self.cwd_path == normalized or self.cwd_path.startswith(normalized.rstrip("/") + "/")

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
            self._check_permission(inode, "x")
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
        if path.startswith("~"):
            path = self._expand_home_path(path)
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

    def _expand_home_path(self, path: str) -> str:
        if path == "~":
            suffix = ""
        elif path.startswith("~/"):
            suffix = path[2:]
        else:
            raise FileSystemError(f"invalid path: {path}")

        home_path = self._current_home_path()
        if not suffix:
            return home_path
        return posixpath.join(home_path, suffix)

    # _read_root 读取根目录的 inode 和 DirBlock
    def _read_root(self) -> tuple[Inode, DirBlock]:
        inode = self._read_inode(ROOT_ID)
        return inode, self._read_dir(inode)

    # _read_inode 从内存 inode 表获取指定 inode 的当前副本
    def _read_inode(self, inode_id: int) -> Inode:
        with self._hold_inode(inode_id) as memory_inode:
            return memory_inode.inode

    # _read_dir 从磁盘读取指定目录 inode 的 DirBlock 对象
    def _read_dir(self, inode: Inode) -> DirBlock:
        if not inode.is_dir:
            raise FileSystemError(f"inode {inode.inode_id} is not a directory")
        if not inode.direct_blocks:
            raise FileSystemError(f"directory inode {inode.inode_id} has no data block")

        with open_disk(self.path) as fp:
            return self._read_dir_from_fp(fp, inode)

    def _read_dir_from_fp(self, fp, inode: Inode) -> DirBlock:
        if not isinstance(inode, Inode):
            raise TypeError("inode must be an Inode")
        if not inode.is_dir:
            raise FileSystemError(f"inode {inode.inode_id} is not a directory")
        if not inode.direct_blocks:
            raise FileSystemError(f"directory inode {inode.inode_id} has no data block")

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

    def _current_home_path(self) -> str:
        if self.current_user is None or not self.current_user.home_path:
            raise FileSystemError("login required")
        if self.current_user.name == "root":
            try:
                self._resolve_dir(self.current_user.home_path)
            except FileSystemError:
                return BASE_NAME
        return self.current_user.home_path

    def _sorted_dir_entries(self, dir_block: DirBlock) -> list[tuple[str, int]]:
        entries = [(name, DIR_TYPE) for name in sorted(dir_block.son_dirs)]
        entries.extend((name, FILE_TYPE) for name in sorted(dir_block.son_files))
        return entries

    def _tree_lines(self, base_path: str, dir_block: DirBlock, prefix: str) -> list[str]:
        entries = self._sorted_dir_entries(dir_block)
        lines = []
        for index, (name, entry_type) in enumerate(entries):
            child_path = posixpath.join(base_path, name)
            is_last = index == len(entries) - 1
            branch = "`-- " if is_last else "|-- "
            next_prefix = prefix + ("    " if is_last else "|   ")

            if entry_type == DIR_TYPE:
                inode = self._read_inode(dir_block.son_dirs[name])
                line = f"{prefix}{branch}{name}/"
                if self._can_list_directory(inode):
                    child_dir = self._read_dir(inode)
                    lines.append(line)
                    lines.extend(self._tree_lines(child_path, child_dir, next_prefix))
                else:
                    lines.append(f"{line} [permission denied]")
                continue

            lines.append(f"{prefix}{branch}{name}")
        return lines

    def _find_matches(
        self,
        base_path: str,
        dir_block: DirBlock,
        pattern: str,
        matches: list[str],
    ) -> None:
        for name in sorted(dir_block.son_dirs):
            child_path = posixpath.join(base_path, name)
            if fnmatch.fnmatch(name, pattern):
                matches.append(child_path)
            inode = self._read_inode(dir_block.son_dirs[name])
            if self._can_list_directory(inode):
                self._find_matches(child_path, self._read_dir(inode), pattern, matches)

        for name in sorted(dir_block.son_files):
            if fnmatch.fnmatch(name, pattern):
                matches.append(posixpath.join(base_path, name))

    def _can_list_directory(self, inode: Inode) -> bool:
        try:
            self._check_permission(inode, "r")
            self._check_permission(inode, "x")
        except FileSystemError:
            return False
        return True

    def _count_file_references(self, fp, inode_id: int) -> int:
        root_inode = read_inode(fp, ROOT_ID)
        root_dir = self._read_dir_from_fp(fp, root_inode)
        return self._count_file_references_in_dir(fp, root_dir, inode_id)

    def _count_file_references_in_dir(self, fp, dir_block: DirBlock, inode_id: int) -> int:
        count = sum(1 for current_inode_id in dir_block.son_files.values() if current_inode_id == inode_id)
        for child_inode_id in dir_block.son_dirs.values():
            child_inode = read_inode(fp, child_inode_id)
            child_dir = self._read_dir_from_fp(fp, child_inode)
            count += self._count_file_references_in_dir(fp, child_dir, inode_id)
        return count

    def _collect_subtree_file_links(self, fp, dir_block: DirBlock) -> dict[int, int]:
        counts: dict[int, int] = {}
        for inode_id in dir_block.son_files.values():
            counts[inode_id] = counts.get(inode_id, 0) + 1
        for child_inode_id in dir_block.son_dirs.values():
            child_inode = read_inode(fp, child_inode_id)
            child_dir = self._read_dir_from_fp(fp, child_inode)
            child_counts = self._collect_subtree_file_links(fp, child_dir)
            for inode_id, count in child_counts.items():
                counts[inode_id] = counts.get(inode_id, 0) + count
        return counts
