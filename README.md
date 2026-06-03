# 东北大学OS课程设计 —— Simple File System

一个使用 Python 实现的教学型模拟文件系统。项目通过固定大小的磁盘镜像模拟类 Unix 文件系统的核心机制，支持格式化、挂载、目录树、文件读写、文件描述符、用户登录、权限控制、终端监控器和 Qt 图形界面等功能


## 软件开发环境

| 项目 | 内容 |
| --- | --- |
| 操作系统 | macOS / Linux / Windows |
| 语言 | Python 3 |
| 开发工具 | PyCharm / VS Code / Terminal |
| 交互终端 | prompt-toolkit |
| 图形界面 | PySide6 / Qt |
| 终端监控 | curses |
| 测试工具 | unittest |

## 功能完成情况

<table>
  <tr>
    <td width="48%" valign="top">
      <h3>基础功能</h3>
      <table>
        <tr>
          <th>序号</th>
          <th>命令</th>
          <th>对应功能</th>
          <th>完成情况</th>
        </tr>
        <tr><td>1</td><td><code>login</code></td><td>login</td><td>✅</td></tr>
        <tr><td>2</td><td><code>mkdir</code></td><td>mkdir</td><td>✅</td></tr>
        <tr><td>3</td><td><code>cd</code></td><td>chdir</td><td>✅</td></tr>
        <tr><td>4</td><td><code>ls</code></td><td>dir</td><td>✅</td></tr>
        <tr><td>5</td><td><code>touch</code></td><td>create</td><td>✅</td></tr>
        <tr><td>6</td><td><code>open</code></td><td>open</td><td>✅</td></tr>
        <tr><td>7</td><td><code>write</code></td><td>write</td><td>✅</td></tr>
        <tr><td>8</td><td><code>cat</code></td><td>read</td><td>✅</td></tr>
        <tr><td>9</td><td><code>close</code></td><td>close</td><td>✅</td></tr>
        <tr><td>10</td><td><code>rm</code></td><td>delete</td><td>✅</td></tr>
        <tr><td>11</td><td><code>logout</code></td><td>logout</td><td>✅</td></tr>
        <tr><td>12</td><td><code>rmdir</code></td><td>rmdir</td><td>✅</td></tr>
        <tr><td>13</td><td><code>format</code></td><td>format</td><td>✅</td></tr>
      </table>
    </td>
    <td width="4%"></td>
    <td width="48%" valign="top">
      <h3>拓展功能</h3>
      <table>
        <tr>
          <th>序号</th>
          <th>命令</th>
          <th>拓展功能</th>
          <th>完成情况</th>
        </tr>
        <tr><td>1</td><td><code>vim</code></td><td>编辑文件</td><td>✅</td></tr>
        <tr><td>2</td><td><code>cp</code></td><td>复制文件</td><td>✅</td></tr>
        <tr><td>3</td><td><code>mv</code></td><td>移动文件</td><td>✅</td></tr>
        <tr><td>4</td><td><code>rename</code></td><td>重命名</td><td>✅</td></tr>
        <tr><td>5</td><td><code>stat</code></td><td>文件状态</td><td>✅</td></tr>
        <tr><td>6</td><td><code>tree</code></td><td>目录结构</td><td>✅</td></tr>
        <tr><td>7</td><td><code>find</code></td><td>查找文件</td><td>✅</td></tr>
        <tr><td>8</td><td><code>ln</code></td><td>链接文件</td><td>✅</td></tr>
        <tr><td>9</td><td><code>pwd</code></td><td>打印目录</td><td>✅</td></tr>
        <tr><td>10</td><td><code>clear</code></td><td>清屏操作</td><td>✅</td></tr>
        <tr><td>11</td><td><code>help</code></td><td>帮助功能</td><td>✅</td></tr>
        <tr><td>12</td><td><code>chmod</code></td><td>权限修改</td><td>✅</td></tr>
        <tr><td>13</td><td><code>useradd</code></td><td>新增用户</td><td>✅</td></tr>
        <tr><td>14</td><td><code>passwd</code></td><td>修改密码</td><td>✅</td></tr>
        <tr><td>15</td><td><code>who</code></td><td>查看用户</td><td>✅</td></tr>
        <tr><td>16</td><td><code>su</code></td><td>切换用户</td><td>✅</td></tr>
        <tr><td>17</td><td><code>users</code></td><td>所有用户</td><td>✅</td></tr>
        <tr><td>18</td><td><code>Tab</code> 键</td><td>自动填充</td><td>✅</td></tr>
      </table>
    </td>
  </tr>
