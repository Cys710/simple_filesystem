import io
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from cli.shell import Shell
from user import DEFAULT_ROOT_PASSWORD


class TestShellPasswordPrompts(unittest.TestCase):
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

    def test_login_reads_hidden_password(self):
        temp_dir, shell, output = self.make_shell([DEFAULT_ROOT_PASSWORD])
        try:
            shell.execute("format")
            shell.execute("login root")

            self.assertEqual(shell.fs.whoami(), "root")
            self.assertIn("logged in as root", output.getvalue())
        finally:
            temp_dir.cleanup()

    def test_useradd_and_su_read_hidden_passwords(self):
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
            shell.execute("su alice")

            self.assertEqual(shell.fs.whoami(), "alice")
            self.assertEqual(shell.fs.pwd(), "/home/alice")
        finally:
            temp_dir.cleanup()

    def test_passwd_rejects_mismatched_confirmation(self):
        temp_dir, shell, output = self.make_shell([
            DEFAULT_ROOT_PASSWORD,
            "first",
            "second",
        ])
        try:
            shell.execute("format")
            shell.execute("login root")
            shell.execute("passwd root")

            self.assertIn("passwords do not match", output.getvalue())
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
