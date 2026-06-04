"""
    命令行交互层，解析用户输入的命令并调用 FileSystem 的方法实现功能。
    支持格式化磁盘、挂载磁盘、列出目录、创建目录和文件、切换目录等操作。
"""

from __future__ import annotations

import difflib
import io
import os
import re
import shlex
from getpass import getpass
from pathlib import Path
from typing import Callable, TextIO

from head import DISK_NAME, GREEN, RESET
from core.file_system import FileSystem, FileSystemError
from cli.completion import CommandCompleter, SHELL_COMMANDS
from cli.encoding import configure_terminal_encoding
from utils import INDIRECT_INDEX_TEST_BYTES, append_test_data, logo

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
DIM = "\033[2m"
LOGIN_OPTIONAL_COMMANDS = {
    "bash",
    "exit",
    "quit",
    "help",
    "format",
    "mount",
    "login",
    "clear",
    "cls",
}

try:
    from cli.editor import VimEditor, VimEditorError
except ImportError:
    VimEditor = None

    class VimEditorError(Exception):
        pass

try:
    from cli.monitor import DiskMonitor, DiskMonitorError
except ImportError:
    DiskMonitor = None

    class DiskMonitorError(Exception):
        pass

try:
    from cli.gui_mode import FileSystemGui, FileSystemGuiError
except ImportError as exc:
    FileSystemGui = None
    GUI_IMPORT_ERROR = str(exc)

    class FileSystemGuiError(Exception):
        pass
