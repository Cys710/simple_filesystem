import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "src"))

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from disk import Disk, format_disk, open_disk, read_block
from inode_io import (
    INODE_BLOCK_START_ID,
    INODE_SIZE,
    INODES_PER_BLOCK,
    InodeDiskMixin,
    InodeIOError,
    clear_inode_slot,
    locate_inode,
    read_inode,
    write_inode,
)


@dataclass
class DemoInode:
    inode_id: int
    user_id: int
    is_dir: bool = False
    size: int = 0

class InodeDisk(InodeDiskMixin, Disk):
    pass

class TestInodeIO(unittest.TestCase):
    def test_locate_inode_first_block(self):
        self.assertEqual(locate_inode(0), (INODE_BLOCK_START_ID, 0, 0))
        self.assertEqual(locate_inode(1), (INODE_BLOCK_START_ID, 1, INODE_SIZE))
        self.assertEqual(
            locate_inode(15),
            (INODE_BLOCK_START_ID, 15, 15 * INODE_SIZE),
        )

    def test_locate_inode_next_block(self):
        self.assertEqual(locate_inode(16), (INODE_BLOCK_START_ID + 1, 0, 0))
        self.assertEqual(
            locate_inode(17),
            (INODE_BLOCK_START_ID + 1, 1, INODE_SIZE),
        )

    def test_write_and_read_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            inode = DemoInode(inode_id=3, user_id=1000, is_dir=True)

            with open_disk(path) as fp:
                write_inode(fp, inode.inode_id, inode)

            with open_disk(path) as fp:
                restored = read_inode(fp, inode.inode_id)

            self.assertEqual(restored, inode)

    def test_neighbor_inode_slots_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            inode_a = DemoInode(inode_id=0, user_id=1)
            inode_b = DemoInode(inode_id=1, user_id=2)

            with open_disk(path) as fp:
                write_inode(fp, 0, inode_a)
                write_inode(fp, 1, inode_b)

            with open_disk(path) as fp:
                self.assertEqual(read_inode(fp, 0), inode_a)
                self.assertEqual(read_inode(fp, 1), inode_b)

    def test_inode_16_is_written_to_next_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            inode = DemoInode(inode_id=INODES_PER_BLOCK, user_id=3)

            with open_disk(path) as fp:
                write_inode(fp, inode.inode_id, inode)
                first_inode_block = read_block(fp, INODE_BLOCK_START_ID)
                second_inode_block = read_block(fp, INODE_BLOCK_START_ID + 1)

            self.assertEqual(first_inode_block, b"\x00" * len(first_inode_block))
            self.assertNotEqual(second_inode_block, b"\x00" * len(second_inode_block))

    def test_clear_inode_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            inode = DemoInode(inode_id=2, user_id=4)

            with open_disk(path) as fp:
                write_inode(fp, 2, inode)
                clear_inode_slot(fp, 2)

                with self.assertRaises(InodeIOError):
                    read_inode(fp, 2)

    def test_invalid_inode_id(self):
        with self.assertRaises(InodeIOError):
            locate_inode(-1)

    def test_inode_disk_mixin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            disk = InodeDisk(path)
            disk.format()
            inode = DemoInode(inode_id=4, user_id=5)

            with disk:
                disk.write_inode(inode.inode_id, inode)
                self.assertEqual(disk.read_inode(inode.inode_id), inode)
                disk.clear_inode_slot(inode.inode_id)
                with self.assertRaises(InodeIOError):
                    disk.read_inode(inode.inode_id)


if __name__ == "__main__":
    unittest.main()
