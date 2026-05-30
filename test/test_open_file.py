import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from core.file_system import FileSystem, FileSystemError


class TestOpenFileTable(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        return temp_dir, disk_path, fs

    def test_open_write_close_read_survives_remount(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/a.txt", "w")
            self.assertEqual(fs.write(fd, "hello"), 5)
            fs.close(fd)
            self.assertEqual(fs.open_file_table, {})

            fd = fs.open("/a.txt", "r")
            self.assertEqual(fs.read(fd), b"hello")
            fs.close(fd)

            remounted = FileSystem.mount(disk_path)
            self.assertEqual(remounted.read_file("/a.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_close_invalidates_fd(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/a.txt", "w")
            fs.close(fd)

            with self.assertRaises(FileSystemError):
                fs.write(fd, "x")
            with self.assertRaises(FileSystemError):
                fs.close(fd)
        finally:
            temp_dir.cleanup()

    def test_read_and_write_modes_are_enforced(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/a.txt", "w")
            with self.assertRaises(FileSystemError):
                fs.read(fd)
            fs.close(fd)

            fd = fs.open("/a.txt", "r")
            with self.assertRaises(FileSystemError):
                fs.write(fd, "x")
            fs.close(fd)
        finally:
            temp_dir.cleanup()

    def test_seek_and_partial_read_write(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/a.txt", "w+")
            fs.write(fd, "hello")
            fs.seek(fd, 1)
            self.assertEqual(fs.read(fd, 2), b"el")
            fs.seek(fd, 1)
            fs.write(fd, "A")
            fs.close(fd)

            self.assertEqual(fs.read_file("/a.txt"), b"hAllo")
        finally:
            temp_dir.cleanup()

    def test_append_opens_at_end(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.write_file("/a.txt", "hello")

            fd = fs.open("/a.txt", "a")
            fs.write(fd, " world")
            fs.close(fd)

            self.assertEqual(fs.read_file("/a.txt"), b"hello world")
        finally:
            temp_dir.cleanup()

    def test_multiple_fds_keep_independent_offsets(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.write_file("/a.txt", "abcdef")

            fd1 = fs.open("/a.txt", "r")
            fd2 = fs.open("/a.txt", "r")

            self.assertEqual(fs.read(fd1, 2), b"ab")
            self.assertEqual(fs.read(fd1, 2), b"cd")
            self.assertEqual(fs.read(fd2, 3), b"abc")

            fs.close(fd1)
            fs.close(fd2)
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
