# OpenDir and ReleaseDir Operations Design

## Overview

The `opendir` and `releasedir` operations in FUSE manage directory handles. Unlike file handles which are associated with specific file descriptors, directory handles are used to maintain state across multiple `readdir` calls.

## C++ Implementation Analysis

### OpenDir Operation

In the C++ mergerfs implementation:

```cpp
// fuse_opendir.cpp
int opendir(const char *fusepath_, fuse_file_info_t *ffi_)
{
    Config::Read cfg;
    
    // Create a new DirInfo object storing the directory path
    ffi_->fh = reinterpret_cast<uint64_t>(new DirInfo(fusepath_));
    
    // Disable flushing for directories
    ffi_->noflush = true;
    
    // Handle readdir caching configuration
    if(cfg->cache_readdir)
    {
        ffi_->keep_cache    = 1;
        ffi_->cache_readdir = 1;
    }
    
    return 0;
}
```

### ReleaseDir Operation

```cpp
// fuse_releasedir.cpp
int releasedir(const fuse_file_info_t *ffi_)
{
    // Retrieve the DirInfo object
    DirInfo *di = reinterpret_cast<DirInfo*>(ffi_->fh);
    
    // Delete the DirInfo object
    delete di;
    
    return 0;
}
```

### DirInfo Structure

```cpp
// dirinfo.hpp
class DirInfo : public FH
{
public:
    DirInfo(const char *fusepath_)
        : FH(fusepath_)  // Store the directory path
    {
    }
};

// fh.hpp (base class)
class FH
{
public:
    std::string fusepath;
};
```

## Key Design Points

1. **Directory Handle Storage**: The C++ implementation stores a DirInfo object containing the directory path in the file handle field (`ffi_->fh`).

2. **No Actual Directory Opening**: Unlike file operations, `opendir` doesn't actually open any directory descriptors. It just creates a handle to track the directory path.

3. **State Management**: The directory handle is used to maintain context between `opendir` and subsequent `readdir` calls.

4. **Caching Configuration**: The implementation respects the `cache_readdir` configuration option.

5. **Simple Lifecycle**: 
   - `opendir`: Allocate DirInfo object
   - `readdir`: Use DirInfo to access directory path
   - `releasedir`: Deallocate DirInfo object

## Rust Implementation Design

### Data Structure

```rust
#[derive(Debug)]
pub struct DirHandle {
    pub path: PathBuf,
    pub ino: u64,
}
```

### OpenDir Implementation

```rust
pub fn opendir(&mut self, _req: &Request, ino: u64, flags: i32, reply: ReplyOpen) {
    // 1. Resolve inode to path
    let path = match self.inode_to_path(ino) {
        Ok(p) => p,
        Err(e) => return reply.error(e),
    };
    
    // 2. Check if path exists and is a directory
    // (Note: We don't actually open the directory)
    
    // 3. Create directory handle
    let handle = DirHandle {
        path: path.clone(),
        ino,
    };
    
    // 4. Store handle and generate handle ID
    let fh = self.generate_dir_handle_id();
    self.dir_handles.insert(fh, handle);
    
    // 5. Reply with handle
    reply.opened(fh, flags);
}
```

### ReleaseDir Implementation

```rust
pub fn releasedir(&mut self, _req: &Request, ino: u64, fh: u64, flags: i32, reply: ReplyEmpty) {
    // Remove the directory handle
    self.dir_handles.remove(&fh);
    reply.ok();
}
```

### Integration with ReadDir

The existing `readdir` implementation would need to be updated to use directory handles:

```rust
pub fn readdir(&mut self, _req: &Request, ino: u64, fh: u64, offset: i64, reply: ReplyDirectory) {
    // Retrieve directory handle
    let handle = match self.dir_handles.get(&fh) {
        Some(h) => h,
        None => {
            // Fallback to inode-based lookup for compatibility
            let path = match self.inode_to_path(ino) {
                Ok(p) => p,
                Err(e) => return reply.error(e),
            };
            // Use path directly
        }
    };
    
    // Continue with existing readdir logic using handle.path
}
```

## Implementation Considerations

1. **Handle Management**: Use a HashMap to store directory handles, similar to file handles.

2. **Handle ID Generation**: Reuse existing handle generation logic or create a separate counter for directory handles.

3. **Backward Compatibility**: The `readdir` implementation should still work without `opendir` being called first (some FUSE clients may not use `opendir`).

4. **Thread Safety**: Directory handle storage must be thread-safe if using multi-threaded FUSE.

5. **Resource Cleanup**: Ensure handles are properly cleaned up on `releasedir`.

## Testing Strategy

1. **Unit Tests**:
   - Test handle creation and retrieval
   - Test handle cleanup
   - Test multiple concurrent directory handles

2. **Integration Tests**:
   - Test normal directory listing flow (opendir → readdir → releasedir)
   - Test multiple readdir calls with same handle
   - Test handle cleanup on process termination
   - Test concurrent directory access

## Notes

- The C++ implementation's approach is minimal - it just stores the path for later use
- No actual directory file descriptors are opened or maintained
- The implementation mainly serves to provide context between FUSE operations
- Some FUSE clients may not call `opendir` before `readdir`, so the implementation must handle both cases