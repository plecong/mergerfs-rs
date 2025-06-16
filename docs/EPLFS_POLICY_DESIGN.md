# EPLFS (Existing Path, Least Free Space) Create Policy Design

## Overview

The EPLFS (Existing Path, Least Free Space) create policy is a path-preserving policy that selects the branch with the least available free space among branches where the parent directory already exists. This policy helps balance storage usage across branches by filling up drives with less free space first, while maintaining directory locality.

## Purpose

- **Storage Balancing**: Fills up branches with less available space before using branches with more space
- **Path Preservation**: Keeps related files together by only considering branches where the parent path exists
- **Efficient Space Utilization**: Helps prevent situations where some drives are nearly full while others have significant free space

## Algorithm

### Pseudocode

```
function select_branch(branches, path):
    parent = get_parent_directory(path)
    
    // Special case: root directory exists everywhere
    if parent is root:
        return select_least_free_space_branch(branches)
    
    selected_branch = null
    min_free_space = MAX_UINT64
    highest_priority_error = null
    
    for each branch in branches:
        // Skip non-writable branches
        if not branch.allows_create():
            continue
            
        // Check if parent exists on this branch
        branch_parent = branch.path + parent
        
        if not exists(branch_parent):
            if highest_priority_error is null:
                highest_priority_error = ENOENT
            continue
            
        // Get disk space for this branch
        try:
            disk_space = get_disk_space(branch.path)
            available = disk_space.available
            
            // Select if this has less free space than current minimum
            if available < min_free_space:
                min_free_space = available
                selected_branch = branch
                
        catch error:
            // Track I/O errors with lower priority than ENOENT
            if highest_priority_error is null:
                highest_priority_error = error
    
    if selected_branch is not null:
        return selected_branch
    else:
        return error with appropriate errno
```

## Implementation Details

### 1. Path Checking

- Extract parent directory from the target path
- For each branch, construct the full parent path by joining branch path with parent
- Use `try_exists()` to safely check parent existence without following symlinks
- Handle root directory as a special case (exists on all branches)

### 2. Space Calculation

- Use `DiskSpace::for_path()` to get filesystem statistics
- Consider only available space (`f_bavail * f_frsize`) not total free space
- This respects filesystem reservations for root

### 3. Branch Selection

- Track the branch with minimum free space
- Only consider writable branches (`allows_create()` returns true)
- Skip read-only and no-create branches

### 4. Error Handling

Error priority (highest to lowest):
1. **I/O Errors**: Filesystem access failures
2. **ENOSPC**: No space available (not applicable for this policy)
3. **ENOENT**: Parent directory not found on any branch

### 5. Integration Points

- Implements `CreatePolicy` trait
- Returns `true` for `is_path_preserving()`
- Registered in policy factory with name "eplfs"

## Comparison with C++ Implementation

### Similarities
- Core algorithm selecting least free space among existing paths
- Path preservation behavior
- Error prioritization logic
- Branch mode checking (RO/NC/RW)

### Differences
- **No minimum free space check**: Rust implementation doesn't check minfreespace
- **Simplified error handling**: Uses Rust's Result type instead of errno
- **No caching**: C++ uses statvfs cache for search operations
- **Single purpose**: Only implements create policy, not action/search variants

## Testing Strategy

### Unit Tests
1. **Basic functionality**: Verify selection of branch with least free space
2. **Path preservation**: Ensure only branches with existing parent are considered
3. **Read-only handling**: Skip read-only branches correctly
4. **No parent exists**: Return appropriate error when parent missing
5. **Root path handling**: Special case for root directory

### Integration Tests
1. Create files using eplfs policy
2. Verify files are placed on branches with least free space
3. Test with various branch configurations (RO/RW/NC)
4. Verify path preservation across operations

## Usage Scenarios

Best suited for:
- Environments where balanced disk usage is important
- Keeping related files together while filling up smaller drives first
- Preventing premature "disk full" errors when space is available elsewhere

Not ideal for:
- Performance-critical applications (disk with least space might be slower)
- Scenarios where keeping drives mostly empty is preferred
- Write-heavy workloads on nearly-full filesystems

## Future Enhancements

1. **Minimum free space support**: Add configurable threshold
2. **Performance optimization**: Cache filesystem statistics
3. **Weighted selection**: Consider other factors beyond just free space
4. **Action/Search variants**: Implement for other operation types