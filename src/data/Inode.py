import time

from data import Block
from head import INODE_BLOCK_NUM, INODE_SIZE, BLOCK_SIZE, INODE_NUM, ROOT_ID  

# 索引位图表
class InodeBitmap(Block):

    def __init__(self):
        self.index_per_block = BLOCK_SIZE // INODE_SIZE         # 每块可以存储的索引节点数量
        self.block_num = INODE_BLOCK_NUM                        # 索引节点块数量
        self.bitmap = bytearray(INODE_NUM // 8)                 # 每个字节表示8个索引节点
    
    # 获取指定索引节点ID的位图值 (0表示空闲 1表示占用)
    def _get_bit(self,index):
        byte_index = index // 8
        bit_index = index % 8
        return (self.bitmap[byte_index] >> bit_index) & 1

    # 设置指定索引节点ID的位图值 (0表示空闲 1表示占用)
    def _set_bit(self,index,value):
        byte_index = index // 8
        bit_index = index % 8
        if value == 1:
            self.bitmap[byte_index] |= (1 << bit_index)
        else:
            self.bitmap[byte_index] &= ~(1 << bit_index)

# 索引节点
class Inode(Block):

    def __init__(self,inode_id,user_id):
        self.inode_id = inode_id                    # 索引节点ID
        self.user_id = user_id                      # 用户ID
        self.is_dir = False                         # 是否为目录
        self.size = 0                               # 文件大小
        self.direct_blocks = []                     # 直接索引块列表
        self.direct_blocks_size = 0                 # 直接索引块已使用大小
        self.indirect_block = None                  # 间接索引块ID
        self.create_time = time.time()              # 创建时间
        self.modify_time = time.time()              # 修改时间
        self.user_group = {ROOT_ID, user_id}        # 可访问用户