"""
    curses based full-screen editor used by the shell's vim command.
"""

from __future__ import annotations

import curses
import sys
from dataclasses import dataclass

from core.file_system import FileSystem, FileSystemError


NORMAL = "NORMAL"
"""
方向键 或 h/j/k/l 移动
i 进入插入模式
a 光标后移一格再进入插入模式?
o 在下方开新行
O 在上方开新行
x 删除字符
d 删除整行
: 进入命令模式
Ctrl-S 保存
"""

INSERT = "INSERT"
"""
普通可打印字符会插入文本
Enter 换行
Backspace 删除
方向键移动
Esc 回到普通模式
"""

COMMAND = "COMMAND"
"""
:w 保存
:q 退出，如果有未保存修改会阻止
:q! 强制退出
:wq 或 :x 保存并退出
:数字 跳转到指定行
"""

ESCAPE_KEY_SEQUENCES = {
    "\x1b[A": curses.KEY_UP,
    "\x1b[B": curses.KEY_DOWN,
    "\x1b[C": curses.KEY_RIGHT,
    "\x1b[D": curses.KEY_LEFT,
    "\x1bOA": curses.KEY_UP,
    "\x1bOB": curses.KEY_DOWN,
    "\x1bOC": curses.KEY_RIGHT,
    "\x1bOD": curses.KEY_LEFT,
}

WINDOWS_SPECIAL_KEY_SEQUENCES = {
    "H": curses.KEY_UP,
    "P": curses.KEY_DOWN,
    "M": curses.KEY_RIGHT,
    "K": curses.KEY_LEFT,
}


class VimEditorError(Exception):
    pass


@dataclass
class TextBuffer:
    lines: list[str]
    cursor_y: int = 0
    cursor_x: int = 0
    modified: bool = False

    # 从完整文本创建按行存储的文本缓冲区。
    @classmethod
    def from_text(cls, text: str) -> "TextBuffer":
        lines = text.split("\n")
        if not lines:
            lines = [""]
        return cls(lines=lines)

    # 将缓冲区内容重新拼接成完整文本。
    def to_text(self) -> str:
        return "\n".join(self.lines)

    # 返回光标当前所在行的文本。
    @property
    def current_line(self) -> str:
        return self.lines[self.cursor_y]

    # 将光标限制在现有行列范围内。
    def clamp_cursor(self) -> None:
        self.cursor_y = min(max(self.cursor_y, 0), len(self.lines) - 1)
        self.cursor_x = min(max(self.cursor_x, 0), len(self.current_line))

    # 将光标向左移动，必要时跳到上一行末尾。
    def move_left(self) -> None:
        if self.cursor_x > 0:
            self.cursor_x -= 1
        elif self.cursor_y > 0:
            self.cursor_y -= 1
            self.cursor_x = len(self.current_line)

    # 将光标向右移动，必要时跳到下一行开头。
    def move_right(self) -> None:
        if self.cursor_x < len(self.current_line):
            self.cursor_x += 1
        elif self.cursor_y < len(self.lines) - 1:
            self.cursor_y += 1
            self.cursor_x = 0

    # 将光标向上移动并保持列位置有效。
    def move_up(self) -> None:
        if self.cursor_y > 0:
            self.cursor_y -= 1
            self.clamp_cursor()

    # 将光标向下移动并保持列位置有效。
    def move_down(self) -> None:
        if self.cursor_y < len(self.lines) - 1:
            self.cursor_y += 1
            self.clamp_cursor()

    # 在当前光标位置插入一个字符。
    def insert_char(self, char: str) -> None:
        line = self.current_line
        self.lines[self.cursor_y] = line[: self.cursor_x] + char + line[self.cursor_x :]
        self.cursor_x += len(char)
        self.modified = True

    # 在当前光标位置拆分当前行并插入新行。
    def insert_newline(self) -> None:
        line = self.current_line
        before = line[: self.cursor_x]
        after = line[self.cursor_x :]
        self.lines[self.cursor_y] = before
        self.lines.insert(self.cursor_y + 1, after)
        self.cursor_y += 1
        self.cursor_x = 0
        self.modified = True

    # 在当前行下方创建一个空行并移动光标。
    def open_line_below(self) -> None:
        self.cursor_y += 1
        self.lines.insert(self.cursor_y, "")
        self.cursor_x = 0
        self.modified = True

    # 在当前行上方创建一个空行并移动光标。
    def open_line_above(self) -> None:
        self.lines.insert(self.cursor_y, "")
        self.cursor_x = 0
        self.modified = True

    # 删除光标左侧字符，行首时合并到上一行。
    def backspace(self) -> None:
        if self.cursor_x > 0:
            line = self.current_line
            self.lines[self.cursor_y] = line[: self.cursor_x - 1] + line[self.cursor_x :]
            self.cursor_x -= 1
            self.modified = True
            return

        if self.cursor_y == 0:
            return

        previous_len = len(self.lines[self.cursor_y - 1])
        self.lines[self.cursor_y - 1] += self.current_line
        del self.lines[self.cursor_y]
        self.cursor_y -= 1
        self.cursor_x = previous_len
        self.modified = True

    # 删除光标处字符，行尾时合并下一行。
    def delete_char(self) -> None:
        line = self.current_line
        if self.cursor_x < len(line):
            self.lines[self.cursor_y] = line[: self.cursor_x] + line[self.cursor_x + 1 :]
            self.modified = True
            return

        if self.cursor_y < len(self.lines) - 1:
            self.lines[self.cursor_y] += self.lines[self.cursor_y + 1]
            del self.lines[self.cursor_y + 1]
            self.modified = True

    # 删除当前行并修正光标位置。
    def delete_line(self) -> None:
        if len(self.lines) == 1:
            self.lines[0] = ""
            self.cursor_x = 0
        else:
            del self.lines[self.cursor_y]
            self.clamp_cursor()
        self.modified = True

    # 跳转到指定行号并修正光标位置。
    def goto_line(self, line_number: int) -> None:
        if line_number < 1:
            line_number = 1
        self.cursor_y = min(line_number - 1, len(self.lines) - 1)
        self.clamp_cursor()


