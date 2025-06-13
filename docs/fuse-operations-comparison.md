# FUSE Operations: C++ vs Rust Implementation Comparison

## Overview

This document compares the FUSE operations implemented in the original mergerfs C++ code with our Rust implementation, identifying gaps and implementation differences.

## Implementation Status

### ✅ Implemented Operations (13/40+)

| Operation | C++ File | Rust Status | Notes |
|-----------|----------|-------------|-------|
| `lookup` | fuse_lookup.cpp | ✅ Implemented | Basic implementation, no policy-based search |
| `getattr` | fuse_getattr.cpp | ✅ Implemented | Basic attributes, no caching |
| `open` | fuse_open.cpp | ✅ Implemented | Simple version, no direct I/O support |
| `read` | fuse_read.cpp | ✅ Implemented | Basic read, no readahead optimization |
| `write` | fuse_write.cpp | ✅ Implemented | Fixed to support offsets, no moveonenospc |
| `create` | fuse_create.cpp | ✅ Implemented | Uses create policy correctly |
| `mkdir` | fuse_mkdir.cpp | ✅ Implemented | Uses create policy |
| `rmdir` | fuse_rmdir.cpp | ✅ Implemented | All branches behavior needed |
| `unlink` | fuse_unlink.cpp | ✅ Implemented | All branches behavior needed |
| `readdir` | fuse_readdir.cpp | ✅ Partial | Basic version, no readdir_plus |
| `setattr` | fuse_setattr.cpp | ✅ Implemented | Handles chmod, chown, truncate, utimens |
| `flush` | fuse_flush.cpp | ✅ Implemented | Basic no-op implementation |
| `fsync` | fuse_fsync.cpp | ✅ Implemented | Basic no-op implementation |

### ❌ Missing Core Operations (27+)

#### Essential File Operations
| Operation | C++ File | Purpose | Priority |
|-----------|----------|---------|----------|
| `statfs` | fuse_statfs.cpp | Filesystem statistics (df, etc) | HIGH |
| `rename` | fuse_rename.cpp | Move/rename files and directories | HIGH |
| `symlink` | fuse_symlink.cpp | Create symbolic links | HIGH |
| `readlink` | fuse_readlink.cpp | Read symbolic link target | HIGH |
| `link` | fuse_link.cpp | Create hard links | HIGH |
| `release` | fuse_release.cpp | Close file handle (cleanup) | HIGH |
| `access` | fuse_access.cpp | Check access permissions | MEDIUM |
| `mknod` | fuse_mknod.cpp | Create special files | MEDIUM |
| `truncate` | fuse_truncate.cpp | Resize file (not via setattr) | MEDIUM |

#### Extended Attributes
| Operation | C++ File | Purpose | Priority |
|-----------|----------|---------|----------|
| `getxattr` | fuse_getxattr.cpp | Get extended attribute | MEDIUM |
| `setxattr` | fuse_setxattr.cpp | Set extended attribute | MEDIUM |
| `listxattr` | fuse_listxattr.cpp | List extended attributes | MEDIUM |
| `removexattr` | fuse_removexattr.cpp | Remove extended attribute | MEDIUM |

#### Directory Operations
| Operation | C++ File | Purpose | Priority |
|-----------|----------|---------|----------|
| `opendir` | fuse_opendir.cpp | Open directory handle | MEDIUM |
| `releasedir` | fuse_releasedir.cpp | Close directory handle | MEDIUM |
| `fsyncdir` | fuse_fsyncdir.cpp | Sync directory | LOW |

#### Advanced Operations
| Operation | C++ File | Purpose | Priority |
|-----------|----------|---------|----------|
| `ioctl` | fuse_ioctl.cpp | Device control (mergerfs control) | HIGH |
| `poll` | fuse_poll.cpp | Check I/O readiness | LOW |
| `lock` | fuse_lock.cpp | POSIX locking | LOW |
| `flock` | fuse_flock.cpp | BSD locking | LOW |
| `fallocate` | fuse_fallocate.cpp | Pre-allocate space | LOW |
| `ftruncate` | fuse_ftruncate.cpp | Truncate open file | LOW |
| `copy_file_range` | fuse_copy_file_range.cpp | Server-side copy | LOW |

