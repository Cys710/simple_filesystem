import io
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.shell import Shell
from core.file_system import FileSystemError
from user import DEFAULT_ROOT_PASSWORD


class TestShellBatchScripts(unittest.TestCase):
    def make_shell(self, passwords=()):
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

    def write_script(self, shell: Shell, path: str, content: str) -> None:
        shell.fs.write_file(path, content)

    def test_bash_runs_script_from_simulated_file_system(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            self.write_script(
                shell,
                "/demo.sh",
                "\n".join([
                    "login root",
                    "mkdir /docs",
                    "write /docs/note.txt hello",
                    "cat /docs/note.txt",
                ]),
            )

            shell.execute("bash /demo.sh")

            self.assertEqual(shell.fs.read_file("/docs/note.txt"), b"hello")
            self.assertIn("hello", output.getvalue())
        finally:
            temp_dir.cleanup()

    def test_bash_ignores_comments_and_blank_lines(self):
        temp_dir, shell, _output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            self.write_script(
                shell,
                "/commented.sh",
                "\n".join([
                    "# setup",
                    "",
                    "login root",
                    "write /a.txt 'hello world'  # inline comment",
                ]),
            )

            shell.execute("bash /commented.sh")

            self.assertEqual(shell.fs.read_file("/a.txt"), b"hello world")
        finally:
            temp_dir.cleanup()

    def test_bash_collects_arguments_across_multiple_lines(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            shell.fs.write_file("/a.txt", "hello")
            self.write_script(
                shell,
                "/multiline.sh",
                "\n".join([
                    "login root",
                    "cat",
                    "/a.txt",
                ]),
            )

            shell.execute("bash /multiline.sh")

            self.assertIn("hello", output.getvalue())
            self.assertIn("[bash:/multiline.sh:2-3]$ cat /a.txt", output.getvalue())
        finally:
            temp_dir.cleanup()

    def test_bash_reports_script_line_range_on_error(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            self.write_script(
                shell,
                "/bad.sh",
                "\n".join([
                    "login root",
                    "cat",
                    "/missing.txt",
                ]),
            )

            shell.execute("bash /bad.sh")

            rendered = output.getvalue()
            self.assertIn("bash: /bad.sh:2-3", rendered)
            self.assertIn("cat: no such file or directory: /missing.txt", rendered)
        finally:
            temp_dir.cleanup()

    def test_bash_exit_stops_script_only(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            self.write_script(
                shell,
                "/stop.sh",
                "\n".join([
                    "login root",
                    "exit",
                    "touch /after.txt",
                ]),
            )

            shell.execute("bash /stop.sh")
            shell.execute("whoami")

            with self.assertRaises(FileSystemError):
                shell.fs.read_file("/after.txt")
            self.assertIn("bash: script stopped by exit at /stop.sh:2", output.getvalue())
            self.assertIn("root", output.getvalue())
        finally:
            temp_dir.cleanup()

    def test_bash_missing_script_reports_not_found(self):
        temp_dir, shell, output = self.make_shell()
        try:
            shell.execute("format")
            shell.execute("bash /missing.sh")

            self.assertIn("bash: no such file or directory: /missing.sh", output.getvalue())
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
