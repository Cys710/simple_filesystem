import pickle
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