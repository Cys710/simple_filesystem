"""
    命令行交互层，解析用户输入的命令并调用 FileSystem 的方法实现功能。
    支持格式化磁盘、挂载磁盘、列出目录、创建目录和文件、切换目录等操作。
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Callable, TextIO

from head import DISK_NAME, GREEN, RESET
from core.file_system import FileSystem, FileSystemError
from utils import logo

# Shell 解析用户输入的命令并调用 FileSystem 的方法实现功能。
class Shell:

    def __init__(
        self,
        disk_path: str | Path = DISK_NAME,
        *,
        input_func: Callable[[str], str] = input,
        output: TextIO | None = None,
    ):
        self.disk_path = Path(disk_path)
        self.input_func = input_func
        self.output = output
        self.fs: FileSystem | None = None

    # run 启动交互式 shell，提示用户输入命令并执行，直到用户退出。
    def run(self) -> None:
        logo()
        self._println(f"disk: {self.disk_path}")
        self._println("type 'format' to create a fresh file system or 'mount' to load one")

        while True:
            try:
                # line = self.input_func(f"pfs:{self._pwd()}$ ")
                line = self.input_func(f"{GREEN}pfs:{self._pwd()}$ {RESET}")
            except (EOFError, KeyboardInterrupt):
                self._println()
                return

            should_continue = self.execute(line)
            if not should_continue:
                return

    # execute 解析并执行一行命令，返回 False 表示退出 shell。
    def execute(self, line: str) -> bool:

        try:
            argv = shlex.split(line)
        except ValueError as exc:
            self._println(f"error: {exc}")
            return True

        if not argv:
            return True

        cmd, *args = argv

        try:
            if cmd in {"exit", "quit"}:
                return False
            if cmd == "help":
                self._help()
            elif cmd == "format":
                self._format(args)
            elif cmd == "mount":
                self._mount(args)
            elif cmd == "ls":
                self._ls(args)
            elif cmd == "mkdir":
                self._mkdir(args)
            elif cmd == "touch":
                self._touch(args)
            elif cmd == "cd":
                self._cd(args)
            elif cmd == "pwd":
                self._pwd_command(args)
            elif cmd == "cat":
                self._cat(args)
            elif cmd == "open":
                self._open(args)
            elif cmd == "read":
                self._read(args)
            elif cmd == "write":
                self._write(args)
            elif cmd == "seek":
                self._seek(args)
            elif cmd == "close":
                self._close(args)
            elif cmd == "append":
                self._append(args)
            elif cmd == "rm":
                self._rm(args)
            elif cmd == "rmdir":
                self._rmdir(args)
            elif cmd in {"clear", "cls"}:
                self._clear(args)
            else:
                self._println(f"unknown command: {cmd}")
        except FileSystemError as exc:
            self._println(f"error: {exc}")
        except FileNotFoundError:
            self._println("error: disk image does not exist; run format first")

        return True

    # _format 格式化磁盘并挂载，参数可选指定磁盘路径。
    def _format(self, args: list[str]) -> None:
        self._expect_max_args(args, 1, "format [disk_path]")
        if args:
            self.disk_path = Path(args[0])
        self.fs = FileSystem.format_and_mount(self.disk_path)
        self._println(f"formatted and mounted {self.disk_path}")

    # _format 格式化磁盘并挂载，参数可选指定磁盘路径。
    def _mount(self, args: list[str]) -> None:
        self._expect_max_args(args, 1, "mount [disk_path]")
        if args:
            self.disk_path = Path(args[0])
        self.fs = FileSystem.mount(self.disk_path)
        self._println(f"mounted {self.disk_path}")

    # _ls 列出指定路径下的目录项，默认当前目录，输出格式为 name/（目录）或 name（文件）。
    def _ls(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_max_args(args, 1, "ls [path]")
        entries = self.fs.ls(args[0] if args else ".")
        if not entries:
            self._println()
            return

        names = []
        for name, type_id in entries:
            # suffix = "/" if type_id == 1 else ""
            # names.append(f"{name}{suffix}")
            names.append(name)
        self._println("  ".join(names))

    # _mkdir 在当前目录下创建一个新目录，参数为目录名。
    def _mkdir(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "mkdir name")
        self.fs.mkdir(args[0])

    # _touch 在当前目录下创建一个新文件，参数为文件名。
    def _touch(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "touch name")
        self.fs.touch(args[0])

    # _cd 切换当前目录，参数为目标路径。
    def _cd(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "cd path")
        self.fs.cd(args[0])

    # _clear 清屏命令，参数必须为空。
    def _clear(self, args: list[str]) -> None:
        self._expect_exact_args(args, 0, "clear")
        os.system("cls" if os.name == "nt" else "clear")

    # _pwd_command 输出当前目录的绝对路径，参数必须为空。
    def _pwd_command(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "pwd")
        self._println(self.fs.pwd())

    # _cat 输出指定文件的内容，参数为文件路径。
    def _cat(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "cat file")
        data = self.fs.read_file(args[0])
        self._println(data.decode("utf-8", errors="replace"))

    # _open 打开指定文件并返回文件描述符，参数为文件路径和可选的打开模式（默认为 "r"）。
    def _open(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 1, "open file [mode]")
        self._expect_max_args(args, 2, "open file [mode]")
        fd = self.fs.open(args[0], args[1] if len(args) == 2 else "r")
        self._println(str(fd))

    # _read 从指定文件描述符读取数据，参数为 fd 和可选的读取大小（默认为 -1，表示读取全部）。
    def _read(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 1, "read fd [size]")
        self._expect_max_args(args, 2, "read fd [size]")
        fd = self._parse_fd(args[0])
        size = int(args[1]) if len(args) == 2 else -1
        data = self.fs.read(fd, size)
        self._println(data.decode("utf-8", errors="replace"))

    # _write 向指定文件描述符或文件路径写入文本，参数为 fd 或 file 和要写入的文本。
    def _write(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 2, "write file text")
        if self._is_int(args[0]):
            self.fs.write(self._parse_fd(args[0]), " ".join(args[1:]))
        else:
            self.fs.write_file(args[0], " ".join(args[1:]))

    # _seek 在指定文件描述符上移动文件指针，参数为 fd、offset 和可选的 whence（默认为 0，表示从文件开头）。
    def _seek(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 2, "seek fd offset [whence]")
        self._expect_max_args(args, 3, "seek fd offset [whence]")
        whence = int(args[2]) if len(args) == 3 else 0
        offset = self.fs.seek(self._parse_fd(args[0]), int(args[1]), whence)
        self._println(str(offset))

    # _close 关闭指定文件描述符，参数为 fd。
    def _close(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "close fd")
        self.fs.close(self._parse_fd(args[0]))

    def _append(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 2, "append file text")
        self.fs.write_file(args[0], " ".join(args[1:]), append=True)

    def _rm(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "rm file")
        self.fs.remove(args[0])

    def _rmdir(self, args: list[str]) -> None:
        self._require_mount()
        recursive = False
        if args and args[0] in {"-r", "--recursive"}:
            recursive = True
            args = args[1:]
        self._expect_exact_args(args, 1, "rmdir [-r|--recursive] directory")
        self.fs.rmdir(args[0], recursive=recursive)

    # _require_mount 检查文件系统是否已挂载，如果没有则抛出错误。
    def _require_mount(self) -> None:
        if self.fs is None:
            raise FileSystemError("file system is not mounted")

    # _pwd 返回当前目录的绝对路径，如果文件系统未挂载则返回 "-"。
    def _pwd(self) -> str:
        return self.fs.pwd() if self.fs is not None else "-"

    def _parse_fd(self, text: str) -> int:
        try:
            return int(text)
        except ValueError as exc:
            raise FileSystemError(f"invalid fd: {text}") from exc

    def _is_int(self, text: str) -> bool:
        try:
            int(text)
        except ValueError:
            return False
        return True

    # _help 输出可用命令的帮助信息。
    def _help(self) -> None:
        self._println("commands: \n" \
        " format [disk]\n" \
        " mount [disk]\n" \
        " ls [path]\n" \
        " mkdir dir_name\n" \
        " touch file_name\n" \
        " cat file\n" \
        " open file [mode]\n" \
        " read fd [size]\n" \
        " write file text\n" \
        " write fd text\n" \
        " seek fd offset [whence]\n" \
        " close fd\n" \
        " append file text\n" \
        " rm file\n" \
        " rmdir [-r] directory\n" \
        " cd path\n" \
        " pwd\n" \
        " clear\n" \
        " exit")

    # _expect_exact_args 检查参数数量是否与预期完全匹配，否则抛出错误并显示用法。
    def _expect_exact_args(self, args: list[str], count: int, usage: str) -> None:
        if len(args) != count:
            raise FileSystemError(f"usage: {usage}")

    def _expect_min_args(self, args: list[str], count: int, usage: str) -> None:
        if len(args) < count:
            raise FileSystemError(f"usage: {usage}")

    # _expect_max_args 检查参数数量是否不超过预期，否则抛出错误并显示用法。
    def _expect_max_args(self, args: list[str], count: int, usage: str) -> None:
        if len(args) > count:
            raise FileSystemError(f"usage: {usage}")

    # _println 输出文本到指定输出流，默认为标准输出。
    def _println(self, text: str = "") -> None:
        print(text, file=self.output)

    # _print 输出文本但不换行，参数同 _println。
    def _print(self, text: str = "") -> None:
        print(text, end="", file=self.output)

def main() -> None:
    Shell().run()
