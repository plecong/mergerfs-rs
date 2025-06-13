# FUSE Operations Implementation

## Overview

mergerfs implements the FUSE (Filesystem in Userspace) interface by providing handlers for all filesystem operations. Each operation is implemented in a separate `fuse_*.cpp` file and follows a consistent pattern of policy application and branch selection.

## Operation Categories

### File Operations
Operations that work with file content and metadata.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `open` | `fuse_open.cpp` | Open file for reading/writing | Search |
| `create` | `fuse_create.cpp` | Create new file | Create |
| `read` | `fuse_read.cpp` | Read file content | N/A (uses file handle) |
| `write` | `fuse_write.cpp` | Write file content | N/A (uses file handle) |
| `truncate` | `fuse_truncate.cpp` | Truncate file to size | Action |
| `ftruncate` | `fuse_ftruncate.cpp` | Truncate via file descriptor | N/A (uses file handle) |
| `unlink` | `fuse_unlink.cpp` | Delete file | Action |
| `link` | `fuse_link.cpp` | Create hard link | Action + Create |
| `symlink` | `fuse_symlink.cpp` | Create symbolic link | Create |
| `readlink` | `fuse_readlink.cpp` | Read symbolic link target | Search |
| `flush` | `fuse_flush.cpp` | Flush file buffers | N/A (uses file handle) |
| `release` | `fuse_release.cpp` | Close file | N/A (cleanup) |
| `fsync` | `fuse_fsync.cpp` | Sync file to storage | N/A (uses file handle) |

### Directory Operations
Operations that work with directories and directory listing.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `mkdir` | `fuse_mkdir.cpp` | Create directory | Create |
| `rmdir` | `fuse_rmdir.cpp` | Remove directory | Action |
| `opendir` | `fuse_opendir.cpp` | Open directory for reading | Search |
| `readdir` | `fuse_readdir.cpp` | List directory contents | Search (all) |
| `readdir_plus` | `fuse_readdir_plus.cpp` | List with attributes | Search (all) |
| `releasedir` | `fuse_releasedir.cpp` | Close directory | N/A (cleanup) |
| `fsyncdir` | `fuse_fsyncdir.cpp` | Sync directory | Action |

### Metadata Operations
Operations that work with file/directory attributes.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `getattr` | `fuse_getattr.cpp` | Get file attributes | Search |
| `fgetattr` | `fuse_fgetattr.cpp` | Get attributes via FD | N/A (uses file handle) |
| `chmod` | `fuse_chmod.cpp` | Change permissions | Action |
| `fchmod` | `fuse_fchmod.cpp` | Change permissions via FD | N/A (uses file handle) |
| `chown` | `fuse_chown.cpp` | Change ownership | Action |
| `fchown` | `fuse_fchown.cpp` | Change ownership via FD | N/A (uses file handle) |
| `utimens` | `fuse_utimens.cpp` | Set file times | Action |
| `futimens` | `fuse_futimens.cpp` | Set file times via FD | N/A (uses file handle) |

### Extended Attributes
Operations for extended attribute support.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `getxattr` | `fuse_getxattr.cpp` | Get extended attribute | Search |
| `setxattr` | `fuse_setxattr.cpp` | Set extended attribute | Action |
| `listxattr` | `fuse_listxattr.cpp` | List extended attributes | Search |
| `removexattr` | `fuse_removexattr.cpp` | Remove extended attribute | Action |

### Advanced Operations
Specialized operations for performance and advanced features.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `copy_file_range` | `fuse_copy_file_range.cpp` | Efficient file copying | N/A (uses file handles) |
| `fallocate` | `fuse_fallocate.cpp` | Allocate file space | N/A (uses file handle) |
| `ioctl` | `fuse_ioctl.cpp` | Device control operations | Search |
| `poll` | `fuse_poll.cpp` | Poll for events | Search |
| `flock` | `fuse_flock.cpp` | File locking | N/A (uses file handle) |
| `mknod` | `fuse_mknod.cpp` | Create device node | Create |
| `statfs` | `fuse_statfs.cpp` | Get filesystem statistics | Special |

### Special Operations
Operations for FUSE lifecycle and special files.

| Operation | File | Purpose | Policy Type |
|-----------|------|---------|-------------|
| `init` | `fuse_init.cpp` | Initialize filesystem | N/A |
| `destroy` | `fuse_destroy.cpp` | Cleanup filesystem | N/A |
| `access` | `fuse_access.cpp` | Check file permissions | Search |
| `bmap` | `fuse_bmap.cpp` | Get block mapping | Search |

## Implementation Patterns

### Standard Operation Flow
All FUSE operations follow this general pattern:

```cpp
int FUSE::operation_name(const char *fusepath, /* other params */)
{
    Config::Read cfg;                    // Get read-only config
    const ugid::Set ugid(cfg->ugid);   // Set user/group context
    
    // 1. Apply policy to select branches
    std::vector<Branch*> branches;
    int rv = cfg->func.POLICY_TYPE(cfg->branches, fusepath, branches);
    if(rv < 0) return rv;
    
    // 2. Attempt operation on selected branches
    for(auto &branch : branches) {
        std::string fullpath = fs::path::make(branch->path, fusepath);
        rv = fs::operation_name(fullpath, /* params */);
        if(rv >= 0) return rv;  // Success
        // Continue to next branch on failure
    }
    
    return -errno;  // All branches failed
}
```

### File Handle Operations
Operations using file descriptors have a simpler pattern:

```cpp
int FUSE::operation_name(const fuse_file_info_t *ffi, /* other params */)
{
    FileInfo *fi = reinterpret_cast<FileInfo*>(ffi->fh);
    
    return fs::operation_name(fi->fd, /* params */);
}
```

