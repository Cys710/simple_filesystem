import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)

from head import BLOCK_SIZE, DIRECT_CNT, MAX_DIR_ENTRY_COUNT
from storage.object_io import pack_object
from core.file_system import FileSystem, FileSystemError, MAX_INDIRECT_BLOCK_IDS
from user import DEFAULT_ROOT_PASSWORD
from utils import INDIRECT_INDEX_TEST_BYTES, append_test_data


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

    def test_write_reads_through_single_indirect_blocks(self):
        temp_dir, disk_path, fs = self.make_fs()
        try:
            fs.touch("/big.bin")
            payload = b"x" * (DIRECT_CNT * BLOCK_SIZE + 123)

            fs.write_file("/big.bin", payload)

            self.assertEqual(fs.read_file("/big.bin"), payload)

            inode, _dir_block = fs._resolve_path("/big.bin")
            self.assertEqual(len(inode.direct_blocks), DIRECT_CNT)
            self.assertIsNotNone(inode.indirect_block)

            remounted = FileSystem.mount(disk_path)
            self.assertEqual(remounted.read_file("/big.bin"), payload)
        finally:
            temp_dir.cleanup()

    def test_indirect_capacity_is_conservative_for_object_io(self):
        self.assertGreaterEqual(MAX_INDIRECT_BLOCK_IDS, 1)
        pack_object(list(range(MAX_INDIRECT_BLOCK_IDS)))

    def test_append_test_data_crosses_single_indirect_boundary(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            written = append_test_data(fs, "/demo.bin")

            inode, _dir_block = fs._resolve_path("/demo.bin")
            self.assertEqual(written, INDIRECT_INDEX_TEST_BYTES)
            self.assertEqual(inode.size, DIRECT_CNT * BLOCK_SIZE)
            self.assertEqual(len(inode.direct_blocks), DIRECT_CNT)
            self.assertIsNone(inode.indirect_block)

            append_test_data(fs, "/demo.bin", 1)

            inode, _dir_block = fs._resolve_path("/demo.bin")
            self.assertEqual(inode.size, DIRECT_CNT * BLOCK_SIZE + 1)
            self.assertIsNotNone(inode.indirect_block)
        finally:
            temp_dir.cleanup()

    def test_cp_copies_file_and_keeps_source(self):
        """cp: 复制文件后目标内容一致，源文件仍存在。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "hello")

            fs.cp("/a.txt", "/b.txt")

            self.assertEqual(fs.read_file("/a.txt"), b"hello")
            self.assertEqual(fs.read_file("/b.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_cp_to_directory_uses_source_basename(self):
        """cp: 复制到目录时使用源文件 basename。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dir")
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "hello")

            fs.cp("/a.txt", "/dir")

            self.assertEqual(fs.read_file("/dir/a.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_cp_copies_directory_tree(self):
        """cp: 递归复制目录，保留目录结构。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dir")
            fs.mkdir("/dir/sub")
            fs.touch("/dir/a.txt")
            fs.write_file("/dir/a.txt", "hello")
            fs.touch("/dir/sub/b.txt")
            fs.write_file("/dir/sub/b.txt", "world")

            fs.cp("/dir", "/copy")

            self.assertEqual(fs.read_file("/copy/a.txt"), b"hello")
            self.assertEqual(fs.read_file("/copy/sub/b.txt"), b"world")
            self.assertEqual(fs.read_file("/dir/a.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_cp_copies_directory_into_existing_directory(self):
        """cp: 复制目录到已存在目录下，应创建同名子目录。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dir1")
            fs.touch("/dir1/a.txt")
            fs.write_file("/dir1/a.txt", "hello")
            fs.mkdir("/dst")

            fs.cp("/dir1", "/dst")

            self.assertEqual(fs.read_file("/dst/dir1/a.txt"), b"hello")
        finally:
            temp_dir.cleanup()

    def test_cp_rejects_missing_source(self):
        """cp: 源不存在应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            with self.assertRaises(FileSystemError):
                fs.cp("/missing.txt", "/b.txt")
        finally:
            temp_dir.cleanup()

    def test_cp_overwrite_requires_flag(self):
        """cp: 目标已存在时，未指定 overwrite 应报错；指定 overwrite 则覆盖。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "new")
            fs.touch("/b.txt")
            fs.write_file("/b.txt", "old")

            with self.assertRaises(FileSystemError):
                fs.cp("/a.txt", "/b.txt")

            fs.cp("/a.txt", "/b.txt", overwrite=True)
            self.assertEqual(fs.read_file("/b.txt"), b"new")
        finally:
            temp_dir.cleanup()

    def test_cp_permission_denied_on_destination_directory(self):
        """cp: 目标目录无权限（x/w）应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.useradd("bob", "bob-pass")

            fs.su("alice", "alice-pass")
            fs.write_file("note.txt", "hello")

            with self.assertRaises(FileSystemError):
                fs.cp("/home/alice/note.txt", "/home/bob")
        finally:
            temp_dir.cleanup()

    def test_mv_renames_in_same_directory(self):
        """mv: 同一目录内改名，源消失，目标出现。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "hello")

            fs.mv("/a.txt", "/b.txt")

            self.assertEqual(fs.read_file("/b.txt"), b"hello")
            with self.assertRaises(FileSystemError):
                fs.read_file("/a.txt")
        finally:
            temp_dir.cleanup()

    def test_mv_moves_across_directories(self):
        """mv: 跨目录移动，目标目录内出现文件。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dir1")
            fs.mkdir("/dir2")
            fs.touch("/dir1/a.txt")
            fs.write_file("/dir1/a.txt", "hello")

            fs.mv("/dir1/a.txt", "/dir2")

            self.assertEqual(fs.read_file("/dir2/a.txt"), b"hello")
            with self.assertRaises(FileSystemError):
                fs.read_file("/dir1/a.txt")
        finally:
            temp_dir.cleanup()

    def test_mv_overwrite_requires_flag(self):
        """mv: 目标已存在时，未指定 overwrite 应报错；指定 overwrite 则覆盖并移动。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "new")
            fs.touch("/b.txt")
            fs.write_file("/b.txt", "old")

            with self.assertRaises(FileSystemError):
                fs.mv("/a.txt", "/b.txt")

            fs.mv("/a.txt", "/b.txt", overwrite=True)
            self.assertEqual(fs.read_file("/b.txt"), b"new")
            with self.assertRaises(FileSystemError):
                fs.read_file("/a.txt")
        finally:
            temp_dir.cleanup()

    def test_mv_moves_directory(self):
        """mv: 支持移动目录（跨目录）。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dir1")
            fs.mkdir("/dir1/sub")
            fs.touch("/dir1/sub/a.txt")
            fs.write_file("/dir1/sub/a.txt", "hello")
            fs.mkdir("/dir2")

            fs.mv("/dir1/sub", "/dir2")

            self.assertEqual(fs.read_file("/dir2/sub/a.txt"), b"hello")
            with self.assertRaises(FileSystemError):
                fs._resolve_dir("/dir1/sub")
        finally:
            temp_dir.cleanup()

    def test_mv_rejects_missing_source(self):
        """mv: 源不存在应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            with self.assertRaises(FileSystemError):
                fs.mv("/missing.txt", "/b.txt")
        finally:
            temp_dir.cleanup()

    def test_mv_permission_denied_without_write_on_source_parent(self):
        """mv: 源父目录无写权限（w）时，应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.useradd("bob", "bob-pass")

            fs.mkdir("/shared")
            fs.chmod("/shared", "77")

            fs.su("alice", "alice-pass")
            fs.touch("/shared/a.txt")
            fs.write_file("/shared/a.txt", "hello")
            fs.chmod("/shared/a.txt", "64")

            fs.su("root", DEFAULT_ROOT_PASSWORD)
            fs.chmod("/shared", "75")

            fs.su("bob", "bob-pass")
            with self.assertRaises(FileSystemError):
                fs.mv("/shared/a.txt", "/shared/b.txt")
        finally:
            temp_dir.cleanup()

    def test_rename_file_in_same_parent(self):
        """rename: 同一父目录内重命名文件。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "hello")

            fs.rename("/a.txt", "b.txt")

            self.assertEqual(fs.read_file("/b.txt"), b"hello")
            with self.assertRaises(FileSystemError):
                fs.read_file("/a.txt")
        finally:
            temp_dir.cleanup()

    def test_rename_directory_in_same_parent(self):
        """rename: 同一父目录内重命名目录。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/d1")
            fs.rename("/d1", "d2")
            inode, _dir = fs._resolve_dir("/d2")
            self.assertTrue(inode.is_dir)
            with self.assertRaises(FileSystemError):
                fs._resolve_dir("/d1")
        finally:
            temp_dir.cleanup()

    def test_rename_rejects_invalid_new_name(self):
        """rename: new_name 为空或包含路径分隔符应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            with self.assertRaises(FileSystemError):
                fs.rename("/a.txt", "")
            with self.assertRaises(FileSystemError):
                fs.rename("/a.txt", "x/y.txt")
        finally:
            temp_dir.cleanup()

    def test_rename_overwrite_requires_flag(self):
        """rename: 目标已存在时，未指定 overwrite 应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.touch("/b.txt")
            with self.assertRaises(FileSystemError):
                fs.rename("/a.txt", "b.txt")
        finally:
            temp_dir.cleanup()

    def test_rename_overwrite_replaces_file(self):
        """rename: overwrite=True 时覆盖目标文件。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/a.txt")
            fs.write_file("/a.txt", "new")
            fs.touch("/b.txt")
            fs.write_file("/b.txt", "old")

            fs.rename("/a.txt", "b.txt", overwrite=True)

            self.assertEqual(fs.read_file("/b.txt"), b"new")
            with self.assertRaises(FileSystemError):
                fs.read_file("/a.txt")
        finally:
            temp_dir.cleanup()

    def test_rename_cannot_rename_root_directory(self):
        """rename: 根目录不可重命名。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            with self.assertRaises(FileSystemError):
                fs.rename("/", "root2")
        finally:
            temp_dir.cleanup()

    def test_rename_permission_denied_without_write_on_parent(self):
        """rename: 父目录无写权限（w）时，应报错。"""
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.login("root", DEFAULT_ROOT_PASSWORD)
            fs.useradd("alice", "alice-pass")
            fs.useradd("bob", "bob-pass")

            fs.mkdir("/shared")
            fs.chmod("/shared", "77")

            fs.su("alice", "alice-pass")
            fs.touch("/shared/a.txt")
            fs.write_file("/shared/a.txt", "hello")
            fs.chmod("/shared/a.txt", "64")

            fs.su("root", DEFAULT_ROOT_PASSWORD)
            fs.chmod("/shared", "75")

            fs.su("bob", "bob-pass")
            with self.assertRaises(FileSystemError):
                fs.rename("/shared/a.txt", "b.txt")
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

    def test_rmdir_recursive_removes_directory_tree(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            before = fs.super_block.free_inode_cnt
            fs.mkdir("/parent")
            fs.mkdir("/parent/child")
            fs.touch("/parent/child/a.txt")
            fs.write_file("/parent/child/a.txt", "hello")

            with self.assertRaises(FileSystemError):
                fs.rmdir("/parent")

            fs.rmdir("/parent", recursive=True)

            self.assertEqual(fs.super_block.free_inode_cnt, before)
            self.assertEqual(fs.ls("/"), [])
        finally:
            temp_dir.cleanup()

    def test_touch_rejects_when_directory_entry_limit_is_reached(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            for index in range(MAX_DIR_ENTRY_COUNT):
                fs.touch(f"/file{index}.txt")

            with self.assertRaisesRegex(FileSystemError, f"max {MAX_DIR_ENTRY_COUNT} entries"):
                fs.touch("/overflow.txt")
        finally:
            temp_dir.cleanup()

    def test_link_rejects_when_directory_entry_limit_is_reached(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.touch("/source.txt")
            for index in range(MAX_DIR_ENTRY_COUNT - 1):
                fs.touch(f"/file{index}.txt")

            with self.assertRaisesRegex(FileSystemError, f"max {MAX_DIR_ENTRY_COUNT} entries"):
                fs.link("/source.txt", "/source-link.txt")
        finally:
            temp_dir.cleanup()

    def test_cp_rejects_when_destination_directory_entry_limit_is_reached(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/dst")
            fs.touch("/source.txt")
            fs.write_file("/source.txt", "hello")
            for index in range(MAX_DIR_ENTRY_COUNT):
                fs.touch(f"/dst/file{index}.txt")

            with self.assertRaisesRegex(FileSystemError, f"max {MAX_DIR_ENTRY_COUNT} entries"):
                fs.cp("/source.txt", "/dst")
        finally:
            temp_dir.cleanup()

    def test_mv_rejects_when_destination_directory_entry_limit_is_reached(self):
        temp_dir, _disk_path, fs = self.make_fs()
        try:
            fs.mkdir("/src")
            fs.mkdir("/dst")
            fs.touch("/src/source.txt")
            fs.write_file("/src/source.txt", "hello")
            for index in range(MAX_DIR_ENTRY_COUNT):
                fs.touch(f"/dst/file{index}.txt")

            with self.assertRaisesRegex(FileSystemError, f"max {MAX_DIR_ENTRY_COUNT} entries"):
                fs.mv("/src/source.txt", "/dst")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
