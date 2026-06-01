"""
    Text renderers for the full-screen file-system monitor.
"""

from __future__ import annotations

import textwrap

from core.debug_info import (
    BlockMapDebugInfo,
    FileIndexDebugInfo,
    FreeGroupEntry,
    FreeGroupsDebugInfo,
    InodeBitmapDebugInfo,
    MemoryInodeDebugInfo,
)
from head import BLOCK_SIZE, DATA_BLOCK_START_ID, DIRECT_CNT


ROLE_SYMBOL = {
    "SUPER": "S",
    "INODE_AREA": "I",
    "RESERVED": "R",
    "DIR_DATA": "D",
    "FILE_DATA": "F",
    "GROUP_LINK": "G",
    "INDEX_BLOCK": "X",
    "FREE": ".",
    "UNKNOWN": "?",
}


class DiskVisualizer:
    def render_memory_inodes(self, info: MemoryInodeDebugInfo) -> list[str]:
        lines = [
            "Hash chains for cached inodes",
            "",
            "bucket  inode  type  size(B)  refs  dirty  readers  writer",
            "------  -----  ----  -------  ----  -----  -------  ------",
        ]
        for entry in info.entries:
            readers = ",".join(str(fd) for fd in entry.reader_holders) or "-"
            writer = str(entry.writer_holder) if entry.writer_holder is not None else "-"
            lines.append(
                f"{entry.bucket_id:>6}  {entry.inode_id:>5}  {entry.kind:<4}  "
                f"{entry.size:>7}  {entry.ref_count:>4}  "
                f"{'yes' if entry.dirty else 'no':<5}  {readers:<7}  {writer}"
            )
        if not info.entries:
            lines.append("[ empty ]")
        lines.extend([
            "",
            f"Cached inodes: {len(info.entries)} / {info.entry_limit}",
            f"Hash buckets: {info.bucket_count}",
        ])
        return lines

    def render_inode_bitmap(
        self,
        info: InodeBitmapDebugInfo,
        *,
        start: int = 0,
        rows: int | None = None,
    ) -> list[str]:
        lines = [
            "Legend: D dir | F file | . free",
            "",
        ]
        entries = info.entries[start:]
        if rows is not None:
            entries = entries[: rows * 16]
        for offset in range(0, len(entries), 16):
            row = entries[offset : offset + 16]
            symbols = " ".join(self._inode_symbol(entry.kind) for entry in row)
            lines.append(f"{start + offset:04d}: {symbols}")
        lines.extend([
            "",
            f"Used inodes: {info.used}",
            f"Free inodes: {info.free}",
        ])
        return lines

    def render_free_groups(self, info: FreeGroupsDebugInfo) -> list[str]:
        lines = [
            "Current free stack in super block:",
            "",
            "Top",
            " │",
            " ▼",
        ]
        for index, block_id in enumerate(reversed(info.current_stack)):
            suffix = "  ← next allocated block" if index == 0 else ""
            if block_id == 0:
                suffix = "  ← chain end"
            lines.append(f"[ {block_id:>3} ]{suffix}")
        lines.extend([
            "Bottom",
            "",
            f"Next group pointer block: {info.next_group_pointer or 'END'}",
            "",
            "Horizontal group chain:  use Left / Right to scroll",
            "",
        ])
        lines.extend(self._render_horizontal_groups(info.groups))
        if info.inconsistencies:
            lines.extend(["", "Warnings:"])
            lines.extend(f"! {message}" for message in info.inconsistencies)
        return lines

    def render_block_map(
        self,
        info: BlockMapDebugInfo,
        *,
        start: int = 0,
        rows: int | None = None,
    ) -> list[str]:
        lines = [
            "Disk Layout",
            "┌───────┬──────────────────────┬──────────────────────────────────────┐",
            "│ SUPER │      INODE AREA      │              DATA AREA               │",
            "│   0   │        1..128        │              129..1023               │",
            "└───────┴──────────────────────┴──────────────────────────────────────┘",
            "",
            "Legend: S super | I inode area | R reserved | D directory | F file",
            "        G free-group metadata | X indirect index | . free | ? unknown",
            "",
        ]
        entries = info.entries[start:]
        if rows is not None:
            entries = entries[: rows * 16]
        for offset in range(0, len(entries), 16):
            row = entries[offset : offset + 16]
            symbols = " ".join(ROLE_SYMBOL[entry.role] for entry in row)
            lines.append(f"{start + offset:04d}: {symbols}")
        lines.extend([
            "",
            f"Data blocks: used={info.used_data_blocks} free={info.free_data_blocks}",
        ])
        if info.inconsistencies:
            lines.extend(["", "Warnings:"])
            lines.extend(f"! {message}" for message in info.inconsistencies)
        return lines

    def render_file_index(self, info: FileIndexDebugInfo) -> list[str]:
        lines = [
            f"File: {info.path}",
            f"inode: {info.inode_id}    size: {info.size} B    block size: {BLOCK_SIZE} B",
            "",
            f"inode {info.inode_id}",
        ]

        branches = []
        for index in range(DIRECT_CNT):
            if index < len(info.direct_blocks):
                branch = self._block_target(info.direct_blocks[index])
            else:
                branch = "unused"
            branches.append(f"direct[{index}] ----------------> {branch}")

        if info.single_indirect_block is None:
            branches.append("single indirect -----------> unused")
        else:
            branches.append(
                "single indirect -----------> "
                + self._index_target(info.single_indirect_block)
            )

        for index, text in enumerate(branches):
            is_last = index == len(branches) - 1
            lines.append(("└── " if is_last else "├── ") + text)

        if info.single_indirect_block is not None:
            for index, block_id in enumerate(info.single_indirect_data_blocks):
                is_last = index == len(info.single_indirect_data_blocks) - 1
                prefix = "    └── " if is_last else "    ├── "
                lines.append(f"{prefix}[{index}] ----------------> {self._block_target(block_id)}")

        lines.extend([
            "",
            "Note: this file system implements direct indexes and one single indirect index.",
        ])
        return lines

    def render_overview(
        self,
        inode_info: InodeBitmapDebugInfo,
        group_info: FreeGroupsDebugInfo,
        block_info: BlockMapDebugInfo,
    ) -> list[tuple[str, list[str]]]:
        inode_lines = self.render_inode_bitmap(inode_info, rows=2)
        inode_lines = inode_lines[:4] + [
            f"Used: {inode_info.used}    Free: {inode_info.free}"
        ]

        block_entries = block_info.entries
        selected = block_entries[:16] + block_entries[128:160]
        block_lines = [
            "Legend: S super | I inode | R reserved | D dir | F file | G group | X index | . free",
        ]
        for offset in range(0, len(selected), 16):
            row = selected[offset : offset + 16]
            row_start = 0 if offset == 0 else 128 + offset - 16
            symbols = " ".join(ROLE_SYMBOL[entry.role] for entry in row)
            block_lines.append(f"{row_start:04d}: {symbols}")
        block_lines.append(
            f"Data blocks: used={block_info.used_data_blocks} free={block_info.free_data_blocks}"
        )

        disk_lines = [
            "[ S: super 0 ] [ I: inode area 1..128 ] [ DATA: blocks 129..1023 ]",
        ]

        top = list(reversed(group_info.current_stack))[:8]
        stack = " ".join(f"[{block_id}]" for block_id in top) or "[empty]"
        group_lines = [
            f"SuperBlock Top -> {stack}",
            f"Next group pointer: {group_info.next_group_pointer or 'END'}",
        ]
        return [
            ("Inode Bitmap", inode_lines),
            ("Disk Layout", disk_lines),
            ("Block Map", block_lines),
            ("Free Groups", group_lines),
        ]

    def _render_horizontal_groups(self, groups: list[FreeGroupEntry]) -> list[str]:
        if not groups:
            return ["[ empty ]"]

        bodies = [self._group_card_body(group) for group in groups]
        body_height = max(len(body) for body in bodies)
        cards = [self._box_card(body, body_height) for body in bodies]
        height = body_height + 2
        arrow_row = 2
        connector = " ────> "
        lines = []
        for row in range(height):
            parts = []
            for index, card in enumerate(cards):
                parts.append(card[row] if row < len(card) else " " * len(card[0]))
                if index < len(cards) - 1:
                    parts.append(connector if row == arrow_row else " " * len(connector))
            lines.append("".join(parts).rstrip())
        lines.append(" " * 12 + "chain end: stack[0] == 0")
        return lines

    def _group_card_body(self, group: FreeGroupEntry) -> list[str]:
        width = 32
        inner = width - 2
        title = group.source
        next_group = group.next_group_block or "END"
        values = " ".join(str(block_id) for block_id in group.stack)
        value_lines = textwrap.wrap(values, width=inner - 2) or ["empty"]
        return [
            title,
            f"count = {group.count}",
            f"next group = {next_group}",
            "stack:",
            *value_lines,
        ]

    def _box_card(self, body: list[str], body_height: int) -> list[str]:
        width = 32
        inner = width - 2
        padded = body + [""] * (body_height - len(body))
        return [
            "┌" + "─" * inner + "┐",
            *(f"│ {line:<{inner - 1}}│" for line in padded),
            "└" + "─" * inner + "┘",
        ]

    def _inode_symbol(self, kind: str) -> str:
        return {"DIR": "D", "FILE": "F", "FREE": "."}.get(kind, "?")

    def _block_target(self, data_block_id: int) -> str:
        return f"data block {data_block_id}  (disk {DATA_BLOCK_START_ID + data_block_id})"

    def _index_target(self, data_block_id: int) -> str:
        return f"index block {data_block_id}  (disk {DATA_BLOCK_START_ID + data_block_id})"
