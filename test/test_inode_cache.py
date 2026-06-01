import io
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from core.file_system import FileSystem, FileSystemError
from core.format_disk import format_disk
from core.inode_cache import InodeBusyError, InodeCache
from cli.shell import Shell
from dataStruct import Inode
from storage.disk import open_disk
from storage.inode_io import read_inode, write_inode


class TestInodeCache(unittest.TestCase):
    def make_cache(self, *, max_entries=128):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        format_disk(disk_path)
        with open_disk(disk_path) as fp:
            write_inode(fp, 1, Inode(1, 0))
            write_inode(fp, 129, Inode(129, 0))
        return temp_dir, disk_path, InodeCache(disk_path, max_entries=max_entries)

    def test_iget_reuses_cached_object_and_iput_releases_reference(self):
        temp_dir, _disk_path, cache = self.make_cache()
        try:
            first = cache.iget(1)
            second = cache.iget(1)

            self.assertIs(first, second)
            self.assertEqual(first.ref_count, 2)

            cache.iput(first)
            cache.iput(second)
            self.assertEqual(first.ref_count, 0)
        finally:
            temp_dir.cleanup()

    def test_hash_collisions_are_linked_in_same_bucket(self):
        temp_dir, _disk_path, cache = self.make_cache()
        try:
            first = cache.iget(1)
            second = cache.iget(129)

            self.assertEqual(cache.bucket_index(1), cache.bucket_index(129))
            self.assertIs(cache.buckets[1], second)
            self.assertIs(second.hash_next, first)
            self.assertIs(first.hash_prev, second)

            cache.iput(first)
            cache.iput(second)
        finally:
            temp_dir.cleanup()

    def test_dirty_inode_is_written_back_when_last_reference_is_released(self):
        temp_dir, disk_path, cache = self.make_cache()
        try:
            memory_inode = cache.iget(1)
            memory_inode.inode.size = 123
            cache.mark_dirty(memory_inode)
            cache.iput(memory_inode)

            with open_disk(disk_path) as fp:
                self.assertEqual(read_inode(fp, 1).size, 123)
        finally:
            temp_dir.cleanup()

    def test_full_cache_evicts_unused_inode(self):
        temp_dir, _disk_path, cache = self.make_cache(max_entries=1)
        try:
            first = cache.iget(1)
            cache.iput(first)
            second = cache.iget(129)

            self.assertNotIn(1, cache.entries)
            self.assertIn(129, cache.entries)
            cache.iput(second)
        finally:
            temp_dir.cleanup()

    def test_read_locks_are_shared_and_write_lock_is_exclusive(self):
        temp_dir, _disk_path, cache = self.make_cache()
        try:
            memory_inode = cache.iget(1)
            cache.acquire_read(memory_inode, 3)
            cache.acquire_read(memory_inode, 4)

            with self.assertRaises(InodeBusyError):
                cache.acquire_write(memory_inode, 5)

            cache.release_access(memory_inode, 3)
            cache.release_access(memory_inode, 4)
            cache.acquire_write(memory_inode, 5)

            with self.assertRaises(InodeBusyError):
                cache.acquire_read(memory_inode, 6)

            cache.release_access(memory_inode, 5)
            cache.iput(memory_inode)
        finally:
            temp_dir.cleanup()


