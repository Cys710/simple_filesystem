import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.completion import CommandCompleter
from core.file_system import FileSystem


class TestCommandCompleter(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, fs

    def test_completes_command_name(self):
        completer = CommandCompleter(lambda: None)

        result = completer.complete("mon")

        self.assertEqual(result.line, "monitor ")
        self.assertEqual(result.candidates, ["monitor"])

    def test_completes_gui_command_name(self):
        completer = CommandCompleter(lambda: None)

        result = completer.complete("gu")

        self.assertEqual(result.line, "gui ")
        self.assertEqual(result.candidates, ["gui"])

    def test_completes_paths_from_current_directory(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.mkdir("/docs")
            fs.touch("/note.txt")
            completer = CommandCompleter(lambda: fs)

            self.assertEqual(completer.complete("cd do").line, "cd docs/")
            self.assertEqual(completer.complete("cat no").line, "cat note.txt ")
        finally:
            temp_dir.cleanup()

    def test_completes_nested_paths(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.mkdir("/docs")
            fs.touch("/docs/note.txt")
            completer = CommandCompleter(lambda: fs)

            result = completer.complete("cat /docs/no")

            self.assertEqual(result.line, "cat /docs/note.txt ")
        finally:
            temp_dir.cleanup()

    def test_directory_only_commands_do_not_offer_files(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.mkdir("/docs")
            fs.touch("/document.txt")
            completer = CommandCompleter(lambda: fs)

            result = completer.complete("cd do")

            self.assertEqual(result.candidates, ["docs/"])
        finally:
            temp_dir.cleanup()

    def test_completes_tilde_paths_from_user_home(self):
        temp_dir, fs = self.make_fs()
        try:
            fs.login("root", "123456")
            fs.useradd("alice", "alice-pass")
            fs.su("alice", "alice-pass")
            fs.touch("~/note.txt")
            completer = CommandCompleter(lambda: fs)

            result = completer.complete("cat ~/no")

            self.assertEqual(result.line, "cat ~/note.txt ")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()

