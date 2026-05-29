"""
    系统工具函数,方便实现一些功能
"""

# import time
# import pickle
# from math import ceil
# from head import BLOCK_SIZE,ROOT_ID,VERSION

# # 分块函数 文本按照大小分块返回
# def serializer(text: str) -> list:
#     b_text = pickle.dumps(text)
#     block_num = int(ceil(len(b_text) / BLOCK_SIZE))
#     yield from [b_text[BLOCK_SIZE * i:BLOCK_SIZE * (i + 1)] for i in range(block_num)]

# # 分块函数 字节流按照大小分块返回
# def split_serializer(b_obj: bytes) -> list:
#     block_num = int(ceil(len(b_obj) / BLOCK_SIZE))  
#     yield from [b_obj[BLOCK_SIZE * i:BLOCK_SIZE * (i + 1)] for i in range(block_num)]

# # 读取函数 从文件中读取指定块数的字节流
# def from_serializer(fp,block_num):
#     s = b''
#     for _ in range(block_num):
#         s += fp.read(BLOCK_SIZE)
#     return s