## Key Implementation Differences

### 1. Policy System
**C++ Implementation:**
- Policies for: access, chmod, chown, create, getattr, link, mkdir, mknod, open, readlink, rename, rmdir, setattr, symlink, truncate, unlink, utimens
- Each operation can have a different policy
- Runtime configurable

**Rust Implementation:**
- Only create policy implemented
- No per-operation policy configuration
- Limited to compile-time policy selection

### 2. File Handle Management
**C++ Implementation:**
```cpp
struct FileInfo {
    int fd;
    int direct_io;
    int real_fd;
    uint64_t fh;
    mutex_t mutex;
};
```
- Tracks file descriptors per branch
- Supports direct I/O
- Thread-safe with mutex

**Rust Implementation:**
- No file handle tracking
- Operations work directly on paths
- No direct I/O support

### 3. Error Handling
**C++ Implementation:**
- Sophisticated error aggregation across branches
- Priority-based error selection
- Detailed errno mapping

**Rust Implementation:**
- Basic error handling
- Limited error aggregation
- Simple errno mapping

### 4. Directory Reading
**C++ Implementation:**
- Multiple readdir implementations (seq, cor, cosr, plus)
- Configurable behavior
- Performance optimizations

**Rust Implementation:**
- Single basic readdir
- No readdir_plus support
- No performance optimizations

### 5. Special Features Missing

#### moveonenospc
When a write fails due to ENOSPC, C++ mergerfs can move the file to another branch with space.

#### symlinkify
Convert files to symlinks based on age to save space.

#### Path Preservation
Many policies support "existing path" variants to keep related files together.

#### Security Contexts
SELinux and other security context support.

## Implementation Roadmap

### Phase 1: Essential Operations (Required for basic compatibility)
1. `statfs` - Filesystem statistics
2. `rename` - File/directory renaming
3. `symlink`/`readlink` - Symbolic link support
4. `link` - Hard link support
5. `release` - Proper file handle cleanup

### Phase 2: Extended Functionality
1. `access` - Permission checking
2. Extended attributes (xattr) operations
3. `opendir`/`releasedir` - Directory handle management
4. `ioctl` - mergerfs runtime configuration

### Phase 3: Advanced Features
1. Multiple readdir implementations
2. moveonenospc support
3. Direct I/O support
4. File locking operations
5. Advanced caching

## Code Structure Recommendations

### 1. File Handle Management
Create a proper file handle system:
```rust
pub struct FileHandle {
    pub branch_idx: usize,
    pub path: PathBuf,
    pub flags: i32,
    pub direct_io: bool,
}

pub struct FileHandleManager {
    handles: RwLock<HashMap<u64, FileHandle>>,
    next_handle: AtomicU64,
}
```

### 2. Policy Integration
Extend policy system to all operations:
```rust
pub struct PolicyConfig {
    pub access: Box<dyn SearchPolicy>,
    pub chmod: Box<dyn ActionPolicy>,
    pub chown: Box<dyn ActionPolicy>,
    pub create: Box<dyn CreatePolicy>,
    pub getattr: Box<dyn SearchPolicy>,
    pub link: Box<dyn ActionPolicy>,
    pub mkdir: Box<dyn CreatePolicy>,
    pub mknod: Box<dyn CreatePolicy>,
    pub open: Box<dyn SearchPolicy>,
    pub readlink: Box<dyn SearchPolicy>,
    pub rename: Box<dyn ActionPolicy>,
    pub rmdir: Box<dyn ActionPolicy>,
    pub setattr: Box<dyn ActionPolicy>,
    pub symlink: Box<dyn CreatePolicy>,
    pub truncate: Box<dyn ActionPolicy>,
    pub unlink: Box<dyn ActionPolicy>,
    pub utimens: Box<dyn ActionPolicy>,
}
```

### 3. Operation Traits
Define traits for consistent operation handling:
```rust
trait FuseOperation {
    fn execute(&self, req: &Request) -> Result<(), c_int>;
    fn policy_type(&self) -> PolicyType;
}
```

## Testing Requirements

Each new operation needs:
1. Unit tests for the operation logic
2. Integration tests via FUSE mount
3. Python tests for real-world scenarios
4. Comparison tests with C++ mergerfs behavior