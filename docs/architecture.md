# 架构说明

本文档说明 Simple File System 的主要分层、磁盘布局和核心数据结构。

## 整体分层

```text
cli
  Shell、补全、批处理、编辑器、监控器、GUI

core
  文件系统核心 API、格式化、挂载、路径解析、权限检查、inode 缓存

storage
  磁盘块读写、对象序列化读写、inode 固定槽位读写

dataStruct
  超级块、目录块、inode、空闲块成组链接表、打开文件表项
```

命令行和 GUI 都尽量复用 `core.file_system.FileSystem`，这样路径解析、权限检查、读写语义和错误信息可以保持一致。

## 磁盘布局

磁盘参数定义在 `src/head.py`。

```text
磁盘大小：4MB
块大小：4096B
总块数：1024

block 0      超级块
block 1-128  inode 区
block 129+   数据区
```

inode 参数：

```text
inode 大小：256B
每块 inode 数：16
inode 区块数：128
inode 总数：2048
```

数据区参数：

```text
数据块数：895
数据区起始块：129
数据块 0 用作空闲块链尾标记，不作为普通数据块分配
```

## 持久化方式

### 块级 IO

`src/storage/disk.py` 负责磁盘镜像创建、打开、关闭和单块读写。所有读写最终都会落到固定大小的块上。

### 对象 IO

`src/storage/object_io.py` 使用 pickle 序列化对象，并在对象前写入 8 字节长度头。它适合保存超级块、目录块、间接块列表等完整对象。

### inode IO

`src/storage/inode_io.py` 将每个 inode 写入固定 256B 槽位。槽位前 2 字节保存序列化负载长度，剩余空间保存 inode 对象。

修改 inode 字段时要注意序列化后不能超过槽位容量。

## 核心数据结构

### SuperBlock

`SuperBlock` 保存文件系统全局状态：

- inode 总数和空闲 inode 数。
- 数据块总数和空闲数据块数。
- inode 位图。
- 空闲数据块成组链接表。
- 根目录 inode id。
- 用户表。

### Inode

`Inode` 保存文件或目录的元信息：

- inode id。
- owner id。
- mode 权限位。
- 文件大小。
- 是否为目录。
- 直接块列表。
- 一级间接块 id。
- 创建时间和修改时间。

### DirBlock

`DirBlock` 保存目录内容：

- 当前目录名。
- 当前目录 inode id。
- 父目录 inode id。
- 子文件映射。
- 子目录映射。

### InodeCache

`InodeCache` 管理运行时内存 inode 表：

- 引用计数。
- 脏标记。
- Hash 桶。
- 读写锁占用状态。

打开文件表项会持有对应 `MemoryInode`，关闭 fd 时释放引用和锁。

## 文件索引

普通文件使用直接块和一级间接块：

```text
direct_blocks       直接数据块
indirect_block      保存更多数据块 id 的索引块
```

当前直接块数量由 `DIRECT_CNT` 控制，一级间接块容量由块大小和对象序列化容量共同限制。

## 空闲块管理

数据块使用成组链接法管理。超级块中保存当前可分配块栈；当栈耗尽时，从组长块读取下一组空闲块信息。

这种设计适合演示传统文件系统中空闲块分组管理的思想。

## 用户与权限

当前项目使用简化权限模型：

```text
owner
others
mode
```

`chmod` 使用两位八进制写法，例如：

```text
70
75
64
60
```

判断规则：

```text
当前用户是 owner -> 使用 owner 位
当前用户不是 owner -> 使用 others 位
root 用户 -> 绕过普通权限检查
```

默认权限：

```text
普通文件：64
普通目录：75
用户 home 目录：70
```

## 设计边界

- 当前不实现 group。
- 用户表保存在超级块中，不使用 `/etc/passwd`。
- pickle 只用于本地教学模拟，不适合读取不可信磁盘镜像。
- 修改磁盘结构后建议重新格式化磁盘镜像。
