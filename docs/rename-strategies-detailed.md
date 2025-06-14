# Detailed Design: Path-Preserving vs Create-Path Rename Strategies

## Overview

The rename operation in mergerfs has two distinct strategies based on whether the configured create policy is "path-preserving". This document details the implementation of both strategies based on the C++ implementation analysis.

## Key Concepts

### Path-Preserving Create Policies
These policies attempt to keep files on branches where the parent directory already exists:
- `epff` - Existing Path First Found
- `eplfs` - Existing Path Least Free Space  
- `eplus` - Existing Path Least Used Space
- `epmfs` - Existing Path Most Free Space

### Non-Path-Preserving Create Policies
These policies don't consider existing paths and choose branches based on other criteria:
- `ff` - First Found
- `mfs` - Most Free Space
- `lfs` - Least Free Space
- `rand` - Random

## Strategy 1: Path-Preserving Rename

Used when the create policy is path-preserving AND `ignorepponrename` is false.

### Algorithm

```pseudocode
function rename_preserve_path(old_path, new_path):
    # 1. Get branches where source file exists using action policy
    source_branches = action_policy.select_branches(old_path)
    
    if source_branches.empty:
        return ENOENT
    
    success = false
    to_remove = []
    
    # 2. For each branch in the pool
    for branch in all_branches:
        new_full_path = branch.path + new_path
        
        # 3. If source doesn't exist on this branch, mark destination for removal
        if branch not in source_branches:
            to_remove.append(new_full_path)
            continue
        
        # 4. Attempt rename on this branch
        old_full_path = branch.path + old_path
        result = fs::rename(old_full_path, new_full_path)
        
        if result == success:
            success = true
        else:
            # Mark failed source for removal
            to_remove.append(old_full_path)
    
    # 5. If no renames succeeded, return EXDEV
    if not success:
        return EXDEV
    
    # 6. Clean up marked files
    for path in to_remove:
        fs::remove(path)
    
    return OK
```

### Key Characteristics
- Files stay on their original branches only
- No directory creation on new branches
- Returns EXDEV if all renames fail
- Removes orphaned files after successful rename

## Strategy 2: Create-Path Rename

Used when the create policy is NOT path-preserving OR `ignorepponrename` is true.

### Algorithm

```pseudocode
function rename_create_path(old_path, new_path):
    # 1. Get branches where source file exists using action policy
    source_branches = action_policy.select_branches(old_path)
    
    if source_branches.empty:
        return ENOENT
    
    # 2. Get target branch for new path's parent using search policy
    target_branches = search_policy.find_branches(new_path.parent())
    
    if target_branches.empty:
        return ENOENT
    
    error = -1
    to_remove = []
    
    # 3. For each branch in the pool
    for branch in all_branches:
        new_full_path = branch.path + new_path
        
        # 4. If source doesn't exist on this branch, mark destination for removal
        if branch not in source_branches:
            to_remove.append(new_full_path)
            continue
        
        # 5. Attempt rename
        old_full_path = branch.path + old_path
        result = fs::rename(old_full_path, new_full_path)
        
        # 6. If rename fails with ENOENT, try creating parent directory
        if result == ENOENT:
            # Clone path structure from target branch
            fs::clonepath_as_root(target_branches[0].path, branch.path, new_path.parent())
            # Retry rename
            result = fs::rename(old_full_path, new_full_path)
        
        # 7. Track errors
        error = error::calc(result, error, errno)
        
        if result != success:
            to_remove.append(old_full_path)
    
    # 8. Clean up if any rename succeeded
    if error == 0:
        for path in to_remove:
            fs::remove(path)
    
    return error
```

### Key Characteristics
- Can create parent directories on branches where they don't exist
- Uses search policy to find target branch for cloning directory structure
- More flexible - allows files to spread across branches
- Better handles cases where parent directory doesn't exist

## Cross-Device (EXDEV) Handling

When either strategy returns EXDEV, additional handling can be configured:

### 1. Passthrough Mode
Simply return EXDEV to the caller.

### 2. Relative Symlink Mode
1. Move source files to temporary location (`.mergerfs_rename_exdev/<original_path>`)
2. Create relative symlink from new path to temporary location
3. If symlink creation fails, move files back

### 3. Absolute Symlink Mode
Similar to relative symlink but uses absolute paths including the mount point.

## Implementation Considerations

### Error Prioritization
The `error::calc` function maintains the most significant error:
- If no previous error (prev == 0), keep current error
- Otherwise, preserve the first error encountered

### Cleanup Operations
- File removals are silent - failures don't affect the overall operation
- Cleanup happens after all rename attempts complete
- Only clean up files that either:
  - Don't have a source on that branch (destination cleanup)
  - Failed to rename (source cleanup)

### Directory Creation
- Use `clonepath_as_root` to preserve directory structure and permissions
- Only attempt directory creation in create-path mode
- Directory creation requires root privileges temporarily

## Configuration Options

### `ignorepponrename`
- When true: Always use create-path strategy
- When false: Use strategy based on create policy type

### `rename_exdev`
Controls EXDEV handling:
- `passthrough`: Return EXDEV to caller
- `rel_symlink`: Create relative symlinks
- `abs_symlink`: Create absolute symlinks

## Testing Scenarios

1. **Same Directory Rename**: Test both strategies behave identically
2. **Cross-Directory Rename**: Test directory creation in create-path mode
3. **Multi-Branch Files**: Ensure all instances are renamed/cleaned up
4. **Missing Parent Directory**: Test directory creation behavior
5. **Read-Only Branches**: Verify proper error handling
6. **EXDEV Scenarios**: Test cross-device rename handling
7. **Concurrent Renames**: Test for race conditions