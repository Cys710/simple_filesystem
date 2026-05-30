# Agent Guide

## 项目定位

FMS 是一个用 Python 实现的教学型模拟文件系统。项目目标可以概括为：

```text
在一个固定大小的磁盘镜像中，实现多用户、多目录、可持久化的类 Unix 文件系统。
```

当前代码已经具备底层磁盘块读写、对象序列化、inode 槽位读写、磁盘格式化、挂载、根目录初始化，以及基础 shell 命令雏形。下一阶段的重点不是继续堆命令，而是把“用户身份、目录树、权限、文件内容、删除回收、测试”这几条主线补完整。

## 当前项目结构

- `src/head.py`：全局常量，定义磁盘大小、块大小、inode 区、数据区、文件类型、根目录、颜色等。
- `src/storage/disk.py`：固定大小磁盘镜像和块级 IO，包括 `create_disk`、`open_disk`、`read_block`、`write_block`。
- `src/storage/object_io.py`：把 Python 对象序列化后写入一个或多个完整磁盘块。
- `src/storage/inode_io.py`：把 inode 写入 inode 区的 256 字节槽位，避免覆盖同一块内的其他 inode。
- `src/dataStruct/Inode.py`：`InodeBitmap` 和 `Inode` 数据结构。
- `src/dataStruct/data.py`：`SuperBlock` 和 `DirBlock`，包含空闲 inode、空闲数据块、目录项等核心元数据。
- `src/dataStruct/groupList.py`：成组链接法管理空闲数据块。
- `src/core/format_disk.py`：创建磁盘镜像、初始化超级块、空闲块链、根 inode 和根目录。
- `src/core/mount.py`：挂载磁盘镜像并读取超级块和根目录。
- `src/core/file_system.py`：面向 shell 的核心 API，目前已有 `ls`、`mkdir`、`touch`、`cd`、`pwd`。
- `src/cli/shell.py`：交互式 shell，负责命令解析和调用 `FileSystem`。
- `src/user.py`：简单用户模型，当前只有用户名、MD5 密码和用户 id。
- `src/main.py`：入口文件或历史入口代码。
- `test/test_group_list.py`：成组链接法和数据块分配相关单元测试。
- `docs/`：预留文档目录。

## 当前已实现能力

### 磁盘与块 IO

项目使用固定大小磁盘镜像：

- 磁盘大小：`4MB`
- 块大小：`4096B`
- 总块数：`1024`
- 超级块：`1` 块
- inode 区：`128` 块
- inode 大小：`256B`
- inode 总数：`2048`
- 数据块数：`895`
- 数据区起始块：`129`

`storage.disk` 已经把原始文件包装成块设备，后续上层代码应只通过块 id 读写，而不要在业务逻辑中手动计算任意文件偏移。

### 元数据持久化

项目有两类持久化方式：

1. `object_io.py`：适合 `SuperBlock`、`DirBlock`、`GroupList` 这种完整对象。
2. `inode_io.py`：专门处理 inode 槽位，每个 inode 只占 256 字节。

注意：不要用 `object_io.py` 直接保存单个 inode，否则容易破坏 inode 区布局。

### 格式化与挂载

`core.format_disk.format_disk()` 现在会：

1. 创建磁盘镜像。
2. 构造并初始化 `SuperBlock`。
3. 初始化空闲数据块成组链接。
4. 分配根目录的数据块。
5. 标记 root inode 已使用。
6. 写入 root inode 和 root `DirBlock`。
7. 写回超级块。

`core.mount.mount()` 会读取超级块、root inode 和 root 目录，返回 `MountedFileSystem`。

### 基础目录操作

`FileSystem` 当前已提供：

- `format_and_mount(path)`
- `mount(path)`
- `ls(path=".")`
- `mkdir(path)`
- `touch(path)`
- `cd(path)`
- `pwd()`

也就是说，项目已经从“纯数据结构”推进到了“能通过 shell 创建目录和空文件”的阶段。

