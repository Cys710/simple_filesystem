import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from core.file_system import FileSystem, FileSystemError
from head import ROOT_ID
from user import DEFAULT_ROOT_PASSWORD


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
            fs.login("root", DEFAULT_ROOT_PASSWORD)
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
                fs.login("missing", DEFAULT_ROOT_PASSWORD)
        finally:
            temp_dir.cleanup()

    def test_root_user_survives_remount(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            self.assertEqual(fs.whoami(), "root")

            remounted = FileSystem.mount(disk_path)
            remounted.login("root", DEFAULT_ROOT_PASSWORD)
            self.assertEqual(remounted.whoami(), "root")
        finally:
            temp_dir.cleanup()

    def test_new_inode_owner_uses_current_user(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.touch("/owned.txt")

            inode, _dir_block = fs._resolve_path("/owned.txt")
            self.assertEqual(inode.user_id, ROOT_ID)
        finally:
            temp_dir.cleanup()

    def test_root_can_add_user_with_home_dir(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            user_id = fs.useradd("alice", "alice-pass")

            self.assertEqual(user_id, 1)
            self.assertEqual(fs.users(), ["root", "alice"])
            home_inode, home_dir = fs._resolve_dir("/home/alice")
            self.assertTrue(home_inode.is_dir)
            self.assertEqual(home_dir.name, "alice")
            self.assertEqual(home_inode.user_id, ROOT_ID)
        finally:
            temp_dir.cleanup()

    def test_non_root_cannot_add_or_list_users(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.login("alice", "alice-pass")

            with self.assertRaises(FileSystemError):
                fs.useradd("bob", "bob-pass")
            with self.assertRaises(FileSystemError):
                fs.users()
        finally:
            temp_dir.cleanup()

    def test_passwd_updates_password_and_survives_remount(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "old-pass")
            fs.passwd("alice", "new-pass")

            with self.assertRaises(FileSystemError):
                fs.login("alice", "old-pass")
            fs.login("alice", "new-pass")

            remounted = FileSystem.mount(disk_path)
            remounted.login("alice", "new-pass")
            self.assertEqual(remounted.whoami(), "alice")
        finally:
            temp_dir.cleanup()

    def test_user_can_only_change_own_password(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.useradd("bob", "bob-pass")
            fs.login("alice", "alice-pass")

            fs.passwd("alice", "alice-new")
            with self.assertRaises(FileSystemError):
                fs.passwd("bob", "bob-new")

            fs.login("alice", "alice-new")
        finally:
            temp_dir.cleanup()

    def test_su_switches_user_and_home_directory(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")

            fs.su("alice", "alice-pass")

            self.assertEqual(fs.whoami(), "alice")
            self.assertEqual(fs.pwd(), "/home/alice")
            fs.touch("note.txt")
            inode, _dir_block = fs._resolve_path("/home/alice/note.txt")
            self.assertEqual(inode.user_id, 1)
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
