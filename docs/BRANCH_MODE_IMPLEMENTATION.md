# Branch Mode Implementation Plan

## Overview
Implement branch mode enforcement for RO (ReadOnly) and NC (NoCreate) modes to match C++ mergerfs behavior.

## Branch Mode Specification Format
- Format: `/path=MODE` or `/path=MODE,minfreespace`
- Examples:
  - `/mnt/disk1=RO` - Read-only branch
  - `/mnt/disk2=NC` - No-create branch (can modify existing files)
  - `/mnt/disk3=RW` or `/mnt/disk3` - Read-write branch (default)

## Implementation Steps

### 1. Parse Branch Modes
- Update `parse_args()` in main.rs to parse mode suffixes
- Extract mode from branch path specification

### 2. Enforce in Policies
- Update all create policies to check `branch.is_readonly_or_no_create()`
- Skip RO/NC branches during branch selection for create operations
- Return EROFS if no suitable branch found

### 3. Enforce in FUSE Operations
- `create()` - Check branch mode before creating files
- `mkdir()` - Check branch mode before creating directories
- `mknod()` - Check branch mode before creating special files
- `symlink()` - Check branch mode before creating symlinks
- `rename()` - Check destination branch mode for new files
- `link()` - Check branch mode before creating hard links

### 4. Write Operations
- `write()` - Allow writes to existing files on NC branches
- `truncate()` - Allow truncation on NC branches
- `setattr()` - Allow metadata changes on NC branches

## Error Handling
- Return EROFS (30) when operation violates branch mode
- Policies should continue searching for suitable branches

## Testing
- Enable test_branch_modes.py when implementation is complete
- Test all combinations of RO/NC modes
- Test policy interactions with branch modes