## 当前主要问题

### 1. 编码和注释损坏

大量中文注释出现 mojibake 乱码，影响阅读和维护。建议后续统一将源码保存为 UTF-8，并逐步替换损坏注释。这个清理应单独做，不要混在功能提交里。

### 2. 用户系统尚未接入文件系统

`src/user.py` 只有孤立的 `User` 类，`FileSystem` 创建 inode 时仍基本使用 `ROOT_ID`。目前还没有：

- 用户表持久化。
- 登录状态。
- 当前用户上下文。
- 用户主目录。
- 用户和文件 owner 的真实关联。
- 用户组和权限校验。

这与“多用户文件系统”的目标差距最大，应优先设计。

### 3. 多目录能力只是初步可用

当前已有路径解析、`mkdir`、`cd`、`ls`，但目录树还不完整：

- 没有 `.` 和 `..` 目录项的显式语义。
- 目录删除未实现。
- 递归删除未实现。
- 路径错误、重名、文件/目录类型冲突需要更多测试。
- 目录容量限制没有明确策略。
- 目录项只记录名称到 inode id，缺少更统一的 entry 结构。

### 4. 文件内容还未实现

`touch` 只创建空文件 inode，没有实现：

- 写文件内容。
- 读文件内容。
- 追加写。
- 文件截断。
- 文件大小更新。
- 直接块和间接块分配。
- 文件删除时释放数据块。

### 5. 权限模型不完整

`Inode` 中有 `user_id` 和 `user_group`，但缺少标准权限字段和检查流程。目前 shell 命令不会根据用户身份拒绝访问。

建议引入简化版 Unix 权限：

```text
owner_id
group_id
mode: rwx for owner/group/others
```

目录权限语义建议：

- `r`：允许列出目录。
- `w`：允许在目录中创建、删除、重命名子项。
- `x`：允许进入目录、路径穿越。

文件权限语义建议：

- `r`：允许读取文件内容。
- `w`：允许写入或截断文件。
- `x`：可暂时保留，不一定立即实现执行语义。

### 6. 删除与资源回收缺失

目前已存在空闲 inode bitmap 和空闲数据块链，但还缺少完整的释放流程：

- `rm file`：释放文件数据块、释放 inode、从父目录移除目录项。
- `rmdir dir`：只允许删除空目录。
- `rm -r dir`：递归删除目录树。
- 删除失败时应避免部分写入造成元数据不一致。

### 7. 测试覆盖不足

当前测试主要覆盖 `GroupList` 和空闲数据块行为。后续至少需要补：

- 磁盘块读写测试。
- 对象 IO 测试。
- inode 槽位读写测试。
- format/mount 测试。
- root 目录持久化测试。
- `mkdir/touch/ls/cd/pwd` 测试。
- 路径解析测试。
- 用户登录和权限测试。
- 文件读写和删除回收测试。

## 多用户多目录文件系统设计建议

### 数据模型

建议把核心对象扩展为以下几类：

```text
SuperBlock
  - inode/data block allocation state
  - user table location
  - root inode id

User
  - user_id
  - username
  - password_hash
  - primary_group_id
  - home_inode_id

Group
  - group_id
  - group_name
  - member_user_ids

Inode
  - inode_id
  - type: file/dir
  - owner_id
  - group_id
  - mode
  - size
  - direct_blocks
  - indirect_block
  - create_time
  - modify_time

DirBlock
  - inode_id
  - parent_inode_id
  - entries: name -> DirectoryEntry

DirectoryEntry
  - name
  - inode_id
  - type
```

当前 `DirBlock.son_files` 和 `DirBlock.son_dirs` 可以继续短期使用，但中期建议合并成 `entries`，这样 `ls`、`rename`、`stat`、权限检查会更统一。

### 推荐目录结构

格式化后建议创建：

```text
/
/root
/home
/etc
```

后续新增用户时创建：

