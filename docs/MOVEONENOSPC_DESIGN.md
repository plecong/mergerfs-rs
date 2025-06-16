# MoveOnENOSPC Design Document

## Overview

The `moveonenospc` feature automatically moves files to another branch when a write operation fails due to lack of space (ENOSPC) or quota exceeded (EDQUOT). This ensures write operations can continue even when the current branch is full, improving the reliability of the union filesystem.

## Configuration

### Settings Structure
```rust
pub struct MoveOnENOSPC {
    pub enabled: bool,
    pub policy: CreatePolicy,  // Default: "pfrd"
}
```

### Configuration Options
- `moveonenospc=true` - Enable with default "pfrd" policy
- `moveonenospc=false` - Disable the feature
- `moveonenospc=<policy>` - Enable with specific create policy (e.g., "mfs", "lfs", "rand")

## High-Level Algorithm

```pseudocode
function handle_write_with_moveonenospc(fd, data, offset):
    result = try_write(fd, data, offset)
    
    if result.error in [ENOSPC, EDQUOT] AND moveonenospc.enabled:
        # Find current branch containing the file
        current_branch = find_file_branch(fd)
        if current_branch is None:
            return original_error
        
        # Select new branch using configured policy
        target_branch = select_target_branch(moveonenospc.policy, current_branch)
        if target_branch is None:
            return ENOSPC  # No suitable branch found
        
        # Move file to new branch
        new_fd = move_file_to_branch(fd, current_branch, target_branch)
        if new_fd.is_error():
            return original_error
        
        # Retry write on new location
        return try_write(new_fd, data, offset)
    
    return result
```

## Detailed Implementation

### 1. File Branch Detection

```pseudocode
function find_file_branch(fd: FileDescriptor) -> Option<Branch>:
    file_stat = fstat(fd)
    file_device_id = file_stat.st_dev
    
    for branch in branches:
        branch_stat = stat(branch.path)
        if branch_stat.st_dev == file_device_id:
            return Some(branch)
    
    return None
```

### 2. Target Branch Selection

```pseudocode
function select_target_branch(policy: CreatePolicy, exclude_branch: Branch) -> Option<Branch>:
    # Filter available branches
    available_branches = []
    for branch in branches:
        if branch == exclude_branch:
            continue
        if branch.is_readonly():
            continue
        if branch.free_space() < min_free_space:
            continue
        available_branches.append(branch)
    
    if available_branches.is_empty():
        return None
    
    # Apply create policy
    return policy.select(available_branches, file_path)
```

### 3. File Moving Process

```pseudocode
function move_file_to_branch(fd: FileDescriptor, src_branch: Branch, dst_branch: Branch) -> Result<FileDescriptor>:
    # Get file path relative to branch
    file_path = get_relative_path(fd, src_branch)
    src_full_path = src_branch.path + file_path
    dst_full_path = dst_branch.path + file_path
    
    # Create directory structure on target branch
    dst_dir = dirname(dst_full_path)
    clone_directory_path(src_branch, dst_branch, dst_dir)
    
    # Create temporary file on target
    temp_path = create_temp_file(dst_dir)
    
    try:
        # Copy file contents and metadata
        clone_file_data(src_full_path, temp_path)
        clone_file_metadata(src_full_path, temp_path)
        
        # Get original file flags (without creation flags)
        original_flags = get_file_flags(fd)
        clean_flags = original_flags & ~(O_CREAT | O_EXCL | O_TRUNC)
        
        # Atomic rename to final location
        rename(temp_path, dst_full_path)
        
        # Open new file
        new_fd = open(dst_full_path, clean_flags)
        
        # Replace original file descriptor
        dup2(new_fd, fd)
        close(new_fd)
        
        # Remove original file
        unlink(src_full_path)
        
        return Ok(fd)
        
    catch error:
        # Cleanup on failure
        unlink(temp_path)
        return Err(error)
```

### 4. File Cloning Details

```pseudocode
function clone_file_data(src: Path, dst: Path):
    src_fd = open(src, O_RDONLY)
    dst_fd = open(dst, O_WRONLY)
    
    # Copy all data
    while (data = read(src_fd, BUFFER_SIZE)):
        write(dst_fd, data)
    
    close(src_fd)
    close(dst_fd)

function clone_file_metadata(src: Path, dst: Path):
    # Copy extended attributes
    xattrs = listxattr(src)
    for attr in xattrs:
        value = getxattr(src, attr)
        setxattr(dst, attr, value)
    
    # Copy ownership
    stat = lstat(src)
    chown(dst, stat.uid, stat.gid)
    
    # Copy permissions
    chmod(dst, stat.mode)
    
    # Copy timestamps
    utimens(dst, stat.atime, stat.mtime)
```

