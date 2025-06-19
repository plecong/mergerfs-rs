# Direct I/O Implementation in mergerfs

This document describes how direct I/O is implemented in the original C++ mergerfs implementation.

## Overview

Direct I/O is a file I/O mode that bypasses the kernel's page cache, allowing applications to perform reads and writes directly to/from the underlying storage. In mergerfs, direct I/O support is configurable and affects how file operations are performed.

## Configuration

### Primary Configuration: cache.files

The main way to configure direct I/O behavior is through the `cache.files` option, which can have the following values:

- **libfuse**: Uses libfuse's default caching behavior, respecting the configured `direct_io`, `kernel_cache`, and `auto_cache` settings
- **off**: Forces direct I/O (sets `direct_io=1`, `keep_cache=0`, `auto_cache=0`)
- **partial**: Disables direct I/O but doesn't keep cache (sets `direct_io=0`, `keep_cache=0`, `auto_cache=0`)
- **full**: Disables direct I/O and keeps cache (sets `direct_io=0`, `keep_cache=1`, `auto_cache=0`)
- **auto-full**: Disables direct I/O with automatic cache management (sets `direct_io=0`, `keep_cache=0`, `auto_cache=1`)
- **per-process**: Enables caching for specific processes listed in `cache.files.process-names`, direct I/O for others

### Legacy Options (Deprecated)

- `direct_io`: Boolean flag to bypass page cache (deprecated, use `cache.files=off` instead)
- `kernel_cache`: Do not invalidate data cache on file open (deprecated, use `cache.files=full` instead)
- `auto_cache`: Invalidate data cache if file mtime or size change (deprecated, use `cache.files=auto-full` instead)

### Additional Options

- `direct_io_allow_mmap`: Boolean flag (default: true) that enables memory mapping support even when direct I/O is enabled
- `parallel_direct_writes`: Boolean flag (default: true) that enables parallel writes when direct I/O is active

## Implementation Details

### 1. Configuration Propagation

The direct I/O configuration is propagated through the FUSE file info structure during open and create operations:

```cpp
// In fuse_open.cpp and fuse_create.cpp
static void
_config_to_ffi_flags(Config::Read &cfg_, const int tid_, fuse_file_info_t *ffi_)
{
  switch(cfg_->cache_files)
  {
    case CacheFiles::ENUM::LIBFUSE:
      ffi_->direct_io  = cfg_->direct_io;
      ffi_->keep_cache = cfg_->kernel_cache;
      ffi_->auto_cache = cfg_->auto_cache;
      break;
    case CacheFiles::ENUM::OFF:
      ffi_->direct_io  = 1;
      ffi_->keep_cache = 0;
      ffi_->auto_cache = 0;
      break;
    // ... other cases
  }
  
  if(cfg_->parallel_direct_writes == true)
    ffi_->parallel_direct_writes = ffi_->direct_io;
}
```

### 2. FileInfo Storage

The direct I/O flag is stored in the FileInfo structure for each open file:

```cpp
class FileInfo : public FH
{
public:
  FileInfo(const int fd_, const Branch &branch_, const char *fusepath_, const bool direct_io_)
    : FH(fusepath_),
      fd(fd_),
      branch(branch_),
      direct_io(direct_io_)
  {
  }
  
  // ...
  u32 direct_io:1;  // Single bit flag
};
```

### 3. Read Operations

Read operations check the direct_io flag and use different code paths:

```cpp
// In fuse_read.cpp
int read(const fuse_file_info_t *ffi_, char *buf_, size_t size_, off_t offset_)
{
  FileInfo *fi = reinterpret_cast<FileInfo*>(ffi_->fh);
  
  if(fi->direct_io)
    return l::read_direct_io(fi->fd,buf_,size_,offset_);
    
  return l::read_cached(fi->fd,buf_,size_,offset_);
}
```

Both `read_direct_io` and `read_cached` ultimately call `fs::pread()`, but the direct_io flag in the FUSE file info affects kernel caching behavior.

### 4. Write Operations

Write operations also check the direct_io flag and handle writes differently:

```cpp
// In fuse_write.cpp
static int
write(const fuse_file_info_t *ffi_, const char *buf_, const size_t count_, const off_t offset_)
{
  FileInfo *fi = reinterpret_cast<FileInfo*>(ffi_->fh);
  
  std::lock_guard<std::mutex> guard(fi->mutex);
  
  if(fi->direct_io)
    return l::write_direct_io(buf_,count_,offset_,fi);
    
  return l::write_cached(buf_,count_,offset_,fi);
}
```

Key differences:
- **direct_io writes**: Return actual bytes written (including short writes) or -errno
- **cached writes**: Return `count` on success or -errno on error, use `fs::pwriten()` to write all data

### 5. Initialization

During FUSE initialization, the `direct_io_allow_mmap` capability is requested if configured:

```cpp
// In fuse_init.cpp
l::want_if_capable(conn_,FUSE_CAP_DIRECT_IO_ALLOW_MMAP,&cfg->direct_io_allow_mmap);
```

## Behavior Summary

### When direct_io is enabled:
1. File operations bypass the kernel page cache
2. Reads and writes go directly to the underlying filesystem
3. Each read/write operation results in actual I/O
4. Better for large sequential I/O or when data coherency is critical
5. Memory mapping can still be allowed if `direct_io_allow_mmap` is true

### When direct_io is disabled:
1. File operations use the kernel page cache
2. Reads may be satisfied from cache
3. Writes may be buffered in cache
4. Better for small random I/O or frequently accessed files
5. Cache behavior depends on `keep_cache` and `auto_cache` settings

## Process-Specific Caching

The `per-process` cache mode allows selective caching based on the process name:
- Processes listed in `cache.files.process-names` get cached I/O
- All other processes get direct I/O
- Default process list includes: "rtorrent|qbittorrent-nox"

## Thread Safety

- Write operations acquire a mutex when using direct I/O if parallel writes are enabled
- This prevents issues with concurrent writes, especially during file migration on ENOSPC

## Integration with Other Features

1. **Writeback Cache**: When writeback caching is enabled, O_WRONLY is changed to O_RDWR to allow kernel read requests
2. **moveonenospc**: Direct I/O writes can trigger file migration on ENOSPC errors
3. **Passthrough**: Direct I/O settings affect passthrough mode behavior