import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")
DATA = os.path.join(SRC, "data")

sys.path.insert(0, SRC)
sys.path.insert(0, DATA)

from dataStruct import SuperBlock
from src.dataStruct.groupList import GroupList
from head import BLOCK_SIZE, DATA_BLOCK_NUM, DATA_BLOCK_START_ID, FREE_BLOCK_CNT


class GroupLinkTestCase(unittest.TestCase):
    def make_super_block(self):
        fp = tempfile.TemporaryFile(mode="w+b")
        sp = SuperBlock()
        sp.init_data_block_group_link(fp)
        return sp, fp


class TestBasicBehavior(GroupLinkTestCase):
    """基础功能测试。"""

    def test_init_free_block_count(self):
        sp, fp = self.make_super_block()
        try:
            self.assertEqual(sp.free_data_block_cnt, DATA_BLOCK_NUM - 1)
            self.assertEqual(sp.block_group_link.stack[-1], 1)
            self.assertNotIn(0, sp.block_group_link.stack[1:])
        finally:
            fp.close()

    def test_allocate_all_blocks_unique(self):
        sp, fp = self.make_super_block()
        try:
            blocks = []

            for _ in range(DATA_BLOCK_NUM - 1):
                blocks.append(sp.get_data_block_id(fp))

            self.assertEqual(len(blocks), DATA_BLOCK_NUM - 1)
            self.assertEqual(len(set(blocks)), DATA_BLOCK_NUM - 1)
            self.assertNotIn(0, blocks)
            self.assertEqual(sp.free_data_block_cnt, 0)

            with self.assertRaises(Exception):
                sp.get_data_block_id(fp)
        finally:
            fp.close()

    def test_free_then_allocate_again(self):
        sp, fp = self.make_super_block()
        try:
            old_blocks = {
                sp.get_data_block_id(fp),
                sp.get_data_block_id(fp),
                sp.get_data_block_id(fp),
            }

            self.assertEqual(sp.free_data_block_cnt, DATA_BLOCK_NUM - 4)

            for block_id in old_blocks:
                sp.free_up_data_block(fp, block_id)

            self.assertEqual(sp.free_data_block_cnt, DATA_BLOCK_NUM - 1)

            new_blocks = {
                sp.get_data_block_id(fp),
                sp.get_data_block_id(fp),
                sp.get_data_block_id(fp),
            }

            self.assertEqual(new_blocks, old_blocks)
        finally:
            fp.close()


class TestEquivalencePartitions(GroupLinkTestCase):
    """等价类划分测试。"""

    def test_allocate_from_non_empty_group(self):
        sp, fp = self.make_super_block()
        try:
            block_id = sp.get_data_block_id(fp)

            self.assertGreater(block_id, 0)
            self.assertEqual(sp.free_data_block_cnt, DATA_BLOCK_NUM - 2)
        finally:
            fp.close()

    def test_allocate_across_group_leader(self):
        sp, fp = self.make_super_block()
        try:
            blocks = [sp.get_data_block_id(fp) for _ in range(FREE_BLOCK_CNT + 1)]

            self.assertEqual(len(blocks), FREE_BLOCK_CNT + 1)
            self.assertEqual(len(set(blocks)), FREE_BLOCK_CNT + 1)
            self.assertNotIn(0, blocks)
        finally:
            fp.close()

    def test_free_to_group_with_space(self):
        sp, fp = self.make_super_block()
        try:
            block_id = sp.get_data_block_id(fp)
            before_count = sp.block_group_link.count

            sp.free_up_data_block(fp, block_id)

            self.assertEqual(sp.block_group_link.count, before_count + 1)
            self.assertEqual(sp.block_group_link.stack[-1], block_id)
        finally:
            fp.close()

    def test_free_to_full_group_creates_new_leader(self):
        fp = tempfile.TemporaryFile(mode="w+b")
        try:
            sp = SuperBlock()
            full_stack = list(range(1, FREE_BLOCK_CNT + 1))
            released_block = FREE_BLOCK_CNT + 1
            sp.block_group_link = GroupList.from_existing_stack(1, full_stack)
            sp.free_data_block_cnt = FREE_BLOCK_CNT

            sp.free_up_data_block(fp, released_block)

            self.assertEqual(sp.block_group_link.stack, [released_block])
            self.assertEqual(sp.block_group_link.count, 1)
            self.assertEqual(sp.free_data_block_cnt, FREE_BLOCK_CNT + 1)

            fp.seek((DATA_BLOCK_START_ID + released_block) * BLOCK_SIZE)
            saved_group = GroupList.from_bytes(fp.read(BLOCK_SIZE))
            self.assertEqual(saved_group.stack, full_stack)
        finally:
            fp.close()

    def test_invalid_free_zero(self):
        sp, fp = self.make_super_block()
        try:
            with self.assertRaises(ValueError):
                sp.free_up_data_block(fp, 0)
        finally:
            fp.close()


class TestBoundaryValues(GroupLinkTestCase):
    """边界值测试。"""

    def test_group_list_empty_stack_boundary(self):
        with self.assertRaises(ValueError):
            GroupList.from_existing_stack(1, [])

    def test_group_list_max_stack_boundary(self):
        stack = list(range(1, FREE_BLOCK_CNT + 1))
        group = GroupList.from_existing_stack(1, stack)

        self.assertEqual(group.count, FREE_BLOCK_CNT)
        self.assertFalse(group.has_free_space())
        with self.assertRaises(Exception):
            group.push(FREE_BLOCK_CNT + 1)

    def test_group_list_over_max_stack_boundary(self):
        stack = list(range(1, FREE_BLOCK_CNT + 2))

        with self.assertRaises(ValueError):
            GroupList.from_existing_stack(1, stack)

    def test_allocate_until_empty_boundary(self):
        sp, fp = self.make_super_block()
        try:
            blocks = [sp.get_data_block_id(fp) for _ in range(DATA_BLOCK_NUM - 1)]

            self.assertEqual(len(blocks), DATA_BLOCK_NUM - 1)
            self.assertEqual(len(set(blocks)), DATA_BLOCK_NUM - 1)
            self.assertNotIn(0, blocks)
            self.assertEqual(sp.free_data_block_cnt, 0)

            with self.assertRaises(Exception):
                sp.get_data_block_id(fp)
        finally:
            fp.close()

    def test_free_min_and_max_valid_block_boundary(self):
        sp, fp = self.make_super_block()
        try:
            sp.block_group_link = GroupList.from_existing_stack(0, [0])
            sp.free_data_block_cnt = 0

            sp.free_up_data_block(fp, 1)
            sp.free_up_data_block(fp, DATA_BLOCK_NUM - 1)

            self.assertEqual(sp.free_data_block_cnt, 2)
            self.assertIn(1, sp.block_group_link.stack)
            self.assertIn(DATA_BLOCK_NUM - 1, sp.block_group_link.stack)
        finally:
            fp.close()


if __name__ == "__main__":
    unittest.main()
