"""
    磁盘的高级格式化：文件系统的初始化
    对应命令 format 
    完成 以下功能：
    1. 创建一个新的磁盘文件，覆盖原有数据
    2. 初始化超级块，设置数据块的空闲链表
    3. 初始化根目录的 inode 和 dir block，并将它们写入磁盘
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from head import DISK_NAME,BASE_NAME, BLOCK_SIZE, DATA_BLOCK_START_ID, ROOT_ID
from storage.disk import create_disk, open_disk
from storage.inode_io import read_inode, write_inode
from storage.object_io import read_object, write_object

from dataStruct.data import DirBlock, SuperBlock  
from dataStruct import Inode
from dataStruct.Inode import DEFAULT_DIR_MODE
from user import create_root_user

@dataclass(frozen=True)
class RootInitResult:

    super_block: SuperBlock
    root_inode: Inode
    root_dir: DirBlock
    root_dir_data_block_id: int

    @property
    def root_dir_disk_block_id(self) -> int:
        return DATA_BLOCK_START_ID + self.root_dir_data_block_id

# 标记一个 inode 已被分配
def mark_inode_used(super_block: SuperBlock, inode_id: int) -> None:

    if super_block.free_inode_bitmap._get_bit(inode_id) == 1:
        raise ValueError(f"inode {inode_id} is already allocated")

    super_block.free_inode_bitmap._set_bit(inode_id, 1)
    super_block.free_inode_cnt -= 1

# 创建根目录的 inode，设置它指向一个数据块
def create_root_inode(root_dir_data_block_id: int) -> Inode:

    root_inode = Inode(ROOT_ID, ROOT_ID)
    root_inode.is_dir = True
    root_inode.mode = DEFAULT_DIR_MODE
    root_inode.direct_blocks.append(root_dir_data_block_id)
    root_inode.direct_blocks_size = 1
    root_inode.size = BLOCK_SIZE
    return root_inode

# 创建根目录的 DirBlock 对象，设置它的名字和 inode id
def create_root_dir() -> DirBlock:

    root_dir = DirBlock(BASE_NAME, ROOT_ID)
    root_dir.inode_id = ROOT_ID
    return root_dir

# 初始化根目录：分配一个数据块给根目录，创建根目录的 inode 和 DirBlock，并将它们写入磁盘
def init_root(fp: BinaryIO, super_block: SuperBlock) -> RootInitResult:
    # 分配一个数据块给根目录
    root_dir_data_block_id = super_block.get_data_block_id(fp)
    mark_inode_used(super_block, ROOT_ID)
    # 创建根目录的 inode 和 DirBlock
    root_inode = create_root_inode(root_dir_data_block_id)
    root_dir = create_root_dir()
    # 写回磁盘
    write_inode(fp, ROOT_ID, root_inode)
    write_object(fp, DATA_BLOCK_START_ID + root_dir_data_block_id, root_dir)
    write_super_block(fp, super_block)

    return RootInitResult(
        super_block=super_block,
        root_inode=root_inode,
        root_dir=root_dir,
        root_dir_data_block_id=root_dir_data_block_id,
    )

SUPER_BLOCK_ID = 0
SUPER_BLOCK_BLOCK_COUNT = 1

# 初始化超级块，设置数据块的空闲链表
def build_super_block(fp: BinaryIO) -> SuperBlock:

    super_block = SuperBlock()
    super_block.init_data_block_group_link(fp)
    super_block.users = {"root": create_root_user()}
    return super_block

# 将超级块写入磁盘的第0块
def write_super_block(fp: BinaryIO, super_block: SuperBlock) -> None:

    write_object(
        fp,
        SUPER_BLOCK_ID,
        super_block,
        block_count=SUPER_BLOCK_BLOCK_COUNT,
    )

# 从磁盘的第0块读取超级块对象
def read_super_block(fp: BinaryIO) -> SuperBlock:

    obj = read_object(
        fp,
        SUPER_BLOCK_ID,
        block_count=SUPER_BLOCK_BLOCK_COUNT,
    )

    if not isinstance(obj, SuperBlock):
        raise TypeError(f"block 0 does not contain a SuperBlock: {type(obj)!r}")

    return obj

# 从磁盘中读取根目录的 inode 和 DirBlock 对象
def read_root(fp: BinaryIO, super_block: SuperBlock) -> tuple[Inode, DirBlock]:

    root_inode = read_inode(fp, ROOT_ID)

    if not root_inode.is_dir:
        raise ValueError("root inode is not marked as a directory")
    if not root_inode.direct_blocks:
        raise ValueError("root inode does not point to a directory block")

    root_dir_data_block_id = root_inode.direct_blocks[0]
    root_dir = read_object(fp, DATA_BLOCK_START_ID + root_dir_data_block_id)

    if not isinstance(root_dir, DirBlock):
        raise TypeError(f"root data block does not contain a DirBlock: {type(root_dir)!r}")

    return root_inode, root_dir


# 格式化磁盘：创建一个新的磁盘文件，覆盖原有数据，并初始化超级块
# 并创建根目录的 inode 和 dir block，并将它们写入磁盘
def format_disk(path: str | Path = DISK_NAME) -> RootInitResult:

    create_disk(path, overwrite=True)

    with open_disk(path) as fp:
        super_block = build_super_block(fp)
        result = init_root(fp, super_block)

    return result