</table>

### 视图展示与 GUI

| 序号 | 展示内容 | 完成情况 |
| --- | --- | --- |
| 1 | 索引节点的 bitmap 可视化 ⭐ | ✅ |
| 2 | 成组链表法的可视化 ⭐ | ✅ |
| 3 | 磁盘数据块分配可视化 ⭐ | ✅ |
| 4 | 单一文件其索引节点直接索引和间接索引的查看可视化 | ✅ |
| 5 | `gui` 图形界面：文件管理、目录浏览、属性查看、用户操作 | ✅ |

## 主要数据结构（以文件系统为例）

| 数据结构 | 代码位置 | 说明 |
| --- | --- | --- |
| 文件物理结构 | `dataStruct/Inode.py` | 文件 inode 保存文件大小、直接索引块列表和一级间接索引块，实现直接索引 + 一级间接索引的文件物理结构。 |
| 目录结构 | `dataStruct/data.py` | `DirBlock` 使用 `son_files` 和 `son_dirs` 维护目录项，目录之间通过父 inode 和子目录 inode 构成树形目录结构。 |
| 空闲盘块组织结构 | `dataStruct/groupList.py` | 使用成组链接法管理空闲数据块，超级块中保存当前空闲块栈，组长块连接下一组空闲块。 |
| 超级块 | `dataStruct/data.py` | `SuperBlock` 保存 inode 数量、数据块数量、空闲 inode 位图、空闲数据块链、根目录 inode 和用户表。 |
| inode 位图 | `dataStruct/Inode.py` | `InodeBitmap` 用位图记录 inode 是否被占用，用于 inode 分配与回收。 |
| inode 固定槽位 | `storage/inode_io.py` | 每个 inode 固定占用 256B，通过 inode id 定位到 inode 区中的块号和槽位偏移。 |
| 打开文件表 | `dataStruct/open_file.py` | `OpenFile` 保存 fd、打开模式、文件偏移、读写权限和对应内存 inode。 |
| 内存 inode 表 | `core/inode_cache.py` | `InodeCache` 管理运行期 inode 副本，维护引用计数、脏标记和读写锁。 |
| 用户表 | `user.py` / `dataStruct/data.py` | 用户信息保存在超级块的 `users` 字典中，支持 root、普通用户、home 目录和密码校验。 |

## 功能特性

- 固定大小磁盘镜像，支持块级读写。
- 超级块、inode 区、数据区的模拟布局。
- inode 位图管理空闲 inode。
- 成组链接法管理空闲数据块。
- 支持目录、普通文件、硬链接和递归目录删除。
- 支持直接块和一级间接块文件索引。
- 支持文件描述符表：`open`、`read`、`write`、`seek`、`close`。
- 支持多用户登录、切换用户、修改密码和用户 home 目录。
- 支持简化版权限模型：owner / others。
- 支持命令补全、批处理脚本、内置编辑器、终端监控器和 GUI。

## 项目结构

```text
simple_filesystem/
├── .gitignore                # Git 忽略规则
├── README.md                 # 项目说明
├── requirements.txt          # Python 依赖
├── docs/
│   ├── architecture.md       # 架构与磁盘布局说明
│   ├── commands.md           # 命令说明
│   └── demo.md               # 演示流程
├── src/
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── completion.py     # 命令补全与路径补全
│   │   ├── editor.py         # 内置文本编辑器
│   │   ├── encoding.py       # 终端编码配置
│   │   ├── gui_mode.py       # PySide6 图形界面
│   │   ├── monitor.py        # curses 终端监控器
│   │   ├── prompt.py         # prompt-toolkit 交互输入
│   │   ├── shell.py          # Shell 命令解析与执行
│   │   └── visualizer.py     # 监控器文本渲染
│   ├── core/
│   │   ├── __init__.py
│   │   ├── debug_info.py     # 监控器只读调试快照
│   │   ├── file_system.py    # 文件系统核心 API
│   │   ├── format_disk.py    # 格式化磁盘镜像
│   │   ├── inode_cache.py    # 内存 inode 表与锁
│   │   └── mount.py          # 挂载磁盘镜像
│   ├── dataStruct/
│   │   ├── __init__.py
│   │   ├── block.py          # 块基类
│   │   ├── data.py           # SuperBlock 与 DirBlock
│   │   ├── groupList.py      # 空闲块成组链接表
│   │   ├── Inode.py          # inode 与 inode 位图
│   │   └── open_file.py      # 打开文件表项与模式解析
│   ├── figure/               #GUI 图标
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── disk.py           # 磁盘镜像与块级 IO
│   │   ├── inode_io.py       # inode 固定槽位 IO
│   │   └── object_io.py      # 对象序列化 IO
│   ├── head.py               # 全局常量
│   ├── main.py               # 程序入口
│   ├── user.py               # 用户模型
│   └── utils.py              # 辅助函数
└── test/                     # 数十个测试函数
```

