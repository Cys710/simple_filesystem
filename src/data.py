"""
    主要的数据结构
"""

import pickle
import time
from head import *

# 基本块
class Block:
    # 序列化函数
    def __bytes__(self):
        return pickle.dumps(self)
    # 反序列化函数
    @staticmethod
    def from_bytes(b):
        try:
            obj = pickle.loads(b)
            return obj
        except Exception as e:
            raise TypeError(f"反序列化失败 Block: {e}")
    # 写回函数
    def write_back(self,fp):
        fp.write(bytes(self))

# 超级块
class SuperBlock(Block):
    def __init__(self):
        self.inode_free_num = INODE_BLOCK_NUM * 4
        self.block_free_num = INODE_BLOCK_NUM
