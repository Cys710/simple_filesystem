"""
    命令行交互层，解析用户输入的命令并调用 FileSystem 的方法实现功能。
    支持格式化磁盘、挂载磁盘、列出目录、创建目录和文件、切换目录等操作。
"""

from __future__ import annotations

import io
import os
import re
import shlex
from getpass import getpass
from pathlib import Path
from typing import Callable, TextIO

from head import DISK_NAME, GREEN, RESET
from core.file_system import FileSystem, FileSystemError
from cli.completion import CommandCompleter
from cli.editor import VimEditor, VimEditorError
from cli.monitor import DiskMonitor, DiskMonitorError
from utils import INDIRECT_INDEX_TEST_BYTES, append_test_data, logo

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Shell 解析用户输入的命令并调用 FileSystem 的方法实现功能。
class Shell:

    def __init__(
        self,
        disk_path: str | Path = DISK_NAME,
        *,
        input_func: Callable[[str], str] = input,
        password_func: Callable[[str], str] = getpass,
        output: TextIO | None = None,
    ):
        self.disk_path = Path(disk_path)
        self.input_func = input_func
        self.password_func = password_func
        self.output = output
        self.fs: FileSystem | None = None
        self.completer = CommandCompleter(lambda: self.fs)
        self._prompt_reader = None

    # run 启动交互式 shell，提示用户输入命令并执行，直到用户退出。
    def run(self) -> None:
        logo()
        self._println(f"disk: {self.disk_path}")
        self._println("type 'format' to create a fresh file system or 'mount' to load one")

        while True:
            try:
                line = self._read_command(f"{GREEN}pfs:{self._pwd()}$ {RESET}")
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
            elif cmd == "login":
                self._login(args)
            elif cmd == "logout":
                self._logout(args)
            elif cmd in {"who", "whoami"}:
                self._whoami(args)
            elif cmd == "useradd":
                self._useradd(args)
            elif cmd == "passwd":
                self._passwd(args)
            elif cmd == "users":
                self._users(args)
            elif cmd == "su":
                self._su(args)
            elif cmd == "chmod":
                self._chmod(args)
            elif cmd == "stat":
                self._stat(args)
            elif cmd == "cat":
                self._cat(args)
            elif cmd == "vim":
                self._vim(args)
            elif cmd == "monitor":
                self._monitor(args)
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
            elif cmd == "fill":
                self._fill(args)
            elif cmd == "cp":
                self._cp(args)
            elif cmd == "mv":
                self._mv(args)
            elif cmd in {"rename", "rname"}:
                self._rename(args)
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
        except VimEditorError as exc:
            self._println(f"error: {exc}")
        except DiskMonitorError as exc:
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

    # _login 登录用户，参数为用户名和密码。
    def _login(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "login username")
        password = self._read_password("Password: ")
        self.fs.login(args[0], password)
        self._println(f"logged in as {self.fs.whoami()}")

    # _logout 注销当前用户，参数必须为空。
    def _logout(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "logout")
        old_user = self.fs.whoami()
        self.fs.logout()
        self._println(f"logged out {old_user}")

    # _whoami 输出当前登录的用户名，参数必须为空。
    def _whoami(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "whoami")
        self._println(self.fs.whoami())

    def _useradd(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "useradd username")
        password = self._read_new_password()
        user_id = self.fs.useradd(args[0], password)
        self._println(f"created user {args[0]} ({user_id})")

    def _passwd(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_max_args(args, 1, "passwd [username]")
        username = args[0] if args else self.fs.whoami()
        if username == "guest":
            raise FileSystemError("login required")
        password = self._read_new_password()
        self.fs.passwd(username, password)
        self._println(f"password updated for {username}")

    def _users(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "users")
        self._println("  ".join(self.fs.users()))

    def _su(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "su username")
        password = self._read_password("Password: ")
        self.fs.su(args[0], password)
        self._println(f"switched to {self.fs.whoami()}")

    def _chmod(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 2, "chmod mode path")
        self.fs.chmod(args[1], args[0])

    def _stat(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "stat path")
        info = self.fs.stat(args[0])
        self._println(
            f"{info['type']} inode={info['inode_id']} "
            f"owner={info['owner_id']} mode={info['mode']} size={info['size']}"
        )

    # _cat 输出指定文件的内容，参数为文件路径。
    def _cat(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "cat file")
        data = self.fs.read_file(args[0])
        self._println(data.decode("utf-8", errors="replace"))

    def _vim(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "vim file")
        VimEditor(self.fs, args[0]).run()

    def _monitor(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "monitor")
        DiskMonitor(
            self.fs,
            command_executor=self._execute_monitor_command,
        ).run()

    def _execute_monitor_command(self, command: str) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"error: {exc}"
        if not argv:
            return ""
        if argv[0] in {"format", "mount", "monitor", "vim", "clear", "cls"}:
            return f"error: {argv[0]} is unavailable inside monitor"

        old_output = self.output
        captured = io.StringIO()
        self.output = captured
        try:
            should_continue = self.execute(command)
        finally:
            self.output = old_output

        if not should_continue:
            return "Press q on an empty command line to leave monitor."
        return ANSI_ESCAPE_RE.sub("", captured.getvalue()).strip()

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

    def _fill(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_min_args(args, 1, "fill file [bytes]")
        self._expect_max_args(args, 2, "fill file [bytes]")
        try:
            byte_count = int(args[1]) if len(args) == 2 else INDIRECT_INDEX_TEST_BYTES
            written = append_test_data(self.fs, args[0], byte_count)
        except ValueError as exc:
            raise FileSystemError(str(exc)) from exc
        self._println(f"appended {written} bytes to {args[0]}")

    def _cp(self, args: list[str]) -> None:
        self._require_mount()
        if len(args) < 2 or len(args) > 3:
            raise FileSystemError("usage: cp [-f] source destination")
        
        overwrite = False
        if args[0] == "-f":
            overwrite = True
            args = args[1:]
        
        if len(args) != 2:
            raise FileSystemError("usage: cp [-f] source destination")
        
        self.fs.cp(args[0], args[1], overwrite=overwrite)
        self._println(f"copied {args[0]} to {args[1]}")

    def _mv(self, args: list[str]) -> None:
        self._require_mount()
        if len(args) < 2 or len(args) > 3:
            raise FileSystemError("usage: mv [-f] source destination")
        
        overwrite = False
        if args[0] == "-f":
            overwrite = True
            args = args[1:]
        
        if len(args) != 2:
            raise FileSystemError("usage: mv [-f] source destination")
        
        self.fs.mv(args[0], args[1], overwrite=overwrite)
        self._println(f"moved {args[0]} to {args[1]}")

    def _rename(self, args: list[str]) -> None:
        self._require_mount()
        if len(args) < 2 or len(args) > 3:
            raise FileSystemError("usage: rename [-f] old_name new_name")

        overwrite = False
        if args[0] == "-f":
            overwrite = True
            args = args[1:]

        if len(args) != 2:
            raise FileSystemError("usage: rename [-f] old_name new_name")

        self.fs.rename(args[0], args[1], overwrite=overwrite)
        self._println(f"renamed {args[0]} to {args[1]}")

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

    def _read_password(self, prompt: str) -> str:
        return self.password_func(prompt)

    def _read_new_password(self) -> str:
        password = self._read_password("New password: ")
        confirm = self._read_password("Retype new password: ")
        if password != confirm:
            raise FileSystemError("passwords do not match")
        if not password:
            raise FileSystemError("password cannot be empty")
        return password

    def _read_command(self, prompt: str) -> str:
        if self.input_func is not input:
            return self.input_func(prompt)
        if self._prompt_reader is None:
            try:
                from cli.prompt import PromptReader
            except ImportError as exc:
                raise RuntimeError(
                    "prompt-toolkit is required for the interactive shell; "
                    "install it with 'python -m pip install -r requirements.txt'"
                ) from exc
            self._prompt_reader = PromptReader(self.completer)
        return self._prompt_reader.read(prompt)

    # _help 输出可用命令的帮助信息。
    def _help(self) -> None:
        self._println("commands: \n" \
        " format [disk]\n" \
        " mount [disk]\n" \
        " ls [path]\n" \
        " mkdir dir_name\n" \
        " touch file_name\n" \
        " login username\n" \
        " logout\n" \
        " whoami\n" \
        " who\n" \
        " useradd username\n" \
        " passwd [username]\n" \
        " users\n" \
        " su username\n" \
        " chmod mode path\n" \
        " stat path\n" \
        " cat file\n" \
        " vim file\n" \
        " monitor\n" \
        " open file [mode]\n" \
        " read fd [size]\n" \
        " write file text\n" \
        " write fd text\n" \
        " seek fd offset [whence]\n" \
        " close fd\n" \
        " append file text\n" \
        " fill file [bytes]\n" \
        " cp [-f] source destination\n" \
        " mv [-f] source destination\n" \
        " rename [-f] old_name new_name\n" \
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
