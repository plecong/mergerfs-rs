# Link Operation Design

This document describes the design and implementation of the hard link operation in mergerfs, based on analysis of the C++ implementation.

## Overview

The link operation creates a hard link (additional directory entry) for an existing file. In a union filesystem, this is complex because:
1. The source and destination may be on different branches
2. Hard links cannot cross filesystem boundaries (EXDEV error)
3. Policy decisions determine where links are created

## C++ Implementation Analysis

### Core Components

1. **Policy-driven link creation**
   - Uses action policy to find source file branches
   - Uses search policy to find destination directory branches
   - Supports path-preserving vs path-creating modes

2. **EXDEV Handling**
   - When hard links fail due to cross-device errors, can fall back to:
     - PASSTHROUGH: Return EXDEV error
     - REL_SYMLINK: Create relative symbolic link
     - ABS_BASE_SYMLINK: Create absolute symlink to base branch
     - ABS_POOL_SYMLINK: Create absolute symlink to pool mount

3. **Path Preservation**
   - When enabled, tries to create links on same branch as source
   - Falls back to EXDEV if directories don't exist on source branch

### Pseudocode

```
function link(oldpath, newpath, config):
    // Step 1: Choose link strategy based on config
    if config.create_policy.is_path_preserving AND not config.ignore_pponrename:
        return link_preserve_path(oldpath, newpath, config)
    else:
        return link_create_path(oldpath, newpath, config)

function link_preserve_path(oldpath, newpath, config):
    // Find branches containing the source file
    source_branches = config.link_policy.get_branches(oldpath)
    if source_branches.empty():
        return -ENOENT
    
    error = -1
    for branch in source_branches:
        // Try to create hard link on same branch
        oldfullpath = branch.path + oldpath
        newfullpath = branch.path + newpath
        
        result = create_hard_link(oldfullpath, newfullpath)
        if result == -ENOENT:
            // Directory doesn't exist on this branch
            errno = EXDEV  // Force EXDEV handling
        
        error = update_error(result, error)
    
    return error

function link_create_path(oldpath, newpath, config):
    // Step 1: Find branches with source file using action policy
    source_branches = config.link_policy.get_branches(oldpath)
    if source_branches.empty():
        return -ENOENT
    
    // Step 2: Find branches for destination using search policy
    newdir = dirname(newpath)
    dest_branches = config.getattr_policy.get_branches(newdir)
    if dest_branches.empty():
        return -ENOENT
    
    // Step 3: Try to create link
    error = -1
    for source_branch in source_branches:
        oldfullpath = source_branch.path + oldpath
        newfullpath = source_branch.path + newpath
        
        result = create_hard_link(oldfullpath, newfullpath)
        
        // If directory doesn't exist, create it
        if result == -ENOENT:
            result = clone_path(dest_branches[0], source_branch, newdir)
            if result == 0:
                result = create_hard_link(oldfullpath, newfullpath)
        
        error = update_error(result, error)
    
    return error

function handle_link_exdev(oldpath, newpath, config):
    // Called when link returns EXDEV
    switch config.link_exdev:
        case PASSTHROUGH:
            return -EXDEV
        
        case REL_SYMLINK:
            // Create relative symlink
            target = make_relative_path(oldpath, dirname(newpath))
            return create_symlink(target, newpath)
        
        case ABS_BASE_SYMLINK:
            // Find branch with source file
            branches = config.open_policy.get_branches(oldpath)
            if branches.empty():
                return -ENOENT
            target = branches[0].path + oldpath
            return create_symlink(target, newpath)
        
        case ABS_POOL_SYMLINK:
            // Create symlink to mergerfs mount point
            target = config.mountpoint + oldpath
            return create_symlink(target, newpath)
    
    return -EXDEV

function main_link_operation(oldpath, newpath):
    config = get_config()
    set_ugid(context.uid, context.gid)
    
    // Try normal link
    result = link(oldpath, newpath, config)
    
    // Handle cross-device errors
    if result == -EXDEV:
        result = handle_link_exdev(oldpath, newpath, config)
    
    // Get attributes for successful operations
    if result >= 0:
        getattr(newpath, &stat, &timeouts)
    
    return result
```

### Key Behaviors

1. **Error Aggregation**
   - Tries all matching branches
   - Returns first success or aggregated error

2. **Directory Creation**
   - Creates parent directories on branches as needed
   - Uses clone_path to replicate directory structure

3. **Symlink Fallback**
   - When hard links fail, can create symlinks instead
   - Disables attribute caching for symlink fallbacks

## Rust Implementation Comparison

The current Rust implementation (`src/fuse_fs.rs:1306`) provides basic functionality:

### What's Implemented
- Basic hard link creation on same branch
- Parent directory creation
- Link count updates
- Single branch operation (first found)

### What's Missing
1. **Policy Support**
   - No link-specific policy
   - Always uses first branch with source file
   - No path preservation mode

2. **EXDEV Handling**
   - No symlink fallback options
   - Simply returns error on cross-device attempts

3. **Multi-branch Support**
   - Doesn't try multiple branches
   - No error aggregation

4. **Clone Path**
   - No directory cloning between branches

### Recommended Enhancements

1. **Add LinkPolicy trait**
   ```rust
   trait LinkPolicy {
       fn select_branches(&self, path: &Path, branches: &[Branch]) -> Vec<&Branch>;
   }
   ```

2. **Add link_exdev configuration**
   ```rust
   enum LinkEXDEV {
       Passthrough,
       RelSymlink,
       AbsBaseSymlink,
       AbsPoolSymlink,
   }
   ```

3. **Implement path preservation mode**
   - Check if create policy supports path preservation
   - Try to keep links on same branch as source

4. **Add symlink fallback handling**
   - When hard link fails with EXDEV, create symlinks based on config

## Testing Requirements

1. **Unit Tests**
   - Same branch hard links
   - Cross-branch attempts (EXDEV)
   - Directory creation
   - Link count updates
   - Error cases (ENOENT, EACCES, etc.)

2. **Integration Tests**
   - Multi-branch scenarios
   - Symlink fallback behavior
   - Policy interactions
   - File attributes after linking

## Implementation Priority

Given the current state:
1. The basic functionality works for single-branch cases
2. Advanced features (EXDEV handling, policies) are nice-to-have
3. Testing is the immediate priority to ensure correctness

Recommendation: Focus on comprehensive testing of existing functionality before adding advanced features.