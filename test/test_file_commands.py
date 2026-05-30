import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from core.file_system import FileSystem, FileSystemError


class TestFileCommands(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, disk_path, fs

    def test_write_append_cat_survive_remount(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fs.touch("/note.txt")
            fs.write_file("/note.txt", "hello")
            fs.write_file("/note.txt", " world", append=True)

            self.assertEqual(fs.read_file("/note.txt"), b"hello world")

            remounted = FileSystem.mount(disk_path)
            self.assertEqual(remounted.read_file("/note.txt"), b"hello world")
        finally:
            temp_dir.cleanup()

    def test_rm_removes_file_and_releases_inode(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            before = fs.super_block.free_inode_cnt
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "hello")
            after_create = fs.super_block.free_inode_cnt

            fs.remove("/a.txt")

            self.assertLess(after_create, before)
            self.assertEqual(fs.super_block.free_inode_cnt, before)
            self.assertEqual(fs.ls("/"), [])
            with self.assertRaises(FileSystemError):
                fs.read_file("/a.txt")
        finally:
            temp_dir.cleanup()

    def test_rmdir_removes_empty_dir(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            before = fs.super_block.free_inode_cnt
            fs.mkdir("/empty")
            fs.rmdir("/empty")

            self.assertEqual(fs.super_block.free_inode_cnt, before)
            self.assertEqual(fs.ls("/"), [])
        finally:
            temp_dir.cleanup()

    def test_rmdir_rejects_non_empty_dir(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/parent")
            fs.touch("/parent/a.txt")

            with self.assertRaises(FileSystemError):
                fs.rmdir("/parent")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