```text
/home/alice
/home/bob
```

其中：

- `/` 属于 root。
- `/root` 只允许 root 访问。
- `/home` 允许普通用户进入和查看。
- `/home/<user>` 属于该用户。
- `/etc` 可用于保存用户表、组表等系统配置对象。

### 用户登录流程

建议 `Shell` 保存当前登录用户，`FileSystem` 保存当前用户上下文：

```python
fs.login(username, password)
fs.logout()
fs.current_user
```

命令层可以增加：

```text
login username
logout
useradd username
passwd username
whoami
```

第一阶段可以只支持 root 创建用户；普通用户登录后只能操作自己的 home 目录和有权限访问的目录。

### 权限检查位置

权限检查应放在 `FileSystem` 核心层，而不是 shell 层。shell 只负责解析命令，不能绕过权限。

建议每个公开 API 的开头或路径解析过程中调用：

```python
check_read(inode)
check_write(inode)
check_execute(inode)
```

典型规则：

- `ls /dir` 需要目录 `r` 和 `x`。
- `cd /dir` 需要目录 `x`。
- `touch /dir/a.txt` 需要父目录 `w` 和 `x`。
- `mkdir /dir/sub` 需要父目录 `w` 和 `x`。
- `read file` 需要文件 `r`。
- `write file` 需要文件 `w`。
- root 用户可以绕过普通权限限制。

## 推荐实现顺序

### 阶段 1：先稳定当前基础链路

目标：让现有单用户、多目录雏形稳定可测。

1. 修复明显语法和导入问题。
2. 统一磁盘镜像路径，建议默认使用项目根目录下的 `disk.img`。
3. 为 `format -> mount -> mkdir -> touch -> ls -> cd -> pwd -> restart -> mount -> ls` 增加测试。
4. 把 `FileSystem` 的路径解析行为测试清楚，包括绝对路径、相对路径、`.`、`..`。

验收标准：

```text
格式化后创建的目录和文件，退出进程再挂载仍然存在。
```

### 阶段 2：补文件内容读写

目标：实现真正的文件，而不是只有文件名。

建议新增 API：

```python
fs.read_file(path) -> bytes
fs.write_file(path, data: bytes, append=False)
fs.truncate(path)
```

shell 命令可以先做简化版：

```text
cat file
write file text...
append file text...
```

验收标准：

```text
write a.txt hello
cat a.txt
退出后重新 mount
cat a.txt 仍输出 hello
```

### 阶段 3：实现删除和资源回收

目标：避免 inode 和数据块只分配不释放。

建议新增：

```python
fs.rm(path)
fs.rmdir(path)
fs.unlink(path)
fs.free_inode(inode_id)
fs.free_data_blocks(inode)
```

验收标准：

```text
创建文件占用 inode/data block
删除文件后 free_inode_cnt/free_data_block_cnt 回升
重新创建文件可复用释放的资源
```

### 阶段 4：接入用户系统

目标：从单 root 模式进入多用户模式。

建议先实现最小闭环：

1. 格式化时创建 root 用户。
2. 用户表持久化到固定位置，或通过 `/etc/users` 管理。
3. 支持 `login`、`logout`、`whoami`。
4. 支持 `useradd`，自动创建 `/home/<username>`。
5. 新建文件和目录的 owner 是当前用户。

验收标准：

```text
root 创建 alice
alice 登录
pwd 默认进入 /home/alice
alice 创建的文件 owner_id 是 alice 的 user_id
重启挂载后用户和 home 目录仍存在
```

### 阶段 5：实现权限

目标：不同用户不能随意读写彼此文件。

建议先实现 `chmod` 的数字模式：

```text
chmod 755 dir
chmod 644 file
```

再实现：

```text
chown user file
chgrp group file
```

验收标准：

```text
alice 的私有目录 bob 不能 cd
alice 给文件设置 644 后 bob 可以读但不能写
root 可以访问所有路径
```

### 阶段 6：完善目录操作

