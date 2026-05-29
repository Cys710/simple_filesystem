# Agent Guide

## Project Overview

This repository is a small Python implementation of a simulated file management system / file system. The current code models low-level file-system concepts such as a super block, inode bitmap, inode records, directory blocks, serialized disk blocks, and grouped free data-block management.

The codebase is still in an early stage. Some modules contain commented-out legacy entrypoint code, several Chinese comments appear with mojibake/encoding corruption, and `src/init.py` is currently untracked in git.

## Repository Layout

- `src/head.py`: Global constants for the simulated disk layout, such as disk size, block size, inode count, data-block count, root id, and display constants.
- `src/data/block.py`: Base `Block` class using `pickle` serialization and a `write_back(fp)` helper.
- `src/data/groupList.py`: `GroupList`, a stack-like structure for grouped free data-block management.
- `src/data/Inode.py`: `InodeBitmap` and `Inode` data structures.
- `src/data/data.py`: `SuperBlock` and `DirBlock`; `SuperBlock` owns inode/data-block metadata and allocation/free logic.
- `src/disk.py`: Fixed-size simulated disk block IO helpers and `Disk` wrapper.
- `src/object_io.py`: Object serialization/deserialization helpers for objects stored in full disk blocks.
- `src/inode_io.py`: Inode slot IO helpers for storing 256-byte inode entries inside inode blocks.
- `src/utils.py`: Serialization helpers that split pickled data into block-sized chunks.
- `src/user.py`: Simple `User` model using MD5 password hashing.
- `src/main.py`: Currently contains mostly commented legacy shell/entrypoint code plus a partial `init()` function.
- `src/init.py`: Disk image initialization/formatting helpers. This file is currently untracked.
- `test/test_group_list.py`: Unit tests for `GroupList` and `SuperBlock` free data-block behavior.
- `docs/`: Present but currently empty.

## Development Environment

The project currently uses only the Python standard library. No dependency manager or requirements file is present.

Recommended Python command:

```powershell
python -m unittest discover -s test
```

If import errors occur while running individual files, note that the tests manually add both `src` and `src/data` to `sys.path`. Several source modules also use flat imports such as `from block import Block` and `from head import ...`, so running from the project root with the same import path setup matters.

## Current Behavior

The best-covered behavior is grouped free data-block allocation:

- `SuperBlock.init_data_block_group_link(fp)` initializes the free data-block group link.
- Data block id `0` is reserved and should not be allocated.
- `SuperBlock.get_data_block_id(fp)` allocates one free data block.
- `SuperBlock.free_up_data_block(fp, block_id)` releases a data block back to the free list.
- `GroupList` enforces a maximum stack size of `FREE_BLOCK_CNT`.

The tests check:

- Initial free-block count.
- Allocation uniqueness.
- Allocation until empty.
- Freeing and reallocating blocks.
- Group leader transitions.
- Boundary cases for empty, full, and oversized `GroupList` stacks.

## Important Constants

From `src/head.py`:

- Disk size: `4 * 1024 * 1024` bytes.
- Block size: `4096` bytes.
- Total blocks: `1024`.
- Super block count: `1`.
- Inode block count: `128`.
- Inode size: `256` bytes.
- Inode count: `2048`.
- Data block count: `895`.
- Data blocks start at block id `129`.
- Free block group stack limit: `50`.
- Root id: `0`.

## Known Issues And Cautions

- Many comments and string literals are mojibake. Be careful when editing comments or user-facing messages; preserve behavior first, and fix encoding only as a deliberate cleanup.
- `src/head.py` appears to contain a malformed assertion string around `INODE_NUM`. If parsing fails, inspect that line first.
- `src/main.py` is not a working application entrypoint yet. Treat it as partial/legacy code.
- `src/init.py` creates `disk.img` in the current working directory, while `src/head.py` defines `DISK_NAME = "../FS.pfs"`. Disk image naming/location is not yet consistent.
- Serialization uses `pickle`, which is suitable for this local simulation but should not be used on untrusted data.
- `User` stores MD5 password hashes. This is fine for a teaching/demo project but not for production security.
- `Block.write_back(fp)` writes pickled bytes without padding to a full block. Code that reads full blocks should tolerate trailing zero bytes or ensure fixed-size writes if disk persistence becomes stricter.

