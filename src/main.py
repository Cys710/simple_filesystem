"""
    程序的入口
    1. 实现磁盘的挂载和格式化功能
"""

from __future__ import annotations
from init import init
from shell import main

if __name__ == "__main__":
    main()
    # # 初始化磁盘镜像并挂载
    # fs = init()
    # print(f"mounted: {fs.path}")
    # print(f"free inodes: {fs.super_block.free_inode_cnt}")
    # print(f"free data blocks: {fs.super_block.free_data_block_cnt}")
    # print(f"root inode: {fs.root_inode.inode_id}")
    # print(f"root dir: {fs.root_dir.name}")
    