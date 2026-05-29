"""
    用于实现初始化的功能
    1. 实现磁盘的初始化
    2. 创建根目录的 inode 和 dir block，并将它们写入磁盘
    3. 将根目录的 inode 标记为已使用
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = SRC_DIR / "data"

for import_path in (str(SRC_DIR), str(DATA_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from dataclasses import dataclass

from head import DISK_NAME
from storage.disk import open_disk
from dataStruct.data import DirBlock, SuperBlock
from dataStruct import Inode
from core.format_disk import read_root, read_super_block, format_disk

# 从磁盘镜像中加载超级块元数据，返回一个 MountedFileSystem 对象。
@dataclass(frozen=True)
class MountedFileSystem:

    path: Path
    super_block: SuperBlock
    root_inode: Inode
    root_dir: DirBlock

# 从磁盘镜像中加载超级块元数据，返回一个 MountedFileSystem 对象。
def mount(path: str | Path = DISK_NAME) -> MountedFileSystem:

    disk_path = Path(path)

    with open_disk(disk_path) as fp:
        super_block = read_super_block(fp)
        root_inode, root_dir = read_root(fp, super_block)

    return MountedFileSystem(
        path=disk_path,
        super_block=super_block,
        root_inode=root_inode,
        root_dir=root_dir,
    )

# 初始化磁盘镜像，创建一个新的磁盘文件，并挂在载它
def init(path: str | Path = DISK_NAME) -> MountedFileSystem:

    format_disk(path)
    return mount(path)
