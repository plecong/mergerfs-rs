# Access Operation Design

## Overview

The `access()` FUSE operation checks whether the calling process has permission to access a file or directory with specific modes. This is crucial for applications that want to check permissions before attempting operations.

## C++ Implementation Analysis

### Function Flow
```pseudocode
FUSE::access(path, mask):
    1. Get FUSE context (uid, gid)
    2. Set effective UID/GID using ugid::Set
    3. Get access search policy from config
    4. Call internal access implementation
    
l::access(policy, branches, path, mode):
    1. Use search policy to find branches containing the file
    2. Take first branch from search results
    3. Construct full path: branch + path
    4. Call fs::eaccess(fullpath, mode)
    5. Return result (0 or -errno)

fs::eaccess(path, mode):
    1. Call faccessat(AT_FDCWD, path, mode, AT_EACCESS)
    2. AT_EACCESS flag uses effective UID/GID for check
```

### Key Components

1. **Search Policy Integration**: Uses configurable search policy to find file
2. **Permission Context**: Temporarily sets effective UID/GID from FUSE context
3. **System Call**: Uses `faccessat` with `AT_EACCESS` flag
4. **Error Handling**: Returns -errno on failure

### Access Mode Flags
- `F_OK` (0): Check file existence
- `R_OK` (4): Check read permission
- `W_OK` (2): Check write permission
- `X_OK` (1): Check execute permission

## Rust Implementation Design

### Approach
Since we cannot use libc and need Alpine Linux compatibility, we'll implement access checks using Rust's standard library:

1. **File Metadata**: Use `std::fs::metadata()` to get file permissions
2. **Permission Checking**: Manually check mode bits against requested access
3. **User Context**: Use FUSE context UID/GID for permission evaluation
4. **Search Policy**: Integrate with existing search policy system

### Implementation Steps

```rust
fn access(&self, req: &Request, path: &Path, mask: i32) -> Result<()> {
    // 1. Get search policy
    let policy = self.config.get_search_policy("access");
    
    // 2. Find branches containing the file
    let branches = policy.search(&self.branches, path)?;
    
    // 3. Check access on first branch
    if branches.is_empty() {
        return Err(libc::ENOENT);
    }
    
    let full_path = branches[0].join(path);
    
    // 4. Get file metadata
    let metadata = fs::metadata(&full_path)?;
    let permissions = metadata.permissions();
    
    // 5. Check requested access against permissions
    check_access(req.uid(), req.gid(), &metadata, mask)?;
    
    Ok(())
}
```

### Permission Checking Algorithm

```rust
fn check_access(uid: u32, gid: u32, metadata: &Metadata, mask: i32) -> Result<()> {
    // Special case: root can access anything (except execute without any x bit)
    if uid == 0 {
        if mask & X_OK != 0 && !has_any_execute(metadata) {
            return Err(EACCES);
        }
        return Ok(());
    }
    
    let file_uid = metadata.uid();
    let file_gid = metadata.gid();
    let mode = metadata.mode();
    
    // Determine which permission bits to check
    let perm_bits = if uid == file_uid {
        // User permissions (bits 6-8)
        (mode >> 6) & 0o7
    } else if gid == file_gid || user_in_group(uid, file_gid) {
        // Group permissions (bits 3-5)
        (mode >> 3) & 0o7
    } else {
        // Other permissions (bits 0-2)
        mode & 0o7
    };
    
    // Check each requested permission
    if mask & R_OK != 0 && perm_bits & 0o4 == 0 {
        return Err(EACCES);
    }
    if mask & W_OK != 0 && perm_bits & 0o2 == 0 {
        return Err(EACCES);
    }
    if mask & X_OK != 0 && perm_bits & 0o1 == 0 {
        return Err(EACCES);
    }
    
    Ok(())
}
```

### Differences from C++ Implementation

1. **No faccessat**: We use metadata and manual permission checking
2. **No setuid/setgid**: We check permissions based on FUSE context directly
3. **Group membership**: Simplified - only checks primary group
4. **Effective vs Real UID**: FUSE always provides effective UID/GID

### Error Codes

- `ENOENT`: File doesn't exist
- `EACCES`: Permission denied
- `ENOTDIR`: Component of path not a directory
- Other errors propagated from filesystem operations

### Testing Strategy

1. **Unit Tests**:
   - Test permission checking logic
   - Test various uid/gid/mode combinations
   - Test root user special cases
   
2. **Integration Tests**:
   - Create files with specific permissions
   - Test access checks with different users
   - Test all mask combinations (F_OK, R_OK, W_OK, X_OK)
   - Test directory vs file access
   - Test with different search policies

### Alpine Linux Compatibility

The implementation avoids:
- Direct system calls
- libc dependencies
- Platform-specific constants (hardcode F_OK=0, R_OK=4, W_OK=2, X_OK=1)

Uses only:
- Rust standard library fs operations
- Cross-platform metadata access
- Portable permission bit manipulation