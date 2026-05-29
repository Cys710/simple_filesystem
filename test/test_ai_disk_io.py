import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import tempfile
import unittest
from pathlib import Path

from disk import (
    BLOCK_SIZE,
    DISK_SIZE,
    Disk,
    DiskError,
    create_disk,
    format_disk,
    open_disk,
    read_block,
    write_block,
)

class TestDiskIO(unittest.TestCase):
    def test_create_disk_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"

            create_disk(path)

            self.assertEqual(path.stat().st_size, DISK_SIZE)

    def test_write_and_read_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)

            with open_disk(path) as fp:
                write_block(fp, 10, b"hello")

            with open_disk(path) as fp:
                block = read_block(fp, 10)

            self.assertEqual(block[:5], b"hello")
            self.assertEqual(block[5:], b"\x00" * (BLOCK_SIZE - 5))

    def test_reject_out_of_range_block_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)

            with open_disk(path) as fp:
                with self.assertRaises(DiskError):
                    read_block(fp, -1)
                with self.assertRaises(DiskError):
                    write_block(fp, 1024, b"")

    def test_reject_data_larger_than_one_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)

            with open_disk(path) as fp:
                with self.assertRaises(DiskError):
                    write_block(fp, 0, b"x" * (BLOCK_SIZE + 1))

    def test_disk_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            disk = Disk(path)
            disk.format()

            with disk:
                disk.write_block(3, b"abc")
                self.assertEqual(disk.read_block(3)[:3], b"abc")


if __name__ == "__main__":
    unittest.main()