目标：让多目录行为接近真实文件系统。

建议补：

```text
mv old new
cp src dst
rename old new
tree [path]
stat path
```

其中 `stat` 对调试很有价值，建议优先实现。

## 开发约定

### 分层原则

保持三层边界清楚：

```text
storage 层：只关心磁盘块和对象读写。
core 层：负责 inode、目录、用户、权限、文件内容等文件系统语义。
cli 层：只解析命令并展示结果。
```

不要在 shell 中直接操作 `SuperBlock`、`Inode`、`DirBlock`，否则后续权限和一致性很难维护。

### 持久化原则

任何修改元数据的操作，都要明确写回：

```text
修改 inode -> write_inode
修改 DirBlock -> write_object
修改 SuperBlock -> write_super_block
```

如果一次操作涉及多个对象，建议固定写回顺序，并在测试中覆盖失败前后的状态。

### 路径解析原则

路径解析建议统一在 `FileSystem` 中完成，并支持：

```text
/
.
..
相对路径
绝对路径
连续斜杠
尾部斜杠
```

创建文件或目录时，先解析父目录，再检查名称合法性和权限。

### 测试原则

每个核心能力都应有“进程内测试”和“重新挂载测试”：

```text
format
operation
assert
mount again
assert again
```

文件系统最容易出错的地方不是内存状态，而是写回和重新挂载后的状态。

## 近期最值得做的事情

按优先级排序：

1. 修复并测试当前 format/mount/shell 基础链路。
2. 为 `FileSystem.mkdir/touch/ls/cd/pwd` 增加单元测试。
3. 统一路径和编码，清理损坏注释。
4. 实现文件内容读写。
5. 实现删除和资源回收。
6. 设计并持久化用户表。
7. 接入登录态和用户 home 目录。
8. 增加 owner/group/mode 权限字段。
9. 在所有公开 `FileSystem` API 中做权限检查。
10. 扩展 shell 命令并补充端到端测试。

## 建议的第一个里程碑

第一个真正完整的里程碑建议定义为：

```text
format
mount
mkdir /home
mkdir /home/alice
touch /home/alice/a.txt
write /home/alice/a.txt hello
exit
mount
cat /home/alice/a.txt
```

如果重新挂载后仍能正确看到目录、文件和内容，就说明底层持久化链路已经可靠。

第二个里程碑再加入用户：

```text
format
login root
useradd alice
login alice
pwd                    # /home/alice
touch note.txt
write note.txt hello
logout
login root
stat /home/alice/note.txt
```

第三个里程碑加入权限：

```text
login alice
chmod 600 private.txt
login bob
cat /home/alice/private.txt   # permission denied
login root
cat /home/alice/private.txt   # allowed
```

## 挂载后的内存运行态

这个项目不应该只实现磁盘镜像部分。真实文件系统在挂载后，还会有一批驻留内存的运行态结构。磁盘负责长期保存，内存负责当前会话的操作状态和访问加速。

可以这样区分：

```text
磁盘态：退出程序后仍然存在，例如 super block、inode、目录块、文件数据块、用户表。
内存态：mount 后创建，退出或 unmount 后消失，例如当前用户、当前目录、打开文件表、缓存。
```

当前项目已经有一点内存态：`mount()` 会把超级块、root inode、root 目录读出来放进 `FileSystem` 对象。但它还不是完整的运行态设计。

### 应该较早实现的运行态

这些不是缓存优化，而是文件系统语义本身的一部分，建议在基础命令阶段就逐步加入：

```python
class FileSystem:
    current_user
    cwd_inode_id
    cwd_path
    open_file_table
    next_fd
```

含义如下：

- `current_user`：当前登录用户，后续权限检查依赖它。
- `cwd_inode_id` / `cwd_path`：当前工作目录，每个 shell 会话都应该有自己的当前位置。
- `open_file_table`：打开文件表，保存 fd 到打开文件对象的映射。
- `next_fd`：下一个可分配的文件描述符，通常可以从 `3` 开始。

