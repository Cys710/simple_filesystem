import io
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.shell import Shell


class TestShellFriendlyErrors(unittest.TestCase):
    def make_shell(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        output = io.StringIO()
        shell = Shell(disk_path, output=output)
        return temp_dir, shell, output

    def test_unknown_command_suggests_similar_command(self):
        temp_dir, shell, output = self.make_shell()
        try:
            shell.execute("loggin root")

            rendered = output.getvalue()
            self.assertIn("loggin: command not found", rendered)
            self.assertIn("Did you mean 'login'?", rendered)
        finally:
            temp_dir.cleanup()

    def test_mount_missing_disk_reports_not_found(self):
        temp_dir, shell, output = self.make_shell()
        try:
            shell.execute("mount missing.img")

            self.assertIn("mount: disk image not found", output.getvalue())
        finally:
            temp_dir.cleanup()

    def test_login_before_mount_reports_mount_hint(self):
        temp_dir, shell, output = self.make_shell()
        try:
            shell.execute("login root")

            self.assertIn(
                "login: no file system mounted. Please run 'mount' or 'format' first.",
                output.getvalue(),
            )
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
