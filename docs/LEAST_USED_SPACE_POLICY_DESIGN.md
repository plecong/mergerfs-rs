# Least Used Space (LUS) Create Policy Design

## Overview

The "lus" (least used space) create policy is designed to balance storage usage across multiple branches by placing new files on the branch that currently has the least amount of used space. This helps prevent any single branch from becoming disproportionately full compared to others.

## C++ Implementation Analysis

### Key Components

1. **Policy Classes** (`policy_lus.hpp`):
   - `Policy::LUS::Create` - Main implementation for file/directory creation
   - `Policy::LUS::Action` - Delegates to eplus policy
   - `Policy::LUS::Search` - Delegates to eplus policy

2. **Core Algorithm** (`policy_lus.cpp`):

```cpp
// Pseudocode for lus::create
function lus_create(branches, fusepath, minfreespace):
    lus = UINT64_MAX  // Start with maximum value
    branch = null     // Selected branch
    error = ENOENT    // Default error
    
    for each branch in branches:
        // Skip read-only or no-create branches
        if branch.mode is RO or NC:
            continue
            
        // Get filesystem statistics
        info = statvfs(branch.path)
        if error:
            update error priority
            continue
            
        // Skip read-only filesystems
        if info.f_flag & ST_RDONLY:
            error = EROFS
            continue
            
        // Calculate space metrics
        spaceused = info.f_frsize * (info.f_blocks - info.f_bavail)
        spaceavail = info.f_frsize * info.f_bavail
        
        // Skip if insufficient free space
        if spaceavail < minfreespace:
            error = ENOSPC
            continue
            
        // Select branch with least used space
        if spaceused < lus:
            lus = spaceused
            branch = current_branch
            
    if branch is null:
        return error
    else:
        return (branch, fusepath)
```

### Space Calculations

The policy uses the following formulas:
- **Space Used**: `f_frsize × (f_blocks - f_bavail)`
- **Space Available**: `f_frsize × f_bavail`

Where (from `statvfs`):
- `f_frsize`: Fragment size (fundamental filesystem block size)
- `f_blocks`: Total data blocks in filesystem
- `f_bavail`: Free blocks available to unprivileged users

### Error Priority

The policy uses a priority system for errors:
1. `ENOENT` (lowest) - No such file or directory
2. `ENOSPC` - No space left on device  
3. `EROFS` (highest) - Read-only filesystem

Higher priority errors override lower priority ones.

## Rust Implementation Design

### Structure

```rust
pub struct LeastUsedSpace;

impl CreatePolicy for LeastUsedSpace {
    fn select_branch<'a>(
        &self,
        branches: &'a [Branch],
        _path: &Path,
        _config: &Config,
    ) -> Result<&'a Branch, c_int> {
        // Implementation here
    }
    
    fn name(&self) -> &'static str {
        "lus"
    }
}
```

### Algorithm Steps

1. **Initialize tracking variables**:
   - `least_used_space = u64::MAX`
   - `selected_branch = None`
   - `last_error = ENOENT`

2. **Iterate through branches**:
   - Skip branches with `ReadOnly` or `NoCreate` modes
   - Get filesystem statistics using `statvfs`
   - Handle errors with priority system

3. **Calculate space metrics**:
   - Used space = fragment_size × (total_blocks - available_blocks)
   - Available space = fragment_size × available_blocks

4. **Apply constraints**:
   - Skip read-only filesystems
   - Skip if available space < minimum free space
   - Track appropriate error codes

5. **Select optimal branch**:
   - Choose branch with minimum used space
   - Return branch reference or error

### Key Differences from C++

1. **Error Handling**: Use Rust's `Result` type instead of errno
2. **Memory Safety**: No raw pointers, use references
3. **Platform Compatibility**: Use `nix` crate for portable `statvfs`

### Integration Points

1. **Policy Registry**: Register in `policy/mod.rs`
2. **Configuration**: Support runtime policy switching via xattr
3. **Testing**: Comprehensive unit and integration tests

## Testing Strategy

### Unit Tests

1. **Basic Selection**: Verify branch with least used space is selected
2. **Mode Filtering**: Ensure RO/NC branches are skipped
3. **Minimum Free Space**: Test constraint enforcement
4. **Error Handling**: Verify proper error prioritization
5. **Edge Cases**: Empty branches, all full, all read-only

### Integration Tests

1. **File Creation**: Create files and verify placement
2. **Directory Creation**: Test directory placement
3. **Space Balancing**: Fill branches and verify distribution
4. **Dynamic Changes**: Test behavior as space usage changes

## Example Usage

```bash
# Mount with lus policy for creates
mergerfs -o create=lus /mnt/disk1:/mnt/disk2 /mnt/union

# File placement example:
# disk1: 100GB used of 1TB (10% used)
# disk2: 500GB used of 1TB (50% used)
# New files will go to disk1 (least used space)
```

## Comparison with Related Policies

- **lfs (least free space)**: Selects branch with least free space
- **lus (least used space)**: Selects branch with least used space
- **mfs (most free space)**: Selects branch with most free space

The key difference is that `lus` looks at absolute used space rather than free space, which can be useful when branches have different total capacities.

## Implementation Notes

1. **Performance**: Single pass through branches, O(n) complexity
2. **Thread Safety**: Stateless policy, inherently thread-safe
3. **Caching**: No caching needed, fresh stats each time
4. **Compatibility**: Matches C++ behavior exactly