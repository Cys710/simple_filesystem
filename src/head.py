"""
    头文件用来存储一些基本的配置变量
"""

# 磁盘文件
DISK_NAME = "../disk.img"
# 磁盘大小 4MB
DISK_SIZE = 4*1024*1024

# 块大小 4KB
BLOCK_SIZE = 4096

# 块数 1024
BLOCK_NUM = DISK_SIZE // BLOCK_SIZE
# 索引节点大小 256B
INODE_SIZE = 256

assert BLOCK_NUM == 1024,"块数异常"

# 1个超级块
SUPER_BLOCK_NUM = 1
# 磁盘索引块
INODE_BLOCK_NUM = 128
# 索引节点数 2048
INODE_NUM = (INODE_BLOCK_NUM * BLOCK_SIZE) // INODE_SIZE
assert INODE_NUM == 2048,"索引节点数异常"

# 数据块数 895
DATA_BLOCK_NUM = BLOCK_NUM - SUPER_BLOCK_NUM - INODE_BLOCK_NUM

assert DATA_BLOCK_NUM == 895,"数据块数异常"

# 位置
INODE_BLOCK_START_ID = SUPER_BLOCK_NUM
DATA_BLOCK_START_ID = SUPER_BLOCK_NUM + INODE_BLOCK_NUM

# 目录与文件限制 (有待修改)
DIR_NUM = 128          # 每个目录最大文件数（Linux实际无上限）

# 混合索引配置
DIRECT_CNT = 10       # 直接索引数
INDIRECT_CNT = 1      # 间接索引数

# 成组链表法配置
FREE_BLOCK_CNT = 50   # 一组块的数量

# 根目录ID
ROOT_ID = -1

# FREE_NODE_CNT = 32     # 超级块缓存空闲inode数
# FREE_BLOCK_CNT = 128   # 超级块缓存空闲数据块数

# 目录结构（模仿Linux）
BASE_NAME = "/"
FILE_TYPE = 0
DIR_TYPE = 1
ROOT_ID = 0
ROOT = 'root'

INIT_DIRS = ['root','home','etc']

VERSION = "V 1.0"

LOGO = r"""    
    ____   ______ _____
   / __ \ / ____// ___/
  / /_/ // /_    \__ \
 / ____// __/   ___/ /
/_/    /_/     /____/
                       
"""

# 颜色
FILE_COLOR_F = "37"   # 文件：白色
FILE_COLOR_B = "40"
DIR_COLOR_F = "32"    # 目录：绿色
DIR_COLOR_B = "40"

BLUE = "\033[1;34;40m"      # 亮蓝      (目录)
GREEN = "\033[1;32m"        # 亮绿色    (命令行头)
RESET = "\033[0m"           # 恢复默认  (白色)