else:
    GUI_IMPORT_ERROR = ""

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
        configure_terminal_encoding()
        self.disk_path = Path(disk_path)
        self.input_func = input_func
        self.password_func = password_func
        self.output = output
        self.fs: FileSystem | None = None
        self.completer = CommandCompleter(lambda: self.fs)
        self._prompt_reader = None
        self._last_command_failed = False
        self._script_stack: list[str] = []

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
                self._shutdown_fs()
                return

            should_continue = self.execute(line)
            if not should_continue:
                return

    # execute 解析并执行一行命令，返回 False 表示退出 shell。
    def execute(self, line: str) -> bool:
        self._last_command_failed = False
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
                self._shutdown_fs()
                return False
            if self.fs is not None and self.fs.current_user is None and cmd not in LOGIN_OPTIONAL_COMMANDS:
                raise FileSystemError("login required")
            if cmd == "help":
                self._help()
            elif cmd == "format":
                self._format(args)
            elif cmd == "mount":
                self._mount(args)
            elif cmd == "sync":
                self._sync(args)
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
            elif cmd == "tree":
                self._tree(args)
            elif cmd == "find":
                self._find(args)
            elif cmd == "ln":
                self._ln(args)
            elif cmd == "bash":
                self._bash(args)
            elif cmd == "cat":
                self._cat(args)
            elif cmd == "vim":
                self._vim(args)
            elif cmd == "monitor":
                self._monitor(args)
            elif cmd == "gui":
                self._gui(args)
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
                self._last_command_failed = True
                self._handle_unknown_command(cmd)
        except FileSystemError as exc:
            self._last_command_failed = True
            self._println(self._format_command_error(cmd, str(exc)))
        except VimEditorError as exc:
            self._last_command_failed = True
            self._println(self._format_command_error(cmd, str(exc)))
        except DiskMonitorError as exc:
            self._last_command_failed = True
            self._println(self._format_command_error(cmd, str(exc)))
        except FileSystemGuiError as exc:
            self._last_command_failed = True
            self._println(self._format_command_error(cmd, str(exc)))
        except FileNotFoundError as exc:
            self._last_command_failed = True
            self._println(self._format_os_error(cmd, exc))

        return True

    # _format 格式化磁盘并挂载，参数可选指定磁盘路径。
    def _format(self, args: list[str]) -> None:
        self._expect_max_args(args, 1, "format [disk_path]")
        if args:
            self.disk_path = Path(args[0])
        self._shutdown_fs()
        self.fs = FileSystem.format_and_mount(self.disk_path)
        self._println(f"formatted and mounted {self.disk_path}")

    # _format 格式化磁盘并挂载，参数可选指定磁盘路径。
    def _mount(self, args: list[str]) -> None:
        self._expect_max_args(args, 1, "mount [disk_path]")
        if args:
            self.disk_path = Path(args[0])
        if not self.disk_path.exists():
            raise FileNotFoundError(str(self.disk_path))
        self.fs = FileSystem.mount(self.disk_path)
        self._println(f"mounted {self.disk_path}")

    # _sync 将内存 inode 表中的脏 inode 主动写回磁盘
    def _sync(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "sync")
        self.fs.sync()
        self._println("synced")

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

        if self.fs.current_user is not None:
            raise FileSystemError("already logged in, use 'su' to switch user")

        password = self._read_password("Password: ")
        self.fs.login(args[0], password)
        home_path = self.fs.current_user.home_path if self.fs.current_user is not None else None
        if home_path:
            try:
                self.fs.cd(home_path)
            except FileSystemError:
                pass
        self._println(f"logged in as {self.fs.whoami()}")

    # _logout 注销当前用户，参数必须为空。
    def _logout(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "logout")
        old_user = self.fs.whoami()
        self.fs.logout()
        self.fs.cd("/")
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

    def _tree(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_max_args(args, 1, "tree [path]")
        for line in self.fs.tree(args[0] if args else "."):
            self._println(line)

    def _find(self, args: list[str]) -> None:
        self._require_mount()
        if len(args) == 1:
            path = "."
            pattern = args[0]
        elif len(args) == 2:
            path, pattern = args
        else:
            raise FileSystemError("usage: find [path] pattern")

        for line in self.fs.find(pattern, path):
            self._println(line)

    def _ln(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 2, "ln source target")
        self.fs.link(args[0], args[1])

    def _bash(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "bash script.sh")
        script_path = self._resolve_bash_script_path(args[0])
        if script_path in self._script_stack:
            raise FileSystemError(f"recursive script include detected: {script_path}")

        inode, _dir_block = self.fs._resolve_path(script_path)
        if inode.is_dir:
            raise FileSystemError(f"is a directory: {script_path}")
        script_text = self.fs.read_file(script_path).decode("utf-8", errors="replace")
        commands = self._parse_script_commands(script_path, script_text)

        self._script_stack.append(script_path)
        try:
            for start_line, end_line, command in commands:
                line_ref = self._script_line_ref(script_path, start_line, end_line)
                self._println(f"[bash:{line_ref}]$ {command}")
                should_continue, output, failed = self._execute_capture(command)
                if failed:
                    self._println(f"bash: {line_ref}")
                if output:
                    self._println(output)
                if not should_continue:
                    self._println(f"bash: script stopped by exit at {line_ref}")
                    break
        finally:
            self._script_stack.pop()

    # _cat 输出指定文件的内容，参数为文件路径。
    def _cat(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "cat file")
        data = self.fs.read_file(args[0])
        self._println(data.decode("utf-8", errors="replace"))

    def _vim(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 1, "vim file")
        if VimEditor is None:
            raise FileSystemError("vim is unavailable in this environment")
        VimEditor(self.fs, args[0]).run()

    def _monitor(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "monitor")
        if DiskMonitor is None:
            raise FileSystemError("monitor is unavailable in this environment")
        DiskMonitor(
            self.fs,
            command_executor=self._execute_monitor_command,
        ).run()

    def _gui(self, args: list[str]) -> None:
        self._require_mount()
        self._expect_exact_args(args, 0, "gui")
        if self.fs.current_user is None:
            raise FileSystemError("login required")
        if FileSystemGui is None:
            detail = f": {GUI_IMPORT_ERROR}" if GUI_IMPORT_ERROR else ""
            raise FileSystemError(f"gui is unavailable in this environment{detail}")
        FileSystemGui(
            lambda: self.fs,
            self._execute_gui_command,
            disk_path_getter=lambda: self.disk_path,
            command_logger=self._log_gui_command,
            error_formatter=self._format_command_error,
        ).run()

    def _execute_monitor_command(self, command: str) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"error: {exc}"
        if not argv:
            return ""
        if argv[0] in {"format", "mount", "monitor", "gui", "vim", "clear", "cls"}:
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

    def _execute_gui_command(self, command: str) -> tuple[bool, str]:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return False, f"error: {exc}"
        if not argv:
            return True, ""
        if argv[0] in {"gui", "monitor", "vim", "clear", "cls", "exit", "quit"}:
            return False, f"error: {argv[0]} is unavailable inside gui"

        self._log_gui_command(command)
        should_continue, output, failed = self._execute_capture(command)
        if output:
            self._println(output)
        if not should_continue:
            return False, "Close the graphical window to leave gui mode."
        return not failed, output

    def _log_gui_command(self, command: str) -> None:
        self._println(f"[gui]$ {command}")

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

    # _shutdown_fs 在切换挂载或退出前关闭 fd 并写回缓存
    def _shutdown_fs(self) -> None:
        if self.fs is not None:
            self.fs.shutdown()
            self.fs = None

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
        sections = [
            ("System", [
                "format [disk]",
                "mount [disk]",
                "bash script.sh",
                "exit",
            ]),
            ("Directory", [
                "ls [path]",
                "mkdir dir_name",
                "rmdir [-r] directory",
                "cd path",
                "pwd",
                "tree [path]",
                "find [path] pattern",
            ]),
            ("File", [
                "touch file_name",
                "cat file",
                "vim file",
                "cp [-f] source destination",
                "mv [-f] source destination",
                "rename [-f] old_name new_name",
                "rm file",
                "ln source target",
                "stat path",
                "fill file [bytes]",
            ]),
            ("Open File", [
                "open file [mode]",
                "read fd [size]",
                "write file text",
                "write fd text",
                "append file text",
                "seek fd offset [whence]",
                "close fd",
            ]),
            ("User", [
                "login username",
                "logout",
                "whoami",
                "who",
                "useradd username",
                "passwd [username]",
                "users",
                "su username",
                "chmod mode path",
            ]),
            ("View", [
                "monitor",
                "gui",
                "clear",
            ]),
        ]

        self._println(f"{CYAN}Available commands{RESET}")
        for title, commands in sections:
            self._println(f"\n{YELLOW}{title}{RESET}")
            for command in commands:
                self._println(f"  {self._format_help_command(command)}")
        return

    # _expect_exact_args 检查参数数量是否与预期完全匹配，否则抛出错误并显示用法。
    def _format_help_command(self, usage: str) -> str:
        command, _, args = usage.partition(" ")
        if not args:
            return f"{GREEN}{command}{RESET}"
        return f"{GREEN}{command}{RESET} {DIM}{args}{RESET}"

    def _expect_exact_args(self, args: list[str], count: int, usage: str) -> None:
        if len(args) != count:
            raise FileSystemError(f"Parameternotmatch: {usage}")

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

    def _execute_capture(self, line: str) -> tuple[bool, str, bool]:
        try:
            argv = shlex.split(line)
        except ValueError:
            argv = []
        if argv and argv[0] in {"exit", "quit"}:
            self._last_command_failed = False
            return False, "", False

        old_output = self.output
        captured = io.StringIO()
        self.output = captured
        try:
            should_continue = self.execute(line)
        finally:
            self.output = old_output
        return (
            should_continue,
            ANSI_ESCAPE_RE.sub("", captured.getvalue()).strip(),
            self._last_command_failed,
        )

    def _resolve_bash_script_path(self, path: str) -> str:
        if self.fs is None:
            raise FileSystemError("file system is not mounted")
        if self._script_stack and not path.startswith("/"):
            parent_dir = self._script_stack[-1].rsplit("/", 1)[0]
            if not parent_dir:
                parent_dir = "/"
            path = f"{parent_dir}/{path}" if parent_dir != "/" else f"/{path}"
        return self.fs._normalize_path(path)

    def _parse_script_commands(
        self,
        script_path: str,
        script_text: str,
    ) -> list[tuple[int, int, str]]:
        parsed_lines: list[tuple[int, list[str]]] = []
        for line_no, raw_line in enumerate(script_text.splitlines(), start=1):
            tokens = self._script_line_tokens(script_path, line_no, raw_line)
            if tokens:
                parsed_lines.append((line_no, tokens))

        commands: list[tuple[int, int, str]] = []
        pending_tokens: list[str] = []
        start_line: int | None = None
        end_line: int | None = None

        for index, (line_no, tokens) in enumerate(parsed_lines):
            if not pending_tokens:
                pending_tokens = list(tokens)
                start_line = line_no
            else:
                pending_tokens.extend(tokens)
            end_line = line_no

            status = self._script_command_status(pending_tokens)
            next_first_token = None
            if index + 1 < len(parsed_lines):
                next_first_token = parsed_lines[index + 1][1][0]

            should_finalize = status in {"invalid", "unknown"}
            if status == "complete" and (
                next_first_token is None or next_first_token in SHELL_COMMANDS
            ):
                should_finalize = True

            if should_finalize:
                commands.append((start_line, end_line, shlex.join(pending_tokens)))
                pending_tokens = []
                start_line = None
                end_line = None

        if pending_tokens:
            commands.append((start_line, end_line, shlex.join(pending_tokens)))

        return commands

    def _script_line_tokens(self, script_path: str, line_no: int, raw_line: str) -> list[str]:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            return []
        try:
            return shlex.split(raw_line, comments=True)
        except ValueError as exc:
            raise FileSystemError(
                f"invalid script syntax in {script_path}:{line_no}: {exc}"
            ) from exc

    def _script_command_status(self, tokens: list[str]) -> str:
        command = tokens[0]
        arg_count = len(tokens) - 1
        if command not in SHELL_COMMANDS:
            return "unknown"

        if command in {
            "help",
            "logout",
            "who",
            "whoami",
            "users",
            "monitor",
            "gui",
            "pwd",
            "clear",
            "cls",
            "exit",
            "quit",
        }:
            return self._status_for_fixed_range(arg_count, 0, 0)
        if command in {"format", "mount", "ls", "passwd", "tree"}:
            return self._status_for_fixed_range(arg_count, 0, 1)
        if command in {
            "mkdir",
            "touch",
            "cd",
            "login",
            "useradd",
            "su",
            "stat",
            "cat",
            "vim",
            "rm",
            "bash",
        }:
            return self._status_for_fixed_range(arg_count, 1, 1)
        if command in {"chmod", "ln"}:
            return self._status_for_fixed_range(arg_count, 2, 2)
        if command in {"find", "open", "read", "fill"}:
            return self._status_for_fixed_range(arg_count, 1, 2)
        if command == "seek":
            return self._status_for_fixed_range(arg_count, 2, 3)
        if command == "rmdir":
            if arg_count == 0:
                return "incomplete"
            if arg_count == 1 and tokens[1] in {"-r", "--recursive"}:
                return "incomplete"
            return self._status_for_fixed_range(arg_count, 1, 2)
        if command in {"write", "append"}:
            return "complete" if arg_count >= 2 else "incomplete"
        return "unknown"

    def _status_for_fixed_range(self, arg_count: int, min_args: int, max_args: int) -> str:
        if arg_count < min_args:
            return "incomplete"
        if arg_count > max_args:
            return "invalid"
        return "complete"

    def _script_line_ref(self, script_path: str, start_line: int, end_line: int) -> str:
        if start_line == end_line:
            return f"{script_path}:{start_line}"
        return f"{script_path}:{start_line}-{end_line}"

    def _handle_unknown_command(self, cmd: str) -> None:
        self._println(f"{cmd}: command not found")
        suggestion = self._suggest_command(cmd)
        if suggestion is not None:
            self._println(f"Did you mean '{suggestion}'?")

    def _suggest_command(self, cmd: str) -> str | None:
        matches = difflib.get_close_matches(cmd, SHELL_COMMANDS, n=1, cutoff=0.55)
        return matches[0] if matches else None

    def _format_command_error(self, cmd: str, message: str) -> str:
        if message.startswith("Parameternotmatch: "):
            return f"{cmd}: {message}"
        if message.startswith("usage: "):
            return f"{cmd}: {message}"
        if message == "login required":
            return f"{cmd}: login required. Please run 'login <username>' first."
        if message == "file system is not mounted":
            return f"{cmd}: no file system mounted. Please run 'mount' or 'format' first."
        if message == "invalid username or password":
            return f"{cmd}: authentication failed"
        if message == "permission denied":
            return f"{cmd}: permission denied"
        if message == "operation cancelled":
            return f"{cmd}: operation cancelled"
        if message == "passwords do not match":
            return f"{cmd}: passwords do not match"
        if message == "password cannot be empty":
            return f"{cmd}: password cannot be empty"
        if message == "monitor is unavailable in this environment":
            return f"{cmd}: monitor is unavailable in this environment"
        if message.startswith("gui is unavailable in this environment"):
            return (
                f"{cmd}: {message}. Install dependencies with "
                "'python -m pip install -r requirements.txt'. On WSL, also run "
                "under WSLg or configure an X server/DISPLAY."
            )
        if message.startswith("gui requires a graphical display"):
            return f"{cmd}: {message}"
        if message.startswith("recursive script include detected: "):
            return f"{cmd}: recursive script include detected: {message.removeprefix('recursive script include detected: ')}"
        if message.startswith("invalid script syntax in "):
            return f"{cmd}: {message}"
        if message.startswith("path not found: "):
            return f"{cmd}: no such file or directory: {message.removeprefix('path not found: ')}"
        if message.startswith("file not found: "):
            return f"{cmd}: no such file: {message.removeprefix('file not found: ')}"
        if message.startswith("directory not found: "):
            return f"{cmd}: no such directory: {message.removeprefix('directory not found: ')}"
        if message.startswith("user not found: "):
            return f"{cmd}: user not found: {message.removeprefix('user not found: ')}"
        if message.startswith("user already exists: "):
            return f"{cmd}: user already exists: {message.removeprefix('user already exists: ')}"
        if message.startswith("name already exists: "):
            return f"{cmd}: file exists: {message.removeprefix('name already exists: ')}"
        if message.startswith("invalid fd: "):
            return f"{cmd}: invalid file descriptor: {message.removeprefix('invalid fd: ')}"
        if message.startswith("invalid file descriptor: "):
            return f"{cmd}: bad file descriptor: {message.removeprefix('invalid file descriptor: ')}"
        if message.startswith("file descriptor is not readable: "):
            return (
                f"{cmd}: bad file descriptor (not opened for reading): "
                f"{message.removeprefix('file descriptor is not readable: ')}"
            )
        if message.startswith("file descriptor is not writable: "):
            return (
                f"{cmd}: bad file descriptor (not opened for writing): "
                f"{message.removeprefix('file descriptor is not writable: ')}"
            )
        if message.startswith("invalid mode: "):
            return f"{cmd}: invalid mode: {message.removeprefix('invalid mode: ')}"
        if message.startswith("is a directory: "):
            return f"{cmd}: is a directory: {message.removeprefix('is a directory: ')}"
        if message.startswith("not a directory: "):
            return f"{cmd}: not a directory: {message.removeprefix('not a directory: ')}"
        if message.startswith("directory is not empty: "):
            return (
                f"{cmd}: directory not empty: "
                f"{message.removeprefix('directory is not empty: ')}"
            )
        if message == "cannot remove root directory":
            return f"{cmd}: cannot remove '/': operation not permitted"
        if message.startswith("invalid whence: "):
            return f"{cmd}: invalid whence value: {message.removeprefix('invalid whence: ')}"
        if message.startswith("read size cannot be less than -1"):
            return f"{cmd}: invalid read size"
        return f"{cmd}: {message}"

    def _format_os_error(self, cmd: str, exc: FileNotFoundError) -> str:
        raw_path = exc.filename or str(self.disk_path)
        if cmd == "mount":
            return f"mount: disk image not found: {Path(raw_path)}"
        if cmd == "bash":
            return f"bash: script not found: {raw_path}"
        if cmd == "format":
            return f"format: target path not found: {Path(raw_path).parent}"
        return f"{cmd}: no such file or directory: {raw_path}"

def main() -> None:
    Shell().run()
