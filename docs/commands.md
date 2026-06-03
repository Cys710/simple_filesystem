# 命令说明

本文档整理 shell 中可用的主要命令。程序内最新命令列表以 `help` 输出为准。

## 磁盘与会话

| 命令 | 说明 |
| --- | --- |
| `format [disk]` | 格式化磁盘镜像。如果不传路径，使用默认磁盘路径 |
| `mount [disk]` | 挂载磁盘镜像 |
| `sync` | 将脏 inode 写回磁盘 |
| `help` | 查看命令列表 |
| `clear` | 清屏 |
| `exit` / `quit` | 退出 shell |

## 目录命令

| 命令 | 说明 |
| --- | --- |
| `ls [path]` | 查看目录内容 |
| `mkdir dir_name` | 创建目录 |
| `rmdir [-r] directory` | 删除目录，`-r` 表示递归删除 |
| `cd path` | 切换当前工作目录 |
| `pwd` | 显示当前工作目录 |
| `tree [path]` | 以树形结构显示目录 |
| `find [path] pattern` | 查找匹配 pattern 的文件或目录 |

## 文件命令

| 命令 | 说明 |
| --- | --- |
| `touch file_name` | 创建文件 |
| `cat file` | 输出文件内容 |
| `write file text` | 向文件写入文本 |
| `append file text` | 向文件追加文本 |
| `rm file` | 删除文件 |
| `cp [-f] source destination` | 复制文件，`-f` 表示覆盖目标 |
| `mv [-f] source destination` | 移动文件，`-f` 表示覆盖目标 |
| `rename [-f] old_name new_name` | 在同一父目录内重命名 |
| `ln source target` | 创建硬链接 |
| `vim file` | 使用内置编辑器编辑文件 |
| `fill file [bytes]` | 向文件追加测试数据，用于演示大文件和间接块 |

## 文件描述符命令

| 命令 | 说明 |
| --- | --- |
| `open file [mode]` | 打开文件，返回 fd |
| `read fd [size]` | 从 fd 读取内容 |
| `write fd text` | 向 fd 写入文本 |
| `seek fd offset [whence]` | 移动 fd 的当前偏移 |
| `close fd` | 关闭 fd |

常见 mode：

```text
r     只读
w     写入
a     追加
r+    读写
w+    读写并截断
a+    读写并追加
```

## 用户命令

| 命令 | 说明 |
| --- | --- |
| `login username` | 登录用户 |
| `logout` | 登出 |
| `whoami` | 查看当前用户 |
| `who` | 查看当前用户 |
| `useradd username` | 创建用户，仅 root 可用 |
| `passwd [username]` | 修改密码 |
| `users` | 查看用户列表，仅 root 可用 |
| `su username` | 切换用户 |

密码通过隐藏输入读取，不应该写在命令行参数里。

## 权限与调试命令

| 命令 | 说明 |
| --- | --- |
| `chmod mode path` | 修改权限 |
| `stat path` | 查看文件或目录元信息 |
| `monitor` | 启动终端监控器 |
| `gui` | 启动图形界面 |

## 脚本命令

| 命令 | 说明 |
| --- | --- |
| `bash script.sh` | 执行脚本文件 |

脚本中可以写多行 shell 命令。空行和注释行会被跳过。

示例：

```text
format
login root
mkdir docs
touch docs/readme.txt
write docs/readme.txt hello
cat docs/readme.txt
```
