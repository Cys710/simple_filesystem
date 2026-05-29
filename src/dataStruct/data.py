"""
    主要的数据结构
"""
import time

from dataStruct.Inode import InodeBitmap
from dataStruct.block import Block
from dataStruct.groupList import GroupList
from head import *

# 超级块
class SuperBlock(Block):

    # 超级块包含文件系统的基本信息
    def __init__(self):
        self.inode_cnt = INODE_NUM                      # 索引节点数
        self.data_block_cnt = DATA_BLOCK_NUM            # 数据块数

        # 位图法 空闲索引节点
        self.free_inode_cnt = INODE_NUM                 # 空闲索引节点数
        self.free_inode_bitmap = InodeBitmap()          # 索引节点位图

        self.free_data_block_cnt = 0
        self.block_group_link = GroupList.from_existing_stack(0, [0])

        self.data_block_size = BLOCK_SIZE               # 数据块大小
        self.inode_size = INODE_SIZE                    # 索引节点大小
        self.base_dir_inode_id = ROOT_ID                # 根目录索引节点ID
    
    # 显示超级块信息
    def show_info(self):
       # TODO: 显示超级块信息
       pass

    def init_data_block_group_link(self, fp):
        """
        初始化成组链接法。
        相对数据块 0 用作链尾标记，不作为普通数据块分配。
        """
        self.block_group_link = GroupList.from_existing_stack(0, [0])
        self.free_data_block_cnt = 0

        for block_id in range(DATA_BLOCK_NUM - 1, 0, -1):
            self.free_up_data_block(fp, block_id)

    def get_data_block_id(self, fp):
        """
        获取一个空闲数据块ID
        :param fp: 文件指针
        :return: 大于0的值表示返回一个正确的ID,否则表示没有空闲数据块
        """
        if self.free_data_block_cnt == 0:
            raise Exception("没有空闲空间了")
        
        if self.block_group_link.count > 1:
            self.free_data_block_cnt -= 1
            return self.block_group_link.pop()
        
        group_leader_id = self.block_group_link.stack[0]

        if group_leader_id == 0:
            raise Exception("空闲块链已到末尾")
        
        fp.seek((DATA_BLOCK_START_ID + group_leader_id) * BLOCK_SIZE)
        self.block_group_link = GroupList.from_bytes(fp.read(BLOCK_SIZE))

        self.free_data_block_cnt -= 1

        return group_leader_id
    
    def free_up_data_block(self, fp, block_id):
        """
        bfree:
        如果超级块空闲栈未满，直接压栈；
        如果已满，把当前栈写入 block_id，让 block_id 成为新的组长块。
        """
        if block_id <= 0:
            raise ValueError("数据块 0 用作链尾标记，不能释放")

        if self.block_group_link.has_free_space():
            self.block_group_link.push(block_id)
        else:
            old_group = GroupList.from_existing_stack(
                block_id,
                self.block_group_link.stack
            )
            old_group.write_back(fp)

            self.block_group_link = GroupList.from_existing_stack(
                block_id,
                [block_id]
            )

        self.free_data_block_cnt += 1
    

# 目录块
class DirBlock(Block):

    def __init__(self, name , parent_inode_id):

        self.name = name                            # 目录名
        self.inode_id = None                        # 目录对应的索引节点ID
        self.parent_inode_id = parent_inode_id      # 父目录索引节点ID
        
        self.counts = 0
        self.son_files = dict()                     # 目录下的文件列表
        self.son_dirs = dict()                      # 目录下的子目录列表

    # 迭代器 返回目录下的所有文件和子目录
    def son_list(self):
        yield from self.son_files.items()
        yield from self.son_dirs.items()

    # 添加新目录
    def add_new_dir(self, name, inode_id):
        self.son_dirs[name] = inode_id
        self.counts += 1

    # 添加新文件
    def add_new_file(self, name, inode_id):
        self.son_files[name] = inode_id
        self.counts += 1
    
    #   获取文件/目录 索引节点ID
    def get_inode_id(self, name, type_x):
        if type_x == FILE_TYPE:
            return self.son_files.get(name)
        if type_x == DIR_TYPE:
            return self.son_dirs.get(name)

    # 检查文件/目录名称是否存在
    def check_name(self, name):
        if name in self.son_dirs or name in self.son_files:
            return False, f"新建的名字{name}已经存在"
        else:
            return True, None

    # 删除文件/目录
    def remove(self, name, flag):
        if flag == FILE_TYPE:
            self.son_files.pop(name)
            self.counts -= 1
        elif flag == DIR_TYPE:
            self.son_dirs.pop(name)
            self.counts -= 1

    def file_name_and_types(self):
        return [(key, DIR_TYPE) for key in self.son_dirs.keys()] \
               + [(key, FILE_TYPE) for key in self.son_files.keys()]

    def is_exist_son_files(self, name):
        """
        :return:1 存在son_files
        :return:0 存在son_dirs
        :return:-1 不存在
        """
        if name in self.son_files:
            return FILE_TYPE
        if name in self.son_dirs:
            return DIR_TYPE
        if name not in self.son_dirs and name not in self.son_files:
            return -1
        
    # def get_dir(self, dir_name):
    #     """
    #     获取对应目录的inode_id
    #     :param dir_name:
    #     :return:
    #     """
    #     return self.son_dirs.get(dir_name)

    # def get_file(self, file_name):
    #     """
    #     获取对应文件的inode_id
    #     :param file_name:
    #     :return:
    #     """
    #     return self.son_files.get(file_name)

    # def get_all_son_inode(self) -> list:
    #     """
    #     返回所有子目录文件的节点
    #     :return: list
    #     """
    #     return [v for _, v in self.son_files.items()] + [v for _, v in self.son_dirs.items()]
