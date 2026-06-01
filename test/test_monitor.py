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

from cli.monitor import BLOCK, FILE, GROUP, DiskMonitor, DiskMonitorError
from cli.shell import Shell
from cli.visualizer import DiskVisualizer
from core.debug_info import FileSystemInspector
from core.file_system import FileSystem
from head import BLOCK_SIZE, DATA_BLOCK_NUM, DATA_BLOCK_START_ID, DIRECT_CNT


class TestFileSystemInspector(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, fs

    def test_inode_bitmap_and_free_groups_follow_disk_state(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.mkdir("/docs")
            fs.touch("/note.txt")

            inspector = FileSystemInspector(fs)
            bitmap = inspector.inode_bitmap()
            groups = inspector.free_groups()

            self.assertEqual(bitmap.used, 3)
            self.assertEqual([entry.kind for entry in bitmap.entries[:3]], [
                "DIR",
                "DIR",
                "FILE",
            ])
            self.assertEqual(len(groups.free_block_ids), DATA_BLOCK_NUM - 3)
            self.assertTrue(groups.group_leader_ids)
            self.assertEqual(groups.next_allocated, groups.current_stack[-1])
            self.assertEqual(groups.next_group_pointer, groups.current_stack[0])
        finally:
            temp_dir.cleanup()

    def test_block_map_distinguishes_data_group_and_index_blocks(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.touch("/huge.bin")
            fs.write_file("/huge.bin", b"x" * (DIRECT_CNT * BLOCK_SIZE + 1))

            inspector = FileSystemInspector(fs)
            file_info = inspector.file_index("/huge.bin")
            block_map = inspector.block_map()
            roles = {entry.block_id: entry.role for entry in block_map.entries}

            self.assertEqual(
                roles[DATA_BLOCK_START_ID + file_info.direct_blocks[0]],
                "FILE_DATA",
            )
            self.assertEqual(
                roles[DATA_BLOCK_START_ID + file_info.single_indirect_block],
                "INDEX_BLOCK",
            )
            self.assertIn("GROUP_LINK", roles.values())
            self.assertEqual(block_map.inconsistencies, [])
        finally:
            temp_dir.cleanup()

    def test_visualizer_renders_horizontal_group_chain_and_file_tree(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.touch("/huge.bin")
            fs.write_file("/huge.bin", b"x" * (DIRECT_CNT * BLOCK_SIZE + 1))
            inspector = FileSystemInspector(fs)
            visualizer = DiskVisualizer()

            groups = "\n".join(visualizer.render_free_groups(inspector.free_groups()))
            file_index = "\n".join(visualizer.render_file_index(inspector.file_index("/huge.bin")))

            self.assertIn("Horizontal group chain", groups)
            self.assertIn("────>", groups)
            self.assertIn("SuperBlock", groups)
            self.assertIn("single indirect", file_index)
            self.assertIn("index block", file_index)
            self.assertIn("└──", file_index)
        finally:
            temp_dir.cleanup()


class TestDiskMonitorCommands(unittest.TestCase):
    def make_shell(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        output = io.StringIO()
        shell = Shell(disk_path, output=output)
        shell.execute("format")
        return temp_dir, shell, output

    def test_monitor_local_commands_switch_views(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.fs.touch("/note.txt")
            monitor = DiskMonitor(shell.fs)

            monitor._execute_command("view group")
            self.assertEqual(monitor.view, GROUP)

            monitor._execute_command("view block")
            self.assertEqual(monitor.view, BLOCK)

            monitor._execute_command("index /note.txt")
            self.assertEqual(monitor.view, FILE)
            self.assertEqual(monitor.index_path, "/note.txt")
        finally:
            temp_dir.cleanup()

    def test_q_exits_monitor_when_command_line_is_empty(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)

            monitor._handle_key("q")

            self.assertFalse(monitor.running)
        finally:
            temp_dir.cleanup()

    def test_run_screen_ignores_transient_no_input_error(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)
            stdscr = Mock()
            stdscr.get_wch.side_effect = [curses.error("no input"), "q"]

            with (
                patch.object(monitor, "_draw"),
                patch("cli.monitor.time.sleep") as sleep,
            ):
                monitor._run_screen(stdscr)

            stdscr.timeout.assert_called_once_with(-1)
            sleep.assert_called_once_with(0.01)
            self.assertFalse(monitor.running)
        finally:
            temp_dir.cleanup()

    def test_run_reports_terminal_initialization_error(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)
            with (
                patch("cli.monitor.sys.stdin.isatty", return_value=True),
                patch("cli.monitor.sys.stdout.isatty", return_value=True),
                patch("cli.monitor.curses.wrapper", side_effect=curses.error("setup failed")),
            ):
                with self.assertRaisesRegex(DiskMonitorError, "monitor terminal error: setup failed"):
                    monitor.run()
        finally:
            temp_dir.cleanup()

    def test_up_and_down_scroll_monitor_content(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)

            monitor._handle_key(curses.KEY_UP)
            self.assertEqual(monitor.row_offset, 0)

            monitor._handle_key(curses.KEY_DOWN)
            self.assertEqual(monitor.row_offset, 1)

            monitor._handle_key(curses.KEY_DOWN)
            self.assertEqual(monitor.row_offset, 2)

            monitor._handle_key(curses.KEY_UP)
            self.assertEqual(monitor.row_offset, 1)
        finally:
            temp_dir.cleanup()

    def test_tab_cycles_monitor_views(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)

            monitor._handle_key("\t")
            self.assertEqual(monitor.view, "inode")
        finally:
            temp_dir.cleanup()

    def test_draw_clears_content_rows_and_forces_full_redraw_after_view_switch(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            monitor = DiskMonitor(shell.fs)
            stdscr = Mock()
            stdscr.getmaxyx.return_value = (20, 80)

            with patch.object(monitor, "_view_lines", return_value=["short"]):
                monitor._draw(stdscr)

                stdscr.clear.assert_called_once_with()
                stdscr.addnstr.assert_any_call(3, 1, " " * 78, 78, 0)

                stdscr.reset_mock()
                monitor._switch_view(FILE)
                monitor._draw(stdscr)

                stdscr.clear.assert_called_once_with()
                stdscr.erase.assert_not_called()
        finally:
            temp_dir.cleanup()

    def test_shell_command_executor_updates_file_system(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            message = shell._execute_monitor_command("touch /note.txt")

            self.assertEqual(message, "")
            self.assertEqual(shell.fs.stat("/note.txt")["type"], "file")
            self.assertIn(
                "unavailable inside monitor",
                shell._execute_monitor_command("format"),
            )
        finally:
            temp_dir.cleanup()

    def test_monitor_ls_strips_terminal_color_codes(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            shell.fs.mkdir("/a")
            shell.fs.touch("/test.txt")

            message = shell._execute_monitor_command("ls")

            self.assertEqual(message, "a  test.txt")
            self.assertNotIn("\x1b", message)
        finally:
            temp_dir.cleanup()

    def test_monitor_fill_command_appends_test_bytes(self):
        temp_dir, shell, _output = self.make_shell()
        try:
            message = shell._execute_monitor_command("fill /demo.bin 40961")
            inode, _dir_block = shell.fs._resolve_path("/demo.bin")

            self.assertEqual(message, "appended 40961 bytes to /demo.bin")
            self.assertEqual(inode.size, DIRECT_CNT * BLOCK_SIZE + 1)
            self.assertIsNotNone(inode.indirect_block)
        finally:
            temp_dir.cleanup()

    def test_shell_reports_non_interactive_monitor(self):
        temp_dir, shell, output = self.make_shell()
        try:
            with patch("cli.monitor.sys.stdin.isatty", return_value=False):
                shell.execute("monitor")

            self.assertIn(
                "error: monitor requires an interactive terminal",
                output.getvalue(),
            )
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
