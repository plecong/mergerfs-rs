# EPMFS (Existing Path, Most Free Space) Policy Design

## Overview

The EPMFS policy is a hybrid create policy that combines two strategies:
1. **Existing Path (EP)**: Preserves directory locality by selecting branches where the parent directory already exists
2. **Most Free Space (MFS)**: Among branches with the existing path, selects the one with the most available space

This policy is marked as "path preserving" which means it tries to keep files within the same directory structure together on the same branch, improving performance and reducing fragmentation across branches.

## C++ Implementation Analysis

### Key Behaviors

1. **Branch Filtering**:
   - Skip read-only branches (`branch.ro_or_nc()` for create, `branch.ro()` for action)
   - Skip branches where the parent path doesn't exist
   - Skip branches that fail filesystem info queries
   - Skip branches below minimum free space threshold

2. **Selection Logic**:
   - Among eligible branches (writable + path exists), select the one with maximum available space
   - Uses `info.spaceavail` which corresponds to `f_bavail * f_frsize` from statvfs

3. **Error Handling**:
   - Uses priority-based error aggregation via `error_and_continue` macro
   - Error priority: ENOENT < ENOSPC < EROFS < others
   - Returns the highest priority error if no suitable branch found

### Pseudocode

```
function epmfs_create(branches, fusepath):
    best_branch = null
    max_space = 0
    error = ENOENT
    
    for each branch in branches:
        // Skip non-writable branches
        if branch.is_readonly_or_nocreate():
            update_error(error, EROFS)
            continue
            
        // Skip if parent path doesn't exist
        if not exists(branch.path + fusepath):
            update_error(error, ENOENT)
            continue
            
        // Get filesystem info
        info = get_fs_info(branch.path)
        if info is null:
            update_error(error, ENOENT)
            continue
            
        // Skip if filesystem is readonly
        if info.readonly:
            update_error(error, EROFS)
            continue
            
        // Skip if below minimum free space
        if info.spaceavail < branch.minfreespace:
            update_error(error, ENOSPC)
            continue
            
        // Track branch with most free space
        if info.spaceavail > max_space:
            max_space = info.spaceavail
            best_branch = branch
    
    if best_branch is null:
        return error
    
    return best_branch
```

## Rust Implementation Design

### Key Differences from C++

1. **Error Handling**: Use Rust's Result type with PolicyError enum instead of errno
2. **Path Checking**: Need to construct full parent path for existence check
3. **Space Calculation**: Use existing DiskSpace utility that handles statvfs
4. **Branch Access**: Use Arc<Branch> for thread-safe access

### Implementation Plan

1. Create new module `src/policy/create/existing_path_most_free_space.rs`
2. Implement `CreatePolicy` trait with path-preserving behavior
3. Check parent directory existence on each branch
4. Among branches with existing path, select one with most free space
5. Follow error priority similar to C++ (but using Rust error types)

### Error Priority Mapping

C++ errno -> Rust PolicyError:
- ENOENT -> PolicyError::PathNotFound
- ENOSPC -> PolicyError::NoSpace
- EROFS -> PolicyError::ReadOnlyFilesystem
- Other I/O errors -> PolicyError::IoError

## Testing Strategy

### Unit Tests
1. Test with no branches -> NoBranchesAvailable
2. Test with all readonly branches -> ReadOnlyFilesystem
3. Test with path existing on multiple branches -> selects most free space
4. Test with path not existing on any branch -> PathNotFound
5. Test with branches below minfreespace -> NoSpace
6. Test error priority when multiple error conditions exist

### Integration Tests
1. Create files in nested directories and verify they stay on same branch
2. Test fallback behavior when preferred branch is full
3. Test with mix of readonly and readwrite branches
4. Verify path preservation across multiple operations