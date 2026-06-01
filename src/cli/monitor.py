"""
    curses based full-screen monitor for the teaching file system.
"""

from __future__ import annotations

import curses
import re
import shlex
import sys
import time
from collections.abc import Callable

from cli.visualizer import DiskVisualizer
from core.debug_info import FileSystemInspector
from core.file_system import FileSystem


OVERVIEW = "overview"
INODE = "inode"
GROUP = "group"
BLOCK = "block"
FILE = "file"
VIEWS = [OVERVIEW, INODE, GROUP, BLOCK, FILE]


class DiskMonitorError(Exception):
    pass


class DiskMonitor:
    def __init__(
        self,
        fs: FileSystem,
        *,
        command_executor: Callable[[str], str] | None = None,
    ):
        self.fs = fs
        self.command_executor = command_executor
        self.visualizer = DiskVisualizer()
        self.view = OVERVIEW
        self.command = ""
        self.message = "Ready. Type a file-system command or press 1..4 for details."
        self.row_offset = 0
        self.col_offset = 0
        self.running = True
        self.index_path: str | None = None
        self.needs_full_redraw = True
        self.screen_size: tuple[int, int] | None = None

    def run(self) -> None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise DiskMonitorError("monitor requires an interactive terminal")
        try:
            curses.wrapper(self._run_screen)
        except KeyboardInterrupt:
            self.running = False
        except curses.error as exc:
            raise DiskMonitorError(f"monitor terminal error: {exc}") from exc

    def _run_screen(self, stdscr) -> None:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.timeout(-1)
        self._init_colors()

        while self.running:
            self._draw(stdscr)
            try:
                key = stdscr.get_wch()
            except curses.error as exc:
                if str(exc) != "no input":
                    raise
                # Some terminal wrappers briefly expose a non-blocking read.
                time.sleep(0.01)
                continue
            if key == curses.KEY_RESIZE:
                self._invalidate_screen(stdscr)
            self._handle_key(key)

    def _handle_key(self, key) -> None:
        if key == curses.KEY_RESIZE:
            self.needs_full_redraw = True
        elif key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            self.command = self.command[:-1]
        elif key in ("\n", "\r"):
            command = self.command.strip()
            self.command = ""
            if command:
                self._execute_command(command)
        elif key == "\x1b":
            self._switch_view(OVERVIEW)
        elif key == "\t":
            index = (VIEWS.index(self.view) + 1) % len(VIEWS)
            self._switch_view(VIEWS[index])
        elif key in (curses.KEY_UP,):
            self.row_offset = max(0, self.row_offset - 1)
        elif key in (curses.KEY_DOWN,):
            self.row_offset += 1
        elif key == curses.KEY_PPAGE:
            self.row_offset = max(0, self.row_offset - 10)
        elif key == curses.KEY_NPAGE:
            self.row_offset += 10
        elif key in (curses.KEY_LEFT,):
            self.col_offset = max(0, self.col_offset - 4)
        elif key in (curses.KEY_RIGHT,):
            self.col_offset += 4
        elif key == curses.KEY_HOME:
            self.col_offset = 0
        elif key == curses.KEY_END:
            self.col_offset += 40
        elif key == "\x12":
            self.message = "Refreshed."
        elif key == "\x11":
            self.running = False
        elif not self.command and key == "q":
            self.running = False
        elif not self.command and key in {"1", "2", "3", "4"}:
            self._switch_view({"1": INODE, "2": GROUP, "3": BLOCK, "4": FILE}[key])
        elif isinstance(key, str) and key.isprintable():
            self.command += key

    def _execute_command(self, command: str) -> None:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            self.message = f"error: {exc}"
            return
        if not argv:
            return

        name, *args = argv
        if name in {"index", "file"}:
            if len(args) != 1:
                self.message = "usage: index file"
                return
            self.index_path = args[0]
            self._switch_view(FILE)
            self.message = f"Loaded index view for {args[0]}"
            return
        if name == "view":
            if len(args) != 1:
                self.message = "usage: view overview|inode|group|block|file"
                return
            aliases = {
                "overview": OVERVIEW,
                "inode": INODE,
                "group": GROUP,
                "groups": GROUP,
                "block": BLOCK,
                "blocks": BLOCK,
                "file": FILE,
                "index": FILE,
            }
            if args[0] not in aliases:
                self.message = f"unknown view: {args[0]}"
                return
            self._switch_view(aliases[args[0]])
            return
        if name in {"quit", "exit"}:
            self.running = False
            return
        if name == "refresh":
            self.message = "Refreshed."
            return
        if self.command_executor is None:
            self.message = "This monitor has no command executor."
            return

        self.message = self.command_executor(command) or f"Executed: {command}"

    def _switch_view(self, view: str) -> None:
        self.view = view
        self.row_offset = 0
        self.col_offset = 0
        self.needs_full_redraw = True

    def _invalidate_screen(self, stdscr) -> None:
        try:
            stdscr.clearok(True)
        except curses.error:
            pass
        self.screen_size = None
        self.needs_full_redraw = True

    def _draw(self, stdscr) -> None:
        height, width = stdscr.getmaxyx()
        screen_size = (height, width)
        if screen_size != self.screen_size:
            self.screen_size = screen_size
            self.needs_full_redraw = True

        if self.needs_full_redraw:
            stdscr.clear()
            self.needs_full_redraw = False
        else:
            stdscr.erase()
        if height < 16 or width < 68:
            self._draw_small_terminal(stdscr, height, width)
            return
        canvas_width = width - 1

        inspector = FileSystemInspector(self.fs)
        try:
            lines = self._view_lines(inspector, canvas_width)
        except Exception as exc:
            lines = [f"Unable to render monitor data: {exc}"]

        self._draw_header(stdscr, canvas_width)
        content_top = 3
        content_height = max(1, height - 7)
        visible_lines = lines[self.row_offset : self.row_offset + content_height]
        for offset in range(content_height):
            y = content_top + offset
            self._addnstr(stdscr, y, 1, " " * (canvas_width - 2), canvas_width - 2)
            self._addnstr(stdscr, y, 0, "│", 1, self._color(1))
            self._addnstr(stdscr, y, canvas_width - 1, "│", 1, self._color(1))
            if offset < len(visible_lines):
                line = visible_lines[offset]
                visible = line[self.col_offset : self.col_offset + canvas_width - 4]
                self._draw_styled_line(stdscr, y, 3, visible, canvas_width - 4)

        self._draw_footer(stdscr, height, canvas_width)
        cursor_x = min(canvas_width - 2, len(f" simplefs:{self.fs.pwd()} > ") + len(self.command))
        stdscr.move(height - 2, cursor_x)
        stdscr.refresh()

    def _view_lines(self, inspector: FileSystemInspector, width: int) -> list[str]:
        inode_info = inspector.inode_bitmap()
        group_info = inspector.free_groups()
        block_info = inspector.block_map()
        if self.view == OVERVIEW:
            lines = []
            for title, section in self.visualizer.render_overview(
                inode_info,
                group_info,
                block_info,
            ):
                lines.append(self._divider(title, width - 2))
                lines.extend(section)
            return lines
        if self.view == INODE:
            return [self._divider("Inode Bitmap / Type View", width - 2)] + (
                self.visualizer.render_inode_bitmap(inode_info)
            )
        if self.view == GROUP:
            return [self._divider("SuperBlock Free Block Groups", width - 2)] + (
                self.visualizer.render_free_groups(group_info)
            )
        if self.view == BLOCK:
            return [self._divider("Disk Data Block Allocation", width - 2)] + (
                self.visualizer.render_block_map(block_info)
            )
        if self.index_path is None:
            return [
                self._divider("Single File Index", width - 2),
                "",
                "No file selected.",
                "",
                "Type: index /path/to/file",
            ]
        return [self._divider("Single File Index", width - 2)] + (
            self.visualizer.render_file_index(inspector.file_index(self.index_path))
        )

    def _draw_header(self, stdscr, width: int) -> None:
        title = " SimpleFS Monitor "
        line = "┌" + "─" * max(0, width - 2) + "┐"
        start = max(1, (width - len(title)) // 2)
        line = line[:start] + title + line[start + len(title) :]
        self._addnstr(stdscr, 0, 0, line, width, self._color(1) | curses.A_BOLD)
        status = (
            f"│ Path: {self.fs.pwd():<22} "
            f"View: {self.view:<10} "
            "Tab cycle | 1..4 details | Up/Down scroll | q quit"
        )
        self._addnstr(stdscr, 1, 0, status[: width - 1].ljust(width - 1) + "│", width)
        self._addnstr(stdscr, 2, 0, "├" + "─" * (width - 2) + "┤", width, self._color(1))

    def _draw_footer(self, stdscr, height: int, width: int) -> None:
        self._addnstr(stdscr, height - 4, 0, "├" + "─" * (width - 2) + "┤", width, self._color(1))
        message = f"│ Log: {self.message}"
        self._addnstr(stdscr, height - 3, 0, message[: width - 1].ljust(width - 1) + "│", width)
        prompt = f" simplefs:{self.fs.pwd()} > {self.command}"
        self._addnstr(stdscr, height - 2, 0, prompt[:width].ljust(width), width, curses.A_REVERSE)
        self._addnstr(stdscr, height - 1, 0, "└" + "─" * (width - 2) + "┘", width, self._color(1))

    def _draw_small_terminal(self, stdscr, height: int, width: int) -> None:
        canvas_width = max(1, width - 1)
        lines = [
            "SimpleFS Monitor",
            "",
            "Terminal is too small.",
            "Minimum size: 68 columns x 16 rows.",
            f"Current size: {width} columns x {height} rows.",
            "",
            "Resize the terminal or press q to quit.",
        ]
        for y, line in enumerate(lines[:height]):
            self._addnstr(stdscr, y, 0, line, canvas_width)
        stdscr.refresh()

    def _divider(self, title: str, width: int) -> str:
        title = f" {title} "
        available = max(0, width - len(title) - 2)
        left = available // 2
        right = available - left
        return "├" + "─" * left + title + "─" * right + "┤"

    def _init_colors(self) -> None:
        try:
            curses.use_default_colors()
            curses.start_color()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLUE, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_MAGENTA, -1)
            curses.init_pair(5, curses.COLOR_CYAN, -1)
            curses.init_pair(6, curses.COLOR_YELLOW, -1)
            curses.init_pair(7, curses.COLOR_RED, -1)
            curses.init_pair(8, curses.COLOR_WHITE, -1)
        except curses.error:
            pass

    def _color(self, pair: int) -> int:
        try:
            return curses.color_pair(pair)
        except curses.error:
            return 0

    def _addnstr(self, stdscr, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
        try:
            stdscr.addnstr(y, x, text, n, attr)
        except curses.error:
            pass

    def _draw_styled_line(self, stdscr, y: int, x: int, text: str, width: int) -> None:
        symbol_attrs = {
            "D": self._color(2) | curses.A_BOLD,
            "F": self._color(3) | curses.A_BOLD,
            "G": self._color(4) | curses.A_BOLD,
            "X": self._color(5) | curses.A_BOLD,
            "S": self._color(6) | curses.A_BOLD,
            "R": self._color(6) | curses.A_BOLD,
            "I": self._color(5),
            "?": self._color(7) | curses.A_BOLD,
            ".": self._color(8) | curses.A_DIM,
        }
        cursor = 0
        for match in re.finditer(r"(?<!\S)([SIRDFGX?.])(?=\s|$)", text[:width]):
            if match.start() > cursor:
                self._addnstr(stdscr, y, x + cursor, text[cursor : match.start()], width - cursor)
            symbol = match.group(1)
            self._addnstr(stdscr, y, x + match.start(), symbol, 1, symbol_attrs[symbol])
            cursor = match.end()
        if cursor < min(len(text), width):
            self._addnstr(stdscr, y, x + cursor, text[cursor:width], width - cursor)