class TestFileSystemInodeLocks(unittest.TestCase):
    def make_fs(self):
        temp_dir = tempfile.TemporaryDirectory()
        disk_path = os.path.join(temp_dir.name, "disk.img")
        fs = FileSystem.format_and_mount(disk_path)
        fs.write_file("/note.txt", "hello")
        return temp_dir, disk_path, fs

    def test_multiple_read_fds_share_memory_inode(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            first_fd = fs.open("/note.txt", "r")
            second_fd = fs.open("/note.txt", "r")

            first = fs.open_file_table[first_fd]
            second = fs.open_file_table[second_fd]
            self.assertIs(first.memory_inode, second.memory_inode)
            self.assertEqual(first.memory_inode.reader_holders, {first_fd, second_fd})

            fs.close(first_fd)
            fs.close(second_fd)
        finally:
            temp_dir.cleanup()

    def test_readers_block_writer_until_all_read_fds_are_closed(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            first_fd = fs.open("/note.txt", "r")
            second_fd = fs.open("/note.txt", "r")

            with self.assertRaisesRegex(FileSystemError, "locked for reading"):
                fs.open("/note.txt", "w")

            fs.close(first_fd)
            fs.close(second_fd)
            writer_fd = fs.open("/note.txt", "w")
            fs.close(writer_fd)
        finally:
            temp_dir.cleanup()

    def test_writer_blocks_readers_until_close(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            writer_fd = fs.open("/note.txt", "a")

            with self.assertRaisesRegex(FileSystemError, "locked for writing"):
                fs.open("/note.txt", "r")

            fs.close(writer_fd)
            reader_fd = fs.open("/note.txt", "r")
            fs.close(reader_fd)
        finally:
            temp_dir.cleanup()

    def test_remove_rejects_open_file(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/note.txt", "r")

            with self.assertRaisesRegex(FileSystemError, "still in use"):
                fs.remove("/note.txt")

            fs.close(fd)
            fs.remove("/note.txt")
        finally:
            temp_dir.cleanup()

    def test_sync_persists_dirty_inode_while_fd_remains_open(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/note.txt", "a")
            fs.write(fd, " world")
            memory_inode = fs.open_file_table[fd].memory_inode
            self.assertTrue(memory_inode.dirty)

            fs.sync()
            self.assertFalse(memory_inode.dirty)
            remounted = FileSystem.mount(disk_path)
            self.assertEqual(remounted.read_file("/note.txt"), b"hello world")

            fs.close(fd)
        finally:
            temp_dir.cleanup()

    def test_rmdir_rejects_current_directory(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/docs")
            fs.cd("/docs")

            with self.assertRaisesRegex(FileSystemError, "current directory"):
                fs.rmdir("/docs")
        finally:
            temp_dir.cleanup()

    def test_cp_rejects_source_locked_for_writing(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fd = fs.open("/note.txt", "a")

            with self.assertRaisesRegex(FileSystemError, "locked for writing"):
                fs.cp("/note.txt", "/copy.txt")

            fs.close(fd)
        finally:
            temp_dir.cleanup()

    def test_overwrite_operations_reject_open_target_file(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.write_file("/source.txt", "new")
            fs.write_file("/target.txt", "old")
            fd = fs.open("/target.txt", "r")

            with self.assertRaisesRegex(FileSystemError, "still in use"):
                fs.cp("/source.txt", "/target.txt", overwrite=True)
            with self.assertRaisesRegex(FileSystemError, "still in use"):
                fs.mv("/source.txt", "/target.txt", overwrite=True)
            with self.assertRaisesRegex(FileSystemError, "still in use"):
                fs.rename("/source.txt", "target.txt", overwrite=True)

            fs.close(fd)
        finally:
            temp_dir.cleanup()


class TestShellInodeCacheLifecycle(unittest.TestCase):
    def test_exit_closes_open_fds_and_flushes_dirty_inode(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            disk_path = os.path.join(temp_dir.name, "disk.img")
            shell = Shell(disk_path, output=io.StringIO())
            shell.execute("format")
            shell.fs.write_file("/note.txt", "hello")
            fd = shell.fs.open("/note.txt", "a")
            shell.fs.write(fd, " world")
            mounted = shell.fs

            self.assertFalse(shell.execute("exit"))
            self.assertIsNone(shell.fs)
            self.assertEqual(mounted.open_file_table, {})
            self.assertEqual(FileSystem.mount(disk_path).read_file("/note.txt"), b"hello world")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
