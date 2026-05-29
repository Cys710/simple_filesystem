import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "src"))

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from disk import BLOCK_SIZE, format_disk, open_disk
from object_io import (
    ObjectDisk,
    pack_object,
    read_object,
    unpack_object,
    write_object,
    ObjectIOError,
)

@dataclass
class DemoObject:
    name: str
    values: list[int]


class TestObjectIO(unittest.TestCase):
    def test_pack_and_unpack_object(self):
        obj = DemoObject("root", [1, 2, 3])

        packed = pack_object(obj)
        restored = unpack_object(packed)

        self.assertEqual(len(packed), BLOCK_SIZE)
        self.assertEqual(restored, obj)

    def test_write_and_read_single_block_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            obj = {"type": "group", "stack": [1, 2, 3], "count": 3}

            with open_disk(path) as fp:
                write_object(fp, 5, obj)

            with open_disk(path) as fp:
                restored = read_object(fp, 5)

            self.assertEqual(restored, obj)

    def test_write_and_read_multi_block_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            format_disk(path)
            obj = {"text": "x" * (BLOCK_SIZE + 200)}

            with open_disk(path) as fp:
                write_object(fp, 20, obj, block_count=2)

            with open_disk(path) as fp:
                restored = read_object(fp, 20, block_count=2)

            self.assertEqual(restored, obj)

    def test_reject_object_too_large_for_block_count(self):
        obj = {"text": "x" * BLOCK_SIZE}

        with self.assertRaises(ObjectIOError):
            pack_object(obj, block_count=1)

    def test_reject_corrupt_empty_object_block(self):
        with self.assertRaises(ObjectIOError):
            unpack_object(b"\x00" * BLOCK_SIZE)

    def test_object_disk_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FS.pfs"
            disk = ObjectDisk(path)
            disk.format()

            with disk:
                disk.write_object(7, DemoObject("home", [4, 5]))
                restored = disk.read_object(7)

            self.assertEqual(restored, DemoObject("home", [4, 5]))


if __name__ == "__main__":
    unittest.main()
