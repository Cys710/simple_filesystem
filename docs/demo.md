# 演示流程

本文档提供几组适合课程展示的操作流程。

## 基础启动

```text
format
login root
pwd
ls /
```

说明：

- `format` 会创建并初始化磁盘镜像。
- root 默认密码为 `123456`。
- 初始目录包含根目录下的基础结构。

## 文件持久化

```text
format
login root
touch /note.txt
write /note.txt hello
cat /note.txt
exit
```

重新启动后：

```text
mount
login root
cat /note.txt
```

预期可以看到：

```text
hello
```

## 文件描述符

```text
format
login root
touch /a.txt
open /a.txt w
write 3 hello
close 3
open /a.txt r
read 4
close 4
```

说明：

- fd 从 3 开始分配。
- 每个 fd 有独立的 offset。
- 写模式会获取写锁，读模式会获取共享读锁。

## 大文件和间接块

```text
format
login root
fill /big.bin
monitor
```

在 monitor 中可以切换到文件索引或块视图，观察直接块和一级间接块的使用情况。

也可以继续追加 1 字节，让文件跨过直接块边界：

```text
fill /big.bin 1
monitor
```

## 用户与权限

创建用户：

```text
format
login root
useradd alice
useradd bob
```

alice 创建私有文件：

```text
su alice
write private.txt secret
stat private.txt
```

bob 尝试访问：

```text
su bob
cat /home/alice/private.txt
```

预期结果：

```text
permission denied
```

开放只读访问：

```text
su alice
chmod 75 /home/alice
chmod 64 /home/alice/private.txt
su bob
cat /home/alice/private.txt
write /home/alice/private.txt x
```

预期：

- `cat` 可以读取。
- `write` 会因为没有写权限失败。

## 复制、移动和重命名

```text
format
login root
mkdir /docs
touch /a.txt
write /a.txt hello
cp /a.txt /docs
cat /docs/a.txt
mv /docs/a.txt /docs/b.txt
rename /docs/b.txt c.txt
tree /
```

预期目录中出现：

```text
/docs/c.txt
```

## 监控器演示

```text
format
login root
mkdir /docs
write /docs/a.txt hello
fill /docs/big.bin
monitor
```

monitor 中可用操作：

```text
1             inode 位图
2             空闲块成组链接
3             块占用图
4             文件索引
5             内存 inode 表
Tab           切换视图
q             退出 monitor
view block    切换到块视图
index /docs/big.bin
```

## GUI 演示

```text
format
login root
gui
```

GUI 中可以演示：

- 挂载和格式化。
- 新建文件夹。
- 新建、编辑、删除文件。
- 重命名。
- 查看属性。
- 登录、注销、切换用户。
- 搜索当前目录。
