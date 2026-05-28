from data import Block
from head import DATA_BLOCK_START_ID, FREE_BLOCK_CNT, BLOCK_SIZE

# 成组链表法
class GroupList(Block):

    def __init__(self,start_block_id,cnt):
        # 起始块ID
        self.block_id = start_block_id
        # 块数量
        self._cnt = cnt
        # 空闲块栈 (从大到小初始化 以便后续分配时弹出较小的块ID)
        self.stack = [i for i in range(start_block_id+cnt,start_block_id,-1)]
        # self.next_group = None
        if self._cnt < FREE_BLOCK_CNT:  # 不足成组数目则是最后一组,在栈顶放入0
            self.stack.insert(0, 0)
    
    # 获取空闲块ID
    def get_free_block(self):
        """
        获得一个空闲的id
        :return: 大于0的值表示返回一个正确的
        """
        if self._cnt > 1:
            self._cnt -= 1
            return True, self.stack.pop(-1)
        else:
            return False, self.stack[0]
    
    # 检查是否有空余位置(没有则需要分配新的成组链表)
    def has_free_space(self):
        return self._cnt < FREE_BLOCK_CNT
    
    # 释放块ID
    def add_to_stack(self, block_id):
        self.stack.append(block_id)
        self._cnt += 1

    # no-used
    def get_next_stack(self):
        # 返回指向的下的下一个栈的id
        return self.stack[0]

    # 写回函数
    def write_back(self, fp):
        db_id = DATA_BLOCK_START_ID + self.block_id
        fp.seek(db_id * BLOCK_SIZE)
        fp.write(bytes(self))