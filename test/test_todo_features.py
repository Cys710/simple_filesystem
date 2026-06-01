import io
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.shell import Shell
from core.file_system import FileSystem, FileSystemError
from user import DEFAULT_ROOT_PASSWORD


class TestTodoFeatures(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, fs

    def make_shell(self, passwords):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        password_iter = iter(passwords)
        output = io.StringIO()
        shell = Shell(
            disk_path,
            password_func=lambda prompt: next(password_iter),
            output=output,
        )
        return temp_dir, shell, output

    def test_shell_requires_login_before_regular_commands(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            shell.execute("pwd")
            shell.execute("login root")
            shell.execute("pwd")

            rendered = output.getvalue()
            self.assertIn("pwd: login required. Please run 'login <username>' first.", rendered)
            self.assertIn("logged in as root", rendered)
        finally:
            temp_dir.cleanup()

    def test_shell_login_switches_to_user_home_directory(self):
        temp_dir, shell, _output = self.make_shell([
            DEFAULT_ROOT_PASSWORD,
            "alice-pass",
            "alice-pass",
            "alice-pass",
        ])
        try:
            shell.execute("format")
            shell.execute("login root")
            shell.execute("useradd alice")
            shell.execute("logout")
            shell.execute("login alice")

            self.assertEqual(shell.fs.whoami(), "alice")
            self.assertEqual(shell.fs.pwd(), "/home/alice")
        finally:
            temp_dir.cleanup()

    def test_tilde_expands_to_user_home(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.su("alice", "alice-pass")

            fs.write_file("~/note.txt", "hello")

            self.assertEqual(fs.read_file("/home/alice/note.txt"), b"hello")
            self.assertEqual(fs.read_file("~/note.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_tree_and_find_walk_directory_structure(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.mkdir("/docs")
            fs.mkdir("/docs/sub")
            fs.write_file("/docs/readme.txt", "hi")
            fs.write_file("/docs/sub/note.txt", "nested")

            self.assertEqual(
                fs.tree("/docs"),
                [
                    "/docs/",
                    "|-- sub/",
                    "|   `-- note.txt",
                    "`-- readme.txt",
                ],
            )
            self.assertEqual(
                fs.find("*.txt", "/docs"),
                [
                    "/docs/sub/note.txt",
                    "/docs/readme.txt",
                ],
            )
        finally:
            temp_dir.cleanup()

    def test_link_keeps_file_until_last_name_is_removed(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.write_file("/note.txt", "hello")
            fs.link("/note.txt", "/alias.txt")

            fs.remove("/note.txt")
            self.assertEqual(fs.read_file("/alias.txt"), b"hello")

            fs.remove("/alias.txt")
            with self.assertRaises(FileSystemError):
                fs.read_file("/alias.txt")
        finally:
            temp_dir.cleanup()

    def test_recursive_delete_preserves_external_hard_link(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.mkdir("/work")
            fs.write_file("/work/data.txt", "payload")
            fs.link("/work/data.txt", "/saved.txt")

            fs.rmdir("/work", recursive=True)

            self.assertEqual(fs.read_file("/saved.txt"), b"payload")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
