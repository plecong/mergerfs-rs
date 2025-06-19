# fsyncdir Implementation Documentation

## Overview

The `fsyncdir` operation in mergerfs is a FUSE callback that synchronizes a directory's contents to persistent storage. This ensures that directory metadata changes (like file creation, deletion, or rename operations) are flushed to disk.

## C++ Implementation Analysis

### Core Implementation (`fuse_fsyncdir.cpp`)

The C++ implementation is notably simple:

```cpp
namespace l
{
  static
  int
  fsyncdir(const DirInfo *di_,
           const int      isdatasync_)
  {
    int rv;

    rv    = -1;
    errno = ENOSYS;

    return ((rv == -1) ? -errno : 0);
  }
}

namespace FUSE
{
  int
  fsyncdir(const fuse_file_info_t *ffi_,
           int                     isdatasync_)
  {
    DirInfo *di = reinterpret_cast<DirInfo*>(ffi_->fh);

    return l::fsyncdir(di,isdatasync_);
  }
}
```

### Key Observations

1. **No-Op Implementation**: The C++ implementation always returns `ENOSYS` (Function not implemented), making it effectively a no-op.

2. **Parameters**:
   - `ffi_`: FUSE file info structure containing the file handle
   - `isdatasync_`: Flag indicating whether this is a data-only sync (vs full metadata sync)

3. **DirInfo Structure**: The implementation extracts a `DirInfo` pointer from the file handle but doesn't actually use it.

4. **Return Value**: Always returns `ENOSYS` error code, indicating the operation is not supported.

## Design Rationale

The no-op implementation suggests that:

1. **Directory sync is handled by underlying filesystems**: Since mergerfs is a union filesystem that operates on top of existing filesystems, directory synchronization is likely handled by the underlying filesystems themselves.

2. **POSIX compliance**: Returning `ENOSYS` is POSIX-compliant behavior for operations that are not supported by the filesystem.

3. **Performance consideration**: Avoiding explicit directory syncs may improve performance, especially when multiple branches are involved.

## Rust Implementation Plan

For the Rust implementation, we should:

1. Match the C++ behavior by returning `ENOSYS`
2. Extract the directory handle from the file handle parameter
3. Log the operation for debugging purposes
4. Maintain compatibility with the original implementation

### Implementation Steps

1. Add the `fsyncdir` method to the `Filesystem` trait implementation
2. Extract the directory handle from the file handle
3. Return `ENOSYS` error code
4. Add appropriate tracing/logging

## Testing Considerations

Since this is a no-op operation:
- Tests should verify that `fsyncdir` returns `ENOSYS`
- Tests should ensure the operation doesn't crash or corrupt state
- Integration tests should verify that directory operations still work correctly without explicit fsync