### 5. Directory Path Cloning

```pseudocode
function clone_directory_path(src_branch: Branch, dst_branch: Branch, rel_path: Path):
    components = split_path(rel_path)
    current_path = ""
    
    for component in components:
        current_path = join(current_path, component)
        src_dir = join(src_branch.path, current_path)
        dst_dir = join(dst_branch.path, current_path)
        
        if not exists(dst_dir):
            # Get source directory metadata
            stat = lstat(src_dir)
            
            # Create directory with same permissions
            mkdir(dst_dir, stat.mode)
            
            # Copy metadata
            chown(dst_dir, stat.uid, stat.gid)
            utimens(dst_dir, stat.atime, stat.mtime)
            
            # Copy extended attributes
            copy_xattrs(src_dir, dst_dir)
```

## Error Handling

### Failure Scenarios
1. **No suitable branch found**: Return original ENOSPC error
2. **File not found on any branch**: Return original error
3. **Clone operation fails**: Cleanup and return original error
4. **Atomic rename fails**: Cleanup temp file and return original error

### Cleanup Process
```pseudocode
function cleanup_on_failure(temp_file: Option<Path>, opened_fds: Vec<FileDescriptor>):
    if temp_file.exists():
        unlink(temp_file)
    
    for fd in opened_fds:
        close(fd)
```

## Thread Safety

### Mutex Requirements
- File-level mutex to prevent concurrent moves of the same file
- Branch selection must be atomic to prevent race conditions
- File descriptor replacement must be atomic

### Synchronization Points
1. Before checking for ENOSPC - acquire file write lock
2. During branch selection - read lock on branch list
3. During file move - exclusive lock on file
4. After successful move - release all locks

## Integration Points

### Write Operations
1. **Direct I/O Path**: Hook into `write_direct_io` after `pwrite` fails
2. **Cached I/O Path**: Hook into `write_cached` after `pwriten` fails
3. **Error Detection**: Check for ENOSPC and EDQUOT specifically

### Configuration System
1. Add `moveonenospc` to configuration map
2. Support parsing of boolean and policy values
3. Integrate with xattr-based runtime configuration

## Testing Strategy

### Unit Tests
1. Test configuration parsing (true/false/policy names)
2. Test branch selection with various policies
3. Test file moving logic with mocked filesystem
4. Test error handling and cleanup

### Integration Tests
1. Fill a branch and verify automatic file movement
2. Test with different create policies
3. Test concurrent writes to same file
4. Test quota-based failures (EDQUOT)
5. Test edge cases (no available branches, all branches full)

## Performance Considerations

1. **Lazy Evaluation**: Only check moveonenospc on actual ENOSPC errors
2. **Metadata Caching**: Cache branch free space to avoid repeated statvfs calls
3. **Efficient Copying**: Use sendfile or copy_file_range where available
4. **Minimal Locking**: Use fine-grained locks per file, not global locks

## Rust Implementation Notes

### No Unsafe Code
- Use `std::fs` for all file operations
- Use `nix` crate for dup2 functionality
- Use `parking_lot` for efficient mutexes

### Cross-Platform Compatibility
- Avoid libc dependencies
- Use portable system calls via `nix` crate
- Handle platform differences in xattr operations

### Error Mapping
```rust
match error.kind() {
    std::io::ErrorKind::StorageFull => libc::ENOSPC,
    std::io::ErrorKind::Other => {
        // Check for EDQUOT via error code
        if error.raw_os_error() == Some(122) { // EDQUOT
            122
        } else {
            error.raw_os_error().unwrap_or(libc::EIO)
        }
    }
    _ => // map other errors
}
```

## Expected Behavior

### Success Case
1. Application writes to file on Branch A
2. Branch A returns ENOSPC
3. mergerfs finds file on Branch A
4. Policy selects Branch B with space
5. File moved from Branch A to Branch B
6. Write retried on Branch B succeeds
7. Application sees successful write

### Failure Case  
1. Application writes to file
2. All branches are full
3. moveonenospc cannot find suitable branch
4. Original ENOSPC returned to application

### Transparency
- Applications should not be aware of file movement
- File descriptor remains valid after move
- All file attributes preserved
- Atomic operation from application perspective