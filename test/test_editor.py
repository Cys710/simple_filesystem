import curses
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.editor import TextBuffer, VimEditor, VimEditorError
from cli.shell import Shell
from core.file_system import FileSystem, FileSystemError
from user import DEFAULT_ROOT_PASSWORD


class TestTextBuffer(unittest.TestCase):
    def test_insert_newline_and_backspace(self):
        buffer = TextBuffer.from_text("hello")

        for _ in range(5):
            buffer.move_right()
        buffer.insert_newline()
        buffer.insert_char("w")

        self.assertEqual(buffer.lines, ["hello", "w"])
        self.assertEqual((buffer.cursor_y, buffer.cursor_x), (1, 1))

        buffer.backspace()
        buffer.backspace()

        self.assertEqual(buffer.lines, ["hello"])
        self.assertEqual((buffer.cursor_y, buffer.cursor_x), (0, 5))
        self.assertTrue(buffer.modified)

    def test_delete_char_joins_next_line(self):
        buffer = TextBuffer.from_text("abc\ndef")

        buffer.goto_line(1)
        for _ in range(3):
            buffer.move_right()
        buffer.delete_char()

        self.assertEqual(buffer.lines, ["abcdef"])

    def test_goto_line_clamps_to_file_size(self):
        buffer = TextBuffer.from_text("a\nb\nc")

        buffer.goto_line(99)

        self.assertEqual((buffer.cursor_y, buffer.cursor_x), (2, 0))


class TestVimEditorPersistence(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, fs

    def test_save_creates_new_file(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")
            editor.load()
            editor.buffer.insert_char("h")
            editor.buffer.insert_char("i")

            editor.save()

            self.assertEqual(fs.read_file("/note.txt"), b"hi")
            self.assertFalse(editor.buffer.modified)
        finally:
            temp_dir.cleanup()

    def test_load_and_save_existing_file(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.touch("/note.txt")
            fs.write_file("/note.txt", "old")

            editor = VimEditor(fs, "/note.txt")
            editor.load()
            editor.buffer.goto_line(1)
            editor.buffer.move_right()
            editor.buffer.move_right()
            editor.buffer.move_right()
            editor.buffer.insert_char("!")
            editor.save()

            self.assertEqual(fs.read_file("/note.txt"), b"old!")
        finally:
            temp_dir.cleanup()

    def test_load_preserves_permission_error(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.useradd("bob", "bob-pass")
            fs.su("alice", "alice-pass")
            fs.write_file("private.txt", "secret")
            fs.chmod("/home/alice", "75")
            fs.chmod("/home/alice/private.txt", "60")
            fs.su("bob", "bob-pass")

            editor = VimEditor(fs, "/home/alice/private.txt")
            with self.assertRaisesRegex(FileSystemError, "permission denied"):
                editor.load()
        finally:
            temp_dir.cleanup()

    def test_run_requires_interactive_terminal(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")

            with (
                patch("cli.editor.sys.stdin.isatty", return_value=False),
                patch("cli.editor.curses.wrapper") as wrapper,
            ):
                with self.assertRaisesRegex(VimEditorError, "interactive terminal"):
                    editor.run()

            wrapper.assert_not_called()
        finally:
            temp_dir.cleanup()

    def test_run_screen_allows_terminal_without_cursor_visibility_support(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")
            editor.running = False
            stdscr = Mock()

            with patch("cli.editor.curses.curs_set", side_effect=curses.error):
                editor._run_screen(stdscr)

            stdscr.keypad.assert_called_once_with(True)
        finally:
            temp_dir.cleanup()

    def test_read_key_normalizes_escape_arrow_sequence(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")
            stdscr = Mock()
            stdscr.get_wch.side_effect = [
                "\x1b",
                "[",
                "B",
                curses.error("no input"),
            ]

            key = editor._read_key(stdscr)

            self.assertEqual(key, curses.KEY_DOWN)
            stdscr.nodelay.assert_any_call(True)
            stdscr.nodelay.assert_any_call(False)
        finally:
            temp_dir.cleanup()

    def test_read_key_normalizes_windows_special_arrow_sequence(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")
            stdscr = Mock()
            stdscr.get_wch.side_effect = ["\xe0", "H"]

            key = editor._read_key(stdscr)

            self.assertEqual(key, curses.KEY_UP)
        finally:
            temp_dir.cleanup()

    def test_mouse_click_moves_cursor(self):
        temp_dir, fs = self.make_fs()
        try:
            editor = VimEditor(fs, "/note.txt")
            editor.buffer = TextBuffer.from_text("abc\ndefgh")
            editor.row_offset = 0
            editor.col_offset = 0
            editor.text_height = 5

            with patch("cli.editor.curses.getmouse", return_value=(0, 2, 1, 0, getattr(curses, "BUTTON1_CLICKED", 0))):
                editor._handle_key(curses.KEY_MOUSE)

            self.assertEqual((editor.buffer.cursor_y, editor.buffer.cursor_x), (1, 2))
        finally:
            temp_dir.cleanup()

    def test_shell_reports_non_interactive_terminal(self):
        temp_dir, fs = self.make_fs()
        try:
            output = io.StringIO()
            shell = Shell(output=output)
            shell.fs = fs

            with patch("cli.editor.sys.stdin.isatty", return_value=False):
                shell.execute("vim /note.txt")

            self.assertIn("error: vim requires an interactive terminal", output.getvalue())
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
