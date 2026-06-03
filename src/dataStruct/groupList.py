
from dataStruct.block import Block
from head import DATA_BLOCK_START_ID, FREE_BLOCK_CNT, BLOCK_SIZE

# 成组链表法
class GroupList(Block):

    def __init__(self,block_id = 0, stack=None):
        self.block_id = block_id
        self.stack = list(stack) if stack is not None else [0]
        self._cnt = len(self.stack)

    @classmethod
    def from_existing_stack(cls, block_id, stack):
        if not stack:
            raise ValueError("空闲块栈不能为空")
        if len(stack) > FREE_BLOCK_CNT:
            raise ValueError("空闲块栈超过 FREE_BLOCK_CNT")
        return cls(block_id=block_id, stack=stack)
    
    @property
    def count(self):
        return self._cnt

    def has_free_space(self):
        return self._cnt < FREE_BLOCK_CNT

    def push(self, block_id):
        if not self.has_free_space():
            raise Exception("当前空闲块栈已满")
        self.stack.append(block_id)
        self._cnt += 1

    def pop(self):
        if self._cnt == 0:
            raise Exception("当前空闲块栈为空")
        self._cnt -= 1
        return self.stack.pop()

    def write_back(self, fp):
        db_id = DATA_BLOCK_START_ID + self.block_id
        fp.seek(db_id * BLOCK_SIZE)
        fp.write(bytes(self))