### Directory Merge Operations
Directory listing operations must merge results from multiple branches:

```cpp
int FUSE::readdir(const fuse_file_info_t *ffi, fuse_dirents_t *buf)
{
    // Get all branches
    std::vector<Branch*> branches;
    cfg->func.search(cfg->branches, fusepath, branches);
    
    // Read from each branch and merge
    std::set<std::string> seen;
    for(auto &branch : branches) {
        // Read directory entries
        // Deduplicate against 'seen' set
        // Add to output buffer
    }
}
```

## Policy Integration

### Create Operations
Operations that create new files/directories use Create policies:

```cpp
// Examples: create, mkdir, symlink, mknod
int rv = cfg->func.create(cfg->branches, fusepath, branches);
```

Available create policies:
- `ff` (first found): First branch with sufficient space
- `mfs` (most free space): Branch with most available space
- `lfs` (least free space): Branch with least available space
- `eplfs`: Existing path, then least free space
- `epmfs`: Existing path, then most free space
- `rand`: Random selection
- `pfrd`: Proportional free random distribution

### Search Operations
Operations that read existing files use Search policies:

```cpp
// Examples: open, getattr, readlink, access
int rv = cfg->func.search(cfg->branches, fusepath, branches);
```

Available search policies:
- `ff` (first found): Return first match found
- `all`: Return all instances (for directory merging)

### Action Operations
Operations that modify existing files use Action policies:

```cpp
// Examples: unlink, chmod, chown, utimens, truncate
int rv = cfg->func.action(cfg->branches, fusepath, branches);
```

Available action policies:
- `all`: Operate on all instances
- `epall`: Existing path, then all
- `epff`: Existing path, then first found
- `epmfs`: Existing path, then most free space

## Special Cases

### Control File (`/.mergerfs`)
Special handling for runtime configuration:

```cpp
if(fusepath == CONTROLFILE) {
    // Handle configuration file specially
    return handle_control_file(/* params */);
}
```

### Hard Link Handling
Hard links require special Copy-on-Write logic when crossing branch boundaries:

```cpp
int FUSE::link(const char *from, const char *to)
{
    // Check if link crosses branch boundaries
    if(different_branches(from, to)) {
        // Implement copy-on-write
        return fs::cow::link(from, to);
    }
    // Normal hard link
    return fs::link(from, to);
}
```

### Inode Calculation
Custom inode calculation to maintain consistency:

```cpp
ino_t calculate_inode(const std::string &fusepath, const struct stat &st)
{
    switch(cfg->inodecalc) {
        case InodeCalc::PATH_HASH:
            return XXH64(fusepath.c_str(), fusepath.size(), 0);
        case InodeCalc::PASSTHROUGH:
            return st.st_ino;
        case InodeCalc::HYBRID:
            return (st.st_ino + XXH64(fusepath.c_str(), fusepath.size(), 0));
    }
}
```

## Error Handling

### Error Propagation
Operations follow consistent error handling:

```cpp
int rv = fs::operation(path, params);
if(rv == -1) {
    return -errno;  // Convert errno to negative value
}
return rv;  // Success
```

### Multi-Branch Error Handling
When operating on multiple branches, collect and prioritize errors:

```cpp
int error = ENOENT;  // Default error
for(auto &branch : branches) {
    rv = fs::operation(branch->path + fusepath, params);
    if(rv >= 0) return rv;  // Success
    
    // Prioritize certain errors
    if(errno == EACCES) error = EACCES;
    else if(errno == EROFS && error == ENOENT) error = EROFS;
}
return -error;
```

## Performance Optimizations

### Memory Pools
Directory operations use pre-allocated memory pools:

```cpp
extern LockedFixedMemPool<128 * 1024> g_DENTS_BUF_POOL;

auto buf = g_DENTS_BUF_POOL.alloc();
// Use buffer for directory reading
g_DENTS_BUF_POOL.free(buf);
```

### Caching
Configurable caching for metadata operations:

```cpp
if(cfg->cache_attr > 0) {
    // Use cached attributes if available
    if(cache_hit(fusepath, &st)) {
        return 0;
    }
}
```

### Parallel I/O
Some operations can be parallelized across branches:

```cpp
// For directory merging, read multiple branches concurrently
std::vector<std::future<int>> futures;
for(auto &branch : branches) {
    futures.push_back(std::async(std::launch::async, [&] {
        return read_directory(branch->path + fusepath);
    }));
}
```

## Operation-Specific Details

### `readdir` Implementation
Directory reading has multiple implementations for different access patterns:

- `seq`: Sequential reading (default)
- `cosr`: Concurrent sorting with readdir
- `cor`: Concurrent reading
- `cosr`: Concurrent sorting reading

### `copy_file_range` Implementation
Efficient copying with fallback strategies:

1. Try kernel `copy_file_range()` system call
2. Fall back to `sendfile()` for same filesystem
3. Fall back to read/write loop

### `fallocate` Implementation
Space allocation with platform-specific optimizations:

1. Linux: Use `fallocate()` system call
2. macOS: Use `fcntl(F_PREALLOCATE)`
3. POSIX: Use `posix_fallocate()`
4. Fallback: Write zeros

## Thread Safety

All FUSE operations are thread-safe through:

1. **Read-only configuration access**: Most operations only read configuration
2. **Per-file mutexes**: File operations use per-FileInfo mutexes
3. **Atomic operations**: Branch list updates use appropriate locking
4. **Immutable data**: Policy objects are immutable after initialization