class VimEditor:
    # 初始化编辑器状态并绑定文件系统路径。
    def __init__(self, fs: FileSystem, path: str):
        self.fs = fs
        self.path = path
        self.buffer = TextBuffer.from_text("")
        self.file_exists = True
        self.mode = NORMAL
        self.command = ""
        self.message = ""
        self.row_offset = 0
        self.col_offset = 0
        self.running = True
        self.text_height = 1
        self.screen_width = 1

    # 从文件系统读取文件内容到文本缓冲区。
    def load(self) -> None:
        try:
            data = self.fs.read_file(self.path)
        except FileSystemError as exc:
            if "path not found" not in str(exc) and "file not found" not in str(exc):
                raise
            self.file_exists = False
            self.buffer = TextBuffer.from_text("")
            self.message = f'"{self.path}" [New File]'
            return

        text = data.decode("utf-8", errors="replace")
        self.file_exists = True
        self.buffer = TextBuffer.from_text(text)
        self.buffer.modified = False
        self.message = f'"{self.path}" {len(data)} bytes'

    # 将文本缓冲区内容写回文件系统。
    def save(self) -> None:
        if not self.file_exists:
            self.fs.touch(self.path)
            self.file_exists = True

        text = self.buffer.to_text()
        written = self.fs.write_file(self.path, text)
        self.buffer.modified = False
        self.message = f'"{self.path}" written {written} bytes'

    # 加载文件并启动 curses 全屏编辑循环。
    def run(self) -> None:
        self.load()
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise VimEditorError("vim requires an interactive terminal")
        curses.wrapper(self._run_screen)

    # 配置 curses 屏幕并持续读取按键。
    def _run_screen(self, stdscr) -> None:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        stdscr.keypad(True)
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            curses.mouseinterval(0)
        except curses.error:
            pass

        while self.running:
            self._draw(stdscr)
            key = self._read_key(stdscr)
            self._handle_key(key)

    # 根据当前模式分发按键处理逻辑。
    def _handle_key(self, key) -> None:
        if key == curses.KEY_MOUSE:
            self._handle_mouse_key()
            return
        if self.mode == INSERT:
            self._handle_insert_key(key)
        elif self.mode == COMMAND:
            self._handle_command_key(key)
        else:
            self._handle_normal_key(key)

    # 处理普通模式下的移动、编辑和命令入口按键。
    def _handle_normal_key(self, key) -> None:
        if key in (curses.KEY_LEFT, "h"):
            self.buffer.move_left()
        elif key in (curses.KEY_RIGHT, "l"):
            self.buffer.move_right()
        elif key in (curses.KEY_UP, "k"):
            self.buffer.move_up()
        elif key in (curses.KEY_DOWN, "j"):
            self.buffer.move_down()
        elif key == "i":
            self.mode = INSERT
            self.message = "-- INSERT --"
        elif key == "a":
            self.buffer.move_right()
            self.mode = INSERT
            self.message = "-- INSERT --"
        elif key == "o":
            self.buffer.open_line_below()
            self.mode = INSERT
            self.message = "-- INSERT --"
        elif key == "O":
            self.buffer.open_line_above()
            self.mode = INSERT
            self.message = "-- INSERT --"
        elif key == "x":
            self.buffer.delete_char()
        elif key == "d":
            self.buffer.delete_line()
        elif key == ":":
            self.mode = COMMAND
            self.command = ""
        elif key == "\x13":
            self.save()

    # 处理插入模式下的输入、删除、换行和退出按键。
    def _handle_insert_key(self, key) -> None:
        if key == "\x1b":
            self.mode = NORMAL
            self.message = ""
        elif key in (curses.KEY_LEFT,):
            self.buffer.move_left()
        elif key in (curses.KEY_RIGHT,):
            self.buffer.move_right()
        elif key in (curses.KEY_UP,):
            self.buffer.move_up()
        elif key in (curses.KEY_DOWN,):
            self.buffer.move_down()
        elif key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            self.buffer.backspace()
        elif key in ("\n", "\r"):
            self.buffer.insert_newline()
        elif isinstance(key, str) and key.isprintable():
            self.buffer.insert_char(key)

    # 处理命令模式下的命令编辑和执行按键。
    def _handle_command_key(self, key) -> None:
        if key == "\x1b":
            self.mode = NORMAL
            self.command = ""
            self.message = ""
        elif key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            self.command = self.command[:-1]
        elif key in ("\n", "\r"):
            self._execute_command(self.command.strip())
            self.command = ""
            if self.running:
                self.mode = NORMAL
        elif isinstance(key, str) and key.isprintable():
            self.command += key

    # 执行保存、退出和跳转行号等冒号命令。
    def _execute_command(self, command: str) -> None:
        if command == "w":
            self.save()
        elif command in {"q", "quit"}:
            if self.buffer.modified:
                self.message = "No write since last change (add ! to override)"
            else:
                self.running = False
        elif command in {"q!", "quit!"}:
            self.running = False
        elif command in {"wq", "x"}:
            self.save()
            self.running = False
        elif command.isdigit():
            self.buffer.goto_line(int(command))
        else:
            self.message = f"Not an editor command: {command}"

    # 重绘文本区域、状态栏、命令栏和终端光标。
    def _draw(self, stdscr) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        text_height = max(1, height - 2)
        self.text_height = text_height
        self.screen_width = width
        self._scroll_to_cursor(text_height, width)

        for screen_y in range(text_height):
            line_index = self.row_offset + screen_y
            if line_index < len(self.buffer.lines):
                line = self.buffer.lines[line_index]
                visible = line[self.col_offset : self.col_offset + width]
                self._addnstr(stdscr, screen_y, 0, visible, width)
            else:
                self._addnstr(stdscr, screen_y, 0, "~", width)

        status_y = max(0, height - 2)
        command_y = max(0, height - 1)
        self._draw_status(stdscr, status_y, width)
        self._draw_command_line(stdscr, command_y, width)

        cursor_y = self.buffer.cursor_y - self.row_offset
        cursor_x = self.buffer.cursor_x - self.col_offset
        cursor_y = min(max(cursor_y, 0), max(0, text_height - 1))
        cursor_x = min(max(cursor_x, 0), max(0, width - 1))
        stdscr.move(cursor_y, cursor_x)
        stdscr.refresh()

    # 根据光标位置更新行列滚动偏移。
    def _scroll_to_cursor(self, text_height: int, width: int) -> None:
        if self.buffer.cursor_y < self.row_offset:
            self.row_offset = self.buffer.cursor_y
        elif self.buffer.cursor_y >= self.row_offset + text_height:
            self.row_offset = self.buffer.cursor_y - text_height + 1

        if self.buffer.cursor_x < self.col_offset:
            self.col_offset = self.buffer.cursor_x
        elif self.buffer.cursor_x >= self.col_offset + width:
            self.col_offset = self.buffer.cursor_x - width + 1

    # 绘制包含模式、文件名和光标位置的状态栏。
    def _draw_status(self, stdscr, y: int, width: int) -> None:
        dirty = "[+]" if self.buffer.modified else ""
        left = f" {self.mode} {dirty} {self.path}"
        right = f"Ln {self.buffer.cursor_y + 1}, Col {self.buffer.cursor_x + 1} "
        gap = max(1, width - len(left) - len(right))
        status = (left + " " * gap + right)[:width]
        self._addnstr(stdscr, y, 0, status.ljust(width), width, curses.A_REVERSE)

    # 绘制命令输入行或普通消息提示。
    def _draw_command_line(self, stdscr, y: int, width: int) -> None:
        if self.mode == COMMAND:
            text = ":" + self.command
        else:
            text = self.message
        self._addnstr(stdscr, y, 0, text.ljust(width), width)

    # 安全写入 curses 文本，忽略边界导致的绘制异常。
    def _addnstr(self, stdscr, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
        try:
            stdscr.addnstr(y, x, text, n, attr)
        except curses.error:
            pass

    # 读取一次按键并归一化特殊键序列。
    def _read_key(self, stdscr):
        key = stdscr.get_wch()
        if key == curses.KEY_MOUSE:
            return key
        if key in ESCAPE_KEY_SEQUENCES:
            return ESCAPE_KEY_SEQUENCES[key]
        if key == "\x1b":
            return self._read_escape_sequence(stdscr)
        if key in ("\x00", "\xe0"):
            return self._read_windows_special_key(stdscr, key)
        return key

    # 读取并解析 ESC 开头的终端方向键序列。
    def _read_escape_sequence(self, stdscr):
        sequence = "\x1b" + self._drain_pending_input(stdscr)
        return ESCAPE_KEY_SEQUENCES.get(sequence, "\x1b")

    # 读取并解析 Windows 风格特殊键序列。
    def _read_windows_special_key(self, stdscr, prefix: str):
        try:
            next_key = stdscr.get_wch()
        except curses.error:
            return prefix
        if isinstance(next_key, str):
            return WINDOWS_SPECIAL_KEY_SEQUENCES.get(next_key, prefix + next_key)
        return next_key

    # 临时切换非阻塞模式以读取后续已到达的输入。
    def _drain_pending_input(self, stdscr, *, limit: int = 8) -> str:
        chunks: list[str] = []
        stdscr.nodelay(True)
        try:
            for _ in range(limit):
                try:
                    next_key = stdscr.get_wch()
                except curses.error:
                    break
                if not isinstance(next_key, str):
                    break
                chunks.append(next_key)
        finally:
            stdscr.nodelay(False)
        return "".join(chunks)

    # 处理鼠标点击并把光标移动到对应文本位置。
    def _handle_mouse_key(self) -> None:
        try:
            _device_id, mouse_x, mouse_y, _z, button_state = curses.getmouse()
        except curses.error:
            return

        click_mask = 0
        for name in (
            "BUTTON1_PRESSED",
            "BUTTON1_RELEASED",
            "BUTTON1_CLICKED",
            "BUTTON1_DOUBLE_CLICKED",
            "BUTTON1_TRIPLE_CLICKED",
        ):
            click_mask |= getattr(curses, name, 0)

        if click_mask and not (button_state & click_mask):
            return
        if mouse_y < 0 or mouse_y >= self.text_height:
            return

        self.buffer.cursor_y = min(max(self.row_offset + mouse_y, 0), len(self.buffer.lines) - 1)
        line_length = len(self.buffer.lines[self.buffer.cursor_y])
        self.buffer.cursor_x = min(max(self.col_offset + mouse_x, 0), line_length)