建议的打开文件对象：

```python
class OpenFile:
    fd: int
    inode_id: int
    path: str
    mode: str
    offset: int
    readable: bool
    writable: bool
```

### 文件读写建议走 fd 模型

后续实现 `cat`、`write`、`append` 时，底层最好不要每次都直接“路径 -> 磁盘块”。更推荐先建立类似真实系统的文件描述符模型：

```text
open(path, mode) -> fd
read(fd, size) -> bytes
write(fd, data) -> int
seek(fd, offset)
close(fd)
```

典型流程：

```text
open("/home/a.txt", "r")
  -> 路径解析
  -> 权限检查
  -> 读取 inode
  -> 创建 OpenFile
  -> 分配 fd
  -> 放入 open_file_table
  -> 返回 fd

read(fd, size)
  -> 从 open_file_table 找到 OpenFile
  -> 根据 inode 和 offset 读取数据块
  -> 更新 offset

write(fd, data)
  -> 从 open_file_table 找到 OpenFile
  -> 检查 writable
  -> 根据 offset 写入数据块
  -> 更新 inode.size 和 modify_time
  -> 更新 offset

close(fd)
  -> 必要时写回 inode / super block
  -> 从 open_file_table 移除 fd
```

这样做的好处是，后续 shell 命令可以复用同一套核心 API：

```text
cat file       -> open + read + close
write file x   -> open + write + close
append file x  -> open + seek end + write + close
```

### 缓存优化可以后置

需要区分“运行态”和“缓存”：

```text
应该早点做：
current_user
cwd
open_file_table
fd
file offset

可以晚点做：
inode_cache
dir_cache
block_cache
dirty_inodes
dirty_dirs
dirty_blocks
sync
LRU
```

缓存是优化层，不应该改变文件系统基本语义。建议先让下面这个闭环稳定：

```text
format
mount
mkdir
touch
write
cat
exit
mount
cat
```

确认重新挂载后目录、文件和内容都还在，再加入 inode/dir/block 缓存。

### 后续缓存设计

等基本命令稳定后，可以加入：

```python
inode_cache: dict[int, Inode]
dir_cache: dict[int, DirBlock]
block_cache: dict[int, bytes]
dirty_inodes: set[int]
dirty_dirs: set[int]
dirty_blocks: set[int]
```

读取策略：

```text
缓存命中 -> 直接返回内存对象
缓存未命中 -> 从磁盘读取 -> 放入缓存 -> 返回
```

修改策略：

```text
先修改内存对象
标记 dirty
sync 或 close 或 unmount 时写回磁盘
```

后续可以增加命令：

```text
sync      将 dirty 的内存对象写回磁盘
unmount   先 sync，再释放内存态
```

推荐最终架构：

```text
disk.img
  ^
storage 层：read_block / write_block
  ^
cache 层：inode_cache / dir_cache / block_cache / dirty 标记
  ^
core 层：open/read/write/close/mkdir/ls/login/权限检查
  ^
cli 层：shell 命令
```

因此，项目实现顺序建议是：

```text
1. 先完成基础命令和磁盘持久化闭环。
2. 文件读写阶段引入 open/read/write/close 和 fd 模型。
3. 用户和权限接入 current_user。
4. 语义稳定后再做 inode/dir/block 缓存和 dirty 写回。
```

## 注意事项

- 当前项目使用 `pickle` 做本地模拟持久化，不要读取不可信磁盘镜像。
- `src/user.py` 使用 MD5 哈希，适合课程项目演示，不适合真实生产安全。
- 代码中已有用户未清理的历史注释和乱码，功能开发时优先保持行为正确。
- 若修改磁盘布局、inode 字段或序列化格式，旧的 `disk.img` 可能不兼容，应重新 format。
- 多用户和权限会影响所有命令，最好在文件内容读写稳定后再全面接入。
