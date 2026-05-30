import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from core.file_system import FileSystem, FileSystemError
from head import ROOT_ID


class TestUserSession(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, disk_path, fs

    def test_default_session_is_guest(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            self.assertEqual(fs.whoami(), "guest")
            self.assertIsNone(fs.current_user)
        finally:
            temp_dir.cleanup()

    def test_root_login_logout(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", "root")
            self.assertEqual(fs.whoami(), "root")
            self.assertEqual(fs.current_user.user_id, ROOT_ID)

            fs.logout()
            self.assertEqual(fs.whoami(), "guest")
            self.assertIsNone(fs.current_user)
        finally:
            temp_dir.cleanup()

    def test_rejects_invalid_login(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            with self.assertRaises(FileSystemError):
                fs.login("root", "bad-password")
            with self.assertRaises(FileSystemError):
                fs.login("missing", "root")
        finally:
            temp_dir.cleanup()

    def test_root_user_survives_remount(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fs.login("root", "root")
            self.assertEqual(fs.whoami(), "root")

            remounted = FileSystem.mount(disk_path)
            remounted.login("root", "root")
            self.assertEqual(remounted.whoami(), "root")
        finally:
            temp_dir.cleanup()

    def test_new_inode_owner_uses_current_user(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", "root")
            fs.touch("/owned.txt")

            inode, _dir_block = fs._resolve_path("/owned.txt")
            self.assertEqual(inode.user_id, ROOT_ID)
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
