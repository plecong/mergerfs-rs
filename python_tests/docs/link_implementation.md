# mergerfs Hard Link Implementation Documentation

## Overview

The hard link implementation in mergerfs is complex due to the union filesystem nature where files may exist across multiple branches. The `link()` system call creates hard links, which are multiple directory entries pointing to the same inode.

## Key Components

### 1. Main Entry Point (`fuse_link.cpp`)

The FUSE link operation is handled by `FUSE::link()` which:
1. Sets up the user/group ID context
2. Attempts the normal link operation
3. If it fails with EXDEV (cross-device link), handles it based on the `link_exdev` configuration

### 2. Link Strategies

mergerfs implements two main strategies for creating hard links:

#### A. Create Path Strategy (`link_create_path`)
Used when the create policy is NOT path-preserving or when `ignorepponrename` is set:
1. Uses the action policy to find branches containing the old path
2. Uses the search policy to find branches for the new path's parent directory
3. Attempts to create the link on matching branches
4. If the parent directory doesn't exist, clones the directory structure first

#### B. Preserve Path Strategy (`link_preserve_path`)
Used when the create policy IS path-preserving:
1. Uses the action policy to find branches containing the old path
2. Attempts to create the link on the same branch
3. If it fails with ENOENT, returns EXDEV to indicate cross-device link
4. Updates the stat structure if successful and inode is 0

### 3. Core Link Logic

The actual linking process (`link_create_path_loop` and `link_preserve_path_core`):

```pseudocode
for each branch containing the old file:
    oldfullpath = branch_path + old_fuse_path
    newfullpath = branch_path + new_fuse_path
    
    rv = link(oldfullpath, newfullpath)
    
    if rv == -1 and errno == ENOENT:
        # Parent directory doesn't exist, clone it
        clone_path_as_root(new_branch, old_branch, new_parent_dir)
        rv = link(oldfullpath, newfullpath)
    
    accumulate_errors(rv, error, errno)
```

### 4. EXDEV Handling

When a hard link cannot be created across branches (EXDEV error), mergerfs offers several fallback strategies configured via `link_exdev`:

1. **PASSTHROUGH**: Simply return the EXDEV error to the application
2. **REL_SYMLINK**: Create a relative symbolic link instead
3. **ABS_BASE_SYMLINK**: Create an absolute symbolic link to the file in the source branch
4. **ABS_POOL_SYMLINK**: Create an absolute symbolic link using the mergerfs mount point

### 5. Error Handling

The error calculation logic prioritizes success:
- If any link operation succeeds, the overall operation is considered successful
- If all operations fail, the last error is returned
- Special handling for ENOENT errors when directories need to be created

## Policy Interactions

### Action Policy
Determines which branches contain the source file for linking. Common policies:
- `all`: All branches with the file
- `epall`: All branches with the file's parent path

### Search Policy  
Used in create path strategy to find where the new link's parent directory exists.

### Create Policy
Influences whether path preservation is attempted:
- Path-preserving policies: `epff`, `eplfs`, `eplus`, `epmfs`
- Non-path-preserving policies: `ff`, `lfs`, `lus`, `mfs`

## Important Behaviors

1. **Hard links only work within the same branch** - Cross-branch hard links are not supported due to filesystem constraints

2. **Path preservation** - When using path-preserving policies, links are only created on branches where the source file exists

3. **Directory cloning** - If the target directory doesn't exist on a branch, it's cloned from another branch maintaining permissions

4. **Stat updates** - After successful link creation, file attributes are retrieved and cached

5. **Symlink fallback** - When configured, failed hard links can create symlinks instead, though this changes the semantic behavior

## Configuration

The main configuration option is `link_exdev` which controls behavior when hard links fail:
- Default: `passthrough` 
- Options: `passthrough`, `rel-symlink`, `abs-base-symlink`, `abs-pool-symlink`

## Implementation Pseudocode

```pseudocode
function FUSE::link(oldpath, newpath):
    set_user_context()
    
    if create_policy.is_path_preserving() and not ignore_pp_on_rename:
        result = link_preserve_path(oldpath, newpath)
    else:
        result = link_create_path(oldpath, newpath)
    
    if result == -EXDEV:
        result = handle_link_exdev(oldpath, newpath)
    
    return result

function link_preserve_path(oldpath, newpath):
    branches = action_policy.get_branches(oldpath)
    
    for branch in branches:
        result = try_link_on_branch(branch, oldpath, newpath)
        if result == -ENOENT:
            # Convert to EXDEV since we can't create across branches
            errno = EXDEV
    
    return final_error

function link_create_path(oldpath, newpath):
    old_branches = action_policy.get_branches(oldpath)
    new_parent = dirname(newpath)
    new_branches = search_policy.get_branches(new_parent)
    
    for old_branch in old_branches:
        result = link_with_path_creation(old_branch, 
                                       new_branches[0], 
                                       oldpath, 
                                       newpath)
    
    return final_error
```

## Notes for Rust Implementation

1. **Errno mapping**: Use EXDEV (18) for cross-device links, ENOENT (2) for missing paths
2. **Branch iteration**: Process all relevant branches, not just the first
3. **Path cloning**: Implement directory structure cloning for missing parent paths  
4. **Symlink fallback**: Optional based on configuration
5. **Stat caching**: Update file attributes after successful link creation
6. **Error accumulation**: Success if any branch succeeds, otherwise return last error