## Git Notes

Current observed status:

```text
?? src/disk.py
?? src/object_io.py
?? src/inode_io.py
?? src/init.py
```

Do not remove or overwrite untracked/user changes unless explicitly asked.

## Three-Layer Bring-Up Plan

The next development goal is not to implement many shell commands at once. The priority is to connect the whole program end to end through three layers:

```text
disk/block IO -> file-system core API -> shell command layer
```

Once this chain works, new commands and features can be added incrementally.

### Layer 1: Disk And Block IO

First stabilize the disk-file abstraction. At the moment, disk naming is inconsistent:

- `src/head.py` defines `DISK_NAME = "../FS.pfs"`.
- `src/init.py` writes `disk.img`.

Choose one disk path/name before building higher-level behavior.

The disk layer should only understand fixed-size block IO. It should not know about inode, directory, file name, user, or shell concepts.

Suggested minimal API:

```python
create_disk()
open_disk()
read_block(block_id)
write_block(block_id, data)
format_disk()
```

First validation target:

```text
write block 10 -> reopen/read block 10 -> bytes are unchanged
```

After this step, the project has reliable raw disk-block IO.

### Layer 2: Object Serialization

The project has two serialization-related pieces:

- `src/data/block.py`: older object-level pickle helper via `Block`.
- `src/object_io.py`: newer disk-object persistence helper for storing an object into one or more complete blocks.

`Block` supports:

```python
bytes(obj)
Block.from_bytes(...)
write_back(fp)
```

The current `Block.write_back(fp)` writes at the file pointer's current position. The newer `object_io.py` layer makes disk persistence explicit:

```python
write_object(fp, start_block_id, obj, block_count=1)
read_object(fp, start_block_id, block_count=1)
```

This layer should connect:

```text
Python object -> bytes -> disk block -> bytes -> Python object
```

Validation target:

```text
create GroupList -> write it to a block -> read it back -> count/stack are unchanged
```

After this step, the project has object persistence.

Use `object_io.py` for objects that naturally occupy one or more whole blocks, such as:

- `SuperBlock`
- `GroupList`
- `DirBlock`

Do not use whole-block object IO directly for individual inodes. Inodes use fixed 256-byte slots inside inode blocks.

### Inode Slot IO

`src/inode_io.py` handles the special inode layout:

```text
BLOCK_SIZE = 4096
INODE_SIZE = 256
INODES_PER_BLOCK = 16
```

Each inode lives in a 256-byte slot, and each inode block contains 16 inode slots. The slot format is:

```text
2-byte payload length + serialized inode payload + zero padding to 256 bytes
```

Important helpers:

```python
locate_inode(inode_id) -> (block_id, slot_index, offset_in_block)
pack_inode_slot(inode) -> bytes
unpack_inode_slot(slot) -> inode
write_inode(fp, inode_id, inode)
read_inode(fp, inode_id)
clear_inode_slot(fp, inode_id)
```

The inode location formula is:

```python
inode_block_offset = inode_id // INODES_PER_BLOCK
slot_index = inode_id % INODES_PER_BLOCK
block_id = INODE_BLOCK_START_ID + inode_block_offset
offset = slot_index * INODE_SIZE
```

Examples:

```text
inode_id 0  -> block 1, slot 0,  offset 0
inode_id 1  -> block 1, slot 1,  offset 256
inode_id 15 -> block 1, slot 15, offset 3840
inode_id 16 -> block 2, slot 0,  offset 0
```

This layer is intentionally different from `object_io.py`: `object_io.py` writes complete blocks, while `inode_io.py` reads/modifies one 256-byte slot inside a block and preserves the neighboring 15 slots.

### Layer 3: Format And Mount

Build a real `format_disk()` flow before adding commands. The minimum useful format process is:

```text
1. Create the 4MB disk file.
2. Create a SuperBlock.
3. Initialize the free data-block group link.
4. Initialize the inode bitmap.
5. Create the root inode.
6. Create the root DirBlock.
7. Write the SuperBlock to block 0.
8. Write the root inode and root directory to their planned locations.
```

Then add a matching `mount()` or `load_file_system()` flow:

```text
1. Open the disk file.
2. Read the SuperBlock from block 0.
3. Load enough root metadata to serve basic operations.
```

Validation target:

```text
format_disk()
mount()
confirm free_data_block_cnt is correct
confirm root inode/root directory can be read
```

After this step, the file system can be initialized and reopened.

### Inode Allocation

Next, expose inode operations through the file-system core layer. `InodeBitmap` exists, but the project still needs clear high-level methods.

Suggested API:

```python
alloc_inode(user_id) -> inode_id
free_inode(inode_id)
read_inode(inode_id) -> Inode
write_inode(inode)
```

Validation target:

```text
alloc_inode() returns an unused inode id
write_inode()
read_inode()
read inode_id/user_id/is_dir match the written object
```

After this step, metadata allocation is available.

### Root Directory Bring-Up

Use `DirBlock` to bring up only the root directory first. Do not start with recursive paths or a large command set.

Suggested API:

```python
load_root_dir()
save_root_dir(dir_block)
list_dir("/")
create_file("/", name)
create_dir("/", name)
```

At this stage, file content can stay empty. Creating a file only needs to:

```text
allocate inode -> write inode -> add name/inode_id to root DirBlock -> save root DirBlock
```

Validation target:

```text
pfs> ls
pfs> mkdir test
pfs> touch a.txt
pfs> ls
test  a.txt
```

After this step, the program has its first end-to-end path from shell intent to persisted file-system metadata.

### FileSystem Core API

Create or restore a `FileSystem` class as the middle layer. The shell should call this class instead of directly manipulating `SuperBlock`, `Inode`, `DirBlock`, or disk blocks.

Suggested public API:

```python
class FileSystem:
    def format(self): ...
    def mount(self): ...
    def ls(self, path="."): ...
    def mkdir(self, path): ...
    def touch(self, path): ...
    def cd(self, path): ...
    def pwd(self): ...
```

Expected call flow:

```text
shell command
    -> FileSystem.mkdir("abc")
        -> alloc_inode()
        -> write_inode()
        -> update DirBlock
        -> write_block()
```

Keep shell parsing thin. Put real behavior in `FileSystem` so later commands reuse the same core logic.

### Shell Command Layer

`src/main.py` contains a commented legacy shell loop. For the first working shell, keep parsing simple:

```python
cmd = input("pfs> ").split()
```

Start with only the commands needed to prove the chain:

```text
format
mount
ls
mkdir name
touch name
pwd
exit
```

The key persistence test is:

```text
format -> mount -> mkdir test -> touch a.txt -> ls
exit
restart -> mount -> ls
```

The second `ls` should still show `test` and `a.txt`.

### Recommended Implementation Order

Use this order to avoid building features on an unstable foundation:

1. Disk block read/write.
2. Object serialization read/write.
3. `format_disk()` writes a usable `SuperBlock`.
4. `mount()` reads the `SuperBlock`.
5. Inode allocation and inode read/write.
6. Root directory read/write.
7. `FileSystem.ls`, `FileSystem.mkdir`, and `FileSystem.touch`.
8. Shell commands call `FileSystem`.
9. Add recursive paths, file content, delete operations, permissions, and users later.

The first complete milestone should be:

```text
format -> mount -> mkdir -> ls -> exit -> restart -> mount -> ls
```

Once that path works, each new feature can be added by extending the same three-layer pipeline.

## Suggested Next Steps

- Make imports package-consistent, preferably through `src` package imports.
- Fix or normalize source-file encoding and corrupted comments.
- Decide on one disk image path/name.
- Finish a real initialization/format flow that writes a super block, inode bitmap, root directory, and free block metadata.
- Add tests for inode bitmap, block serialization, directory block behavior, and disk initialization.