## 设计说明

磁盘布局参数定义在 `src/head.py`：

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

## 环境要求

- Python 3.10+
- macOS / Linux / Windows
- 终端交互依赖 `prompt-toolkit`
- GUI 模式依赖 `PySide6`
- Windows 下 curses 监控器依赖 `windows-curses`

安装依赖：

```sh
python -m pip install -r requirements.txt
```

## 运行方法

进入项目目录：

```sh
cd simple_filesystem
```

启动交互式 shell：

```sh
python src/main.py
```

首次使用建议先格式化磁盘：

```text
format
login root
```

默认 root 账号：

```text
username: root
password: 123456
```

挂载已有磁盘镜像：

```text
mount
```

退出：

```text
exit
```

## 常用命令

### 磁盘与会话

| 命令 | 说明 |
| --- | --- |
| `format [disk]` | 格式化磁盘镜像 |
| `mount [disk]` | 挂载磁盘镜像 |
| `sync` | 写回脏 inode |
| `help` | 查看命令列表 |
| `exit` / `quit` | 退出 shell |

### 目录与文件

| 命令 | 说明 |
| --- | --- |
| `ls [path]` | 查看目录内容 |
| `mkdir dir_name` | 创建目录 |
| `touch file_name` | 创建文件 |
| `cd path` | 切换当前目录 |
| `pwd` | 查看当前路径 |
| `cat file` | 输出文件内容 |
| `write file text` | 写入文件 |
| `append file text` | 追加写入 |
| `rm file` | 删除文件 |
| `rmdir [-r] directory` | 删除目录 |
| `tree [path]` | 树形显示目录 |
| `find [path] pattern` | 查找文件或目录 |

### 文件描述符

| 命令 | 说明 |
| --- | --- |
| `open file [mode]` | 打开文件，返回 fd |
| `read fd [size]` | 从 fd 读取 |
| `write fd text` | 向 fd 写入 |
| `seek fd offset [whence]` | 移动文件偏移 |
| `close fd` | 关闭 fd |

### 文件操作

| 命令 | 说明 |
| --- | --- |
| `cp [-f] source destination` | 复制文件 |
| `mv [-f] source destination` | 移动文件 |
| `rename [-f] old_name new_name` | 重命名 |
| `ln source target` | 创建硬链接 |
| `vim file` | 使用内置编辑器编辑文件 |
| `bash script.sh` | 执行脚本文件 |

### 用户与权限

| 命令 | 说明 |
| --- | --- |
| `login username` | 登录用户 |
| `logout` | 登出 |
| `whoami` / `who` | 查看当前用户 |
| `useradd username` | 创建用户，仅 root 可用 |
| `passwd [username]` | 修改密码 |
| `users` | 查看用户列表，仅 root 可用 |
| `su username` | 切换用户 |
| `chmod mode path` | 修改权限 |
| `stat path` | 查看文件或目录元信息 |

完整命令说明见 [docs/commands.md](docs/commands.md)。

## 监控器

启动终端监控界面：

```text
monitor
```

监控器可以查看 inode 位图、空闲块成组链接、磁盘块占用图、文件索引结构和内存 inode 表。该功能需要交互式终端环境。

## 图形界面

启动 Qt 图形界面：

```text
gui
```

GUI 复用 shell 命令和 `FileSystem` 核心 API，因此权限、路径、错误信息与命令行保持一致。

Linux / WSL 环境中需要可用的图形显示环境，例如 WSLg 或已配置的 X Server。

## 测试

运行全部单元测试：

```sh
python -m unittest discover -s test
```

运行单个测试文件：

```sh
python -m unittest discover -s test -p 'test_file_commands.py'
```

更多架构说明见 [docs/architecture.md](docs/architecture.md)，演示流程见 [docs/demo.md](docs/demo.md)。
