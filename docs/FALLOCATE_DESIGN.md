# Fallocate Operation Design

## Overview

The `fallocate` operation allows applications to preallocate or manipulate disk space for a file. This is useful for:
- Ensuring sufficient disk space before writing large files
- Improving write performance by reducing fragmentation
- Creating sparse files efficiently
- Punching holes in files to reclaim space

## C++ Implementation Analysis

### Core Structure

The C++ mergerfs implementation of fallocate is straightforward:

```cpp
// fuse_fallocate.cpp
namespace FUSE {
  int fallocate(const uint64_t fh_, int mode_, off_t offset_, off_t len_) {
    FileInfo *fi = reinterpret_cast<FileInfo*>(fh_);
    return l::fallocate(fi->fd, mode_, offset_, len_);
  }
}

// Platform-specific implementations:
// Linux: Uses native ::fallocate()
// POSIX: Uses ::posix_fallocate() (mode must be 0)
// macOS/unsupported: Returns EOPNOTSUPP
```

### Key Observations

1. **File Handle Based**: Operations are performed on already-opened file descriptors
2. **No Policy Involvement**: Direct passthrough to system call
3. **Platform Variations**:
   - Linux: Full support with all modes
   - POSIX: Only supports mode=0 (basic preallocation)
   - Others: Not supported

4. **Error Handling**: Simple errno passthrough

## Rust Implementation Design

### Function Signature

```rust
fn fallocate(
    &self,
    _req: &Request<'_>,
    ino: u64,
    fh: u64,
    offset: i64,
    length: i64,
    mode: i32,
    reply: ReplyEmpty,
)
```

### Implementation Strategy

1. **File Handle Lookup**: Get the file descriptor from the handle
2. **Platform-Specific Call**: Use appropriate system call based on platform
3. **Error Mapping**: Convert system errors to FUSE errors

### Fallocate Modes

```rust
// Linux fallocate flags
const FALLOC_FL_KEEP_SIZE: i32 = 0x01;      // Don't extend file size
const FALLOC_FL_PUNCH_HOLE: i32 = 0x02;     // Deallocate range
const FALLOC_FL_COLLAPSE_RANGE: i32 = 0x08; // Remove range from file
const FALLOC_FL_ZERO_RANGE: i32 = 0x10;     // Zero out range
const FALLOC_FL_INSERT_RANGE: i32 = 0x20;   // Insert space in file
const FALLOC_FL_UNSHARE_RANGE: i32 = 0x40;  // Unshare COW blocks
```

### Cross-Platform Approach

Since we need Alpine Linux/MUSL compatibility without libc:

1. **Linux**: Use `libc::fallocate` through nix crate or direct syscall
2. **Other platforms**: Return EOPNOTSUPP (95)

### Pseudocode

```
function fallocate(ino, fh, offset, length, mode):
    # Get file handle
    file_handle = get_file_handle(fh)
    if not file_handle:
        return EBADF
    
    # Platform-specific implementation
    if platform == "linux":
        result = syscall_fallocate(file_handle.fd, mode, offset, length)
    else:
        # POSIX or unsupported
        if mode != 0:
            return EOPNOTSUPP
        result = posix_fallocate(file_handle.fd, offset, length)
    
    if result < 0:
        return errno_to_fuse_error(errno)
    
    return OK
```

## Error Handling

Common errors:
- `EBADF`: Invalid file handle
- `ENOSPC`: Insufficient disk space
- `EOPNOTSUPP`: Operation not supported (wrong mode or platform)
- `EINVAL`: Invalid parameters
- `EIO`: I/O error

## Testing Considerations

1. **Basic Preallocation**: Test mode=0 allocation
2. **Keep Size**: Test FALLOC_FL_KEEP_SIZE flag
3. **Punch Hole**: Test creating sparse files (if supported)
4. **Error Cases**: Test ENOSPC, invalid parameters
5. **Cross-Platform**: Verify EOPNOTSUPP on non-Linux

## Implementation Notes

- No branch selection needed (operates on existing handle)
- No policy involvement (direct passthrough)
- Must handle platform differences gracefully
- Consider using nix crate for portable fallocate support