import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.shell import Shell
from cli import gui_mode
from cli.gui_mode import FileSystemGui, FileSystemGuiError
from user import DEFAULT_ROOT_PASSWORD


class TestGuiModeCommand(unittest.TestCase):
    def make_shell(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        output = io.StringIO()
        shell = Shell(
            disk_path,
            password_func=lambda _prompt: DEFAULT_ROOT_PASSWORD,
            output=output,
        )
        return temp_dir, shell, output

    def test_gui_requires_login_and_reuses_shell_command_execution(self):
        temp_dir, shell, output = self.make_shell()
        try:
            shell.execute("format")
            shell.fs.write_file("/note.txt", "hello")

            shell.execute("gui")
            self.assertIn("gui: login required", output.getvalue())

            class FakeGui:
                started = False

                def __init__(self, _fs_getter, command_executor, **_kwargs):
                    self.command_executor = command_executor

                def run(self):
                    FakeGui.started = True
                    self.command_executor("cat /note.txt")

            shell.execute("login root")
            with patch("cli.shell.FileSystemGui", FakeGui):
                shell.execute("gui")

            rendered = output.getvalue()
            self.assertTrue(FakeGui.started)
            self.assertIn("[gui]$ cat /note.txt", rendered)
            self.assertIn("hello", rendered)
        finally:
            temp_dir.cleanup()

    def test_gui_reads_plain_names_and_generates_default_names(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.execute("format")
            shell.fs.mkdir("/docs")
            shell.fs.touch("/note.txt")
            shell.fs.touch("/新建文件.txt")

            gui = FileSystemGui(lambda: shell.fs, lambda _command: (True, ""))
            entries = gui._entries("/")

            self.assertIn("docs", [entry.name for entry in entries])
            self.assertNotIn("\x1b", "".join(entry.name for entry in entries))
            self.assertEqual(gui._default_name("新建文件.txt"), "新建文件 (2).txt")
        finally:
            temp_dir.cleanup()

    def test_gui_reports_missing_qt_dependency(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.execute("format")
            gui = FileSystemGui(lambda: shell.fs, lambda _command: (True, ""))

            with patch("cli.gui_mode.QtWidgets", None):
                with self.assertRaisesRegex(FileSystemGuiError, "PySide6"):
                    gui.run()
        finally:
            temp_dir.cleanup()

    def test_gui_reports_missing_graphical_display(self):
        if gui_mode.QtWidgets is None:
            self.skipTest("PySide6 is not installed")
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.execute("format")
            gui = FileSystemGui(lambda: shell.fs, lambda _command: (True, ""))

            with patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
                with patch("sys.platform", "linux"):
                    with self.assertRaisesRegex(FileSystemGuiError, "graphical display"):
                        gui.run()
        finally:
            temp_dir.cleanup()

    def test_gui_uses_svg_icons_from_figure_directory(self):
        gui = FileSystemGui(lambda: None, lambda _command: (True, ""))

        expected_icons = {
            "新建文件": "新建文件.svg",
            "新建文件夹": "新建文件夹.svg",
            "打开": "4打开文件.svg",
            "编辑": "编辑.svg",
            "删除": "删除.svg",
            "属性": "属性.svg",
            "上一级": "上一级.svg",
            "刷新": "刷新.svg",
        }

        for label, filename in expected_icons.items():
            icon_path = gui._icon_resource_path(label)
            self.assertIsNotNone(icon_path)
            self.assertEqual(icon_path.name, filename)
            self.assertTrue(icon_path.exists())

    def test_gui_permission_text_and_root_only_useradd_state(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.execute("format")
            gui = FileSystemGui(lambda: shell.fs, lambda _command: (True, ""))

            self.assertEqual(
                gui._permission_text({"mode": "64", "owner_id": 0}),
                "当前用户: 可读/不可写",
            )
            self.assertEqual(gui._permission_detail_text("64"), "64；所有者:读/写；其他用户:读")
            self.assertFalse(gui._can_manage_users())

            shell.fs.login("root", DEFAULT_ROOT_PASSWORD)
            self.assertEqual(
                gui._permission_text({"mode": "00", "owner_id": 999}),
                "root: 可读/可写",
            )
            self.assertTrue(gui._can_manage_users())
            self.assertTrue(gui._can_change_permissions())

            shell.fs.write_file("/readonly.txt", "hello")
            shell.fs.chmod("/readonly.txt", "64")
            shell.fs.useradd("alice", "alice-pass")
            shell.fs.su("alice", "alice-pass")
            self.assertEqual(
                gui._permission_text({"mode": "64", "owner_id": 999}),
                "alice: 可读/不可写",
            )
            self.assertTrue(gui._can_read_path("/readonly.txt"))
            self.assertFalse(gui._can_write_path("/readonly.txt"))
            self.assertFalse(gui._can_manage_users())
            self.assertFalse(gui._can_change_permissions())
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
