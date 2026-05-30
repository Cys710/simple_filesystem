# Agent Guide

## 项目定位

FMS 是一个用 Python 实现的教学型模拟文件系统。目标是：

```text
在固定大小的磁盘镜像中，实现多用户、多目录、可持久化的类 Unix 文件系统。
```

当前项目已经具备完整的基础链路：格式化、挂载、目录树、文件读写、文件描述符、删除回收、用户会话和简化权限控制。

## 当前项目结构

- `src/head.py`：全局常量，定义磁盘大小、块大小、inode 区、数据区、文件类型、根目录、颜色等。
- `src/storage/disk.py`：固定大小磁盘镜像和块级 IO。
- `src/storage/object_io.py`：对象序列化读写，适合 `SuperBlock`、`DirBlock`、间接块列表等完整对象。
- `src/storage/inode_io.py`：inode 槽位读写，每个 inode 固定 256 字节。
- `src/dataStruct/Inode.py`：`InodeBitmap` 和 `Inode`，包含 owner/mode 权限字段。
- `src/dataStruct/data.py`：`SuperBlock` 和 `DirBlock`。
- `src/dataStruct/groupList.py`：成组链接法管理空闲数据块。
- `src/dataStruct/open_file.py`：打开文件表项和打开模式解析。
- `src/core/format_disk.py`：创建磁盘镜像、初始化超级块、root 用户、根 inode 和根目录。
- `src/core/mount.py`：挂载磁盘镜像并读取超级块和根目录。
- `src/core/file_system.py`：文件系统核心 API。
- `src/cli/shell.py`：交互式 shell。
- `src/user.py`：用户模型，当前使用 MD5 保存密码哈希，root 默认密码为 `123456`。
- `test/`：单元测试，覆盖空闲块、文件读写、fd、删除、用户和权限。

## 当前已实现能力

### 磁盘与元数据

项目使用固定大小磁盘镜像：

```text
磁盘大小：4MB
块大小：4096B
总块数：1024
超级块：1 块
inode 区：128 块
inode 大小：256B
inode 总数：2048
数据块数：895
数据区起始块：129
```

持久化方式：

- `object_io.py`：把对象写入一个或多个完整块。
- `inode_io.py`：把 inode 写入固定 256B 槽位。

注意：inode 仍使用默认 pickle 序列化。当前去掉了 group 字段后，最大测试场景下 inode payload 约 244B，小于 254B 槽位容量。

### 格式化与挂载

`format_disk()` 会：

1. 创建磁盘镜像。
2. 初始化 `SuperBlock`。
3. 初始化空闲数据块成组链接。
4. 创建 root 用户并持久化到 `SuperBlock.users`。
5. 分配根目录数据块。
6. 写入 root inode 和 root `DirBlock`。
7. 写回超级块。

`mount()` 会读取超级块、root inode 和 root 目录，返回 `MountedFileSystem`。

### 目录、文件和 fd

`FileSystem` 当前支持：

```text
format_and_mount
mount
ls
mkdir
touch
cd
pwd
open
read
write
seek
close
read_file
write_file
remove
rmdir
```

文件内容支持：

- 覆盖写。
- 追加写。
- 按 fd 读取和写入。
- seek 调整 offset。
- 多 fd 独立 offset。
- 直接块 + 一级间接块。
- 删除文件和目录时释放 inode 和数据块。

### 用户系统

当前用户表保存在 `SuperBlock.users` 中，适合课程项目阶段使用。已实现：

```text
login username
logout
whoami / who
useradd username
passwd [username]
users
su username
```

当前规则：

- root 默认账号：`root`
- root 默认密码：`123456`
- `useradd` 只有 root 可以执行。
- `users` 只有 root 可以执行。
- `passwd`：root 可改任意用户，普通用户只能改自己的密码。
- `su` 校验密码后切换当前用户，并尝试进入该用户 home 目录。
- `useradd alice ...` 会自动创建 `/home` 和 `/home/alice`。
- `login`、`su`、`useradd`、`passwd` 的密码通过隐藏输入提示读取，不写在命令行里。

### 权限系统

当前权限模型是课设简化版，不实现 group：

```text
owner
others
mode
```

`chmod` 使用两位八进制写法，例如 `70`、`75`、`64`。

判断规则：

```text
当前用户是 owner -> 看 owner 位
当前用户不是 owner -> 看 others 位
root -> 绕过普通权限
未登录 guest -> 为兼容旧测试，暂按 root 处理
```

默认权限：

```text
普通文件：64
普通目录：75
/home/<user>：70
```

权限检查已接入：

```text
ls      目录 r + x
cd      目录 x
mkdir   父目录 w + x
touch   父目录 w + x
open r  文件 r
open w  文件 w
rm      父目录 w + x
rmdir   父目录 w + x
路径穿越 中间目录 x
```

调试命令：

```text
stat path
chmod mode path
```

## 当前命令

```text
format [disk]
mount [disk]
ls [path]
mkdir dir_name
touch file_name
cd path
pwd
cat file
write file text
append file text
open file [mode]
read fd [size]
write fd text
seek fd offset [whence]
close fd
rm file
rmdir [-r] directory
login username
logout
whoami
who
useradd username
passwd [username]
users
su username
chmod mode path
stat path
clear
exit
```

## 典型演示流程

```text
format
login root
useradd alice
useradd bob
su alice
write private.txt secret
stat private.txt
su bob
cat /home/alice/private.txt      # permission denied
su root
cat /home/alice/private.txt      # secret
```

开放读取但禁止写入：

```text
su alice
chmod 75 /home/alice
chmod 64 /home/alice/private.txt
su bob
cat /home/alice/private.txt      # allowed
write /home/alice/private.txt x  # permission denied
```

## 设计边界

- 当前不实现 group。`mode` 只包含 owner 和 others 两位。
- 当前用户表放在 `SuperBlock.users` 中，不使用 `/etc/passwd`。
- `src/user.py` 使用 MD5，适合课程演示，不适合真实生产安全。
- 当前仍使用 pickle 进行本地模拟持久化，不要读取不可信磁盘镜像。
- 修改 inode 字段或序列化结构后，旧 `disk.img` 可能不兼容，应重新 `format`。

## 后续建议

优先级建议：

1. 增加 `cp`、`mv`、`rename`。
2. 增加更完整的 `stat` 展示，例如创建时间、修改时间、直接块数量。
3. 增加 `tree`，方便展示目录结构。
4. 增加 `sync` / `unmount`，为后续缓存层做准备。
5. 根据课设要求决定是否实现 `/etc/users`，一般当前 `SuperBlock.users` 已足够。

