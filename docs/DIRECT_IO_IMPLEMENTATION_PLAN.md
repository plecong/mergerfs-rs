# Direct I/O Implementation Plan for mergerfs-rs

Based on the analysis of the C++ implementation, here's the plan for implementing direct I/O support in the Rust version.

## 1. Configuration Changes

### Add CacheFiles Enum
```rust
// In src/config.rs
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CacheFiles {
    LibFuse,     // Use libfuse's default caching behavior
    Off,         // Force direct I/O
    Partial,     // No direct I/O, no cache keeping
    Full,        // No direct I/O, keep cache
    AutoFull,    // No direct I/O, auto cache management
    PerProcess,  // Process-specific caching
}

impl Default for CacheFiles {
    fn default() -> Self {
        CacheFiles::LibFuse
    }
}
```

### Add Configuration Fields
```rust
// In src/config.rs - add to Config struct
pub struct Config {
    // ... existing fields ...
    
    // Cache configuration
    pub cache_files: CacheFiles,
    pub cache_files_process_names: HashSet<String>,
    
    // Direct I/O related
    pub direct_io: bool,              // Legacy option
    pub kernel_cache: bool,           // Legacy option  
    pub auto_cache: bool,             // Legacy option
    pub direct_io_allow_mmap: bool,
    pub parallel_direct_writes: bool,
    
    // Cache timeouts
    pub cache_attr: u64,              // Attribute cache timeout in seconds
    pub cache_entry: u64,             // Entry cache timeout in seconds
    pub cache_negative_entry: u64,    // Negative entry cache timeout
    pub cache_statfs: u64,            // StatFS cache timeout
    pub cache_symlinks: bool,         // Enable symlink caching
    pub cache_readdir: bool,          // Enable readdir caching
}
```

## 2. FileHandle Changes

### Update FileHandle Structure
```rust
// In src/file_handle.rs
#[derive(Debug, Clone)]
pub struct FileHandle {
    pub ino: u64,
    pub path: PathBuf,
    pub flags: i32,
    pub branch_idx: Option<usize>,
    pub direct_io: bool,    // Set based on cache configuration
    pub fd: RawFd,          // Actual file descriptor
}
```

### Update create_handle Method
```rust
impl FileHandleManager {
    pub fn create_handle(
        &self, 
        ino: u64, 
        path: PathBuf, 
        flags: i32, 
        branch_idx: Option<usize>,
        direct_io: bool,  // New parameter
        fd: RawFd,       // New parameter
    ) -> u64 {
        // ... implementation
    }
}
```

## 3. FUSE Operation Changes

### Open Operation
```rust
// In src/fuse_fs.rs - open implementation
fn open(&self, _req: &Request, ino: u64, fh: &mut FileHandle, flags: u32) -> io::Result<ReplyOpen> {
    // Determine direct_io based on cache_files configuration
    let (direct_io, keep_cache, auto_cache) = self.determine_cache_flags(req.pid());
    
    // Set FUSE file info flags
    let mut reply = ReplyOpen::new(fh);
    reply.direct_io(direct_io);
    reply.keep_cache(keep_cache);
    reply.auto_cache(auto_cache);
    
    if self.config.read().parallel_direct_writes && direct_io {
        reply.parallel_direct_writes(true);
    }
    
    Ok(reply)
}
```

### Create Operation
Similar changes needed for the create operation to set direct_io flags.

### Read Operation
```rust
fn read(&self, _req: &Request, ino: u64, fh: u64, offset: i64, size: u32, ...) -> io::Result<ReplyData> {
    let handle = self.file_handles.get_handle(fh)
        .ok_or_else(|| io::Error::from_raw_os_error(libc::EBADF))?;
    
    if handle.direct_io {
        // Direct I/O read path
        self.read_direct_io(handle, offset, size)
    } else {
        // Cached read path
        self.read_cached(handle, offset, size)
    }
}
```

### Write Operation
```rust
fn write(&self, _req: &Request, ino: u64, fh: u64, offset: i64, data: &[u8], ...) -> io::Result<ReplyWrite> {
    let handle = self.file_handles.get_handle(fh)
        .ok_or_else(|| io::Error::from_raw_os_error(libc::EBADF))?;
    
    if handle.direct_io {
        // Direct I/O write path - return actual bytes written
        self.write_direct_io(handle, offset, data)
    } else {
        // Cached write path - write all data
        self.write_cached(handle, offset, data)
    }
}
```

## 4. Helper Methods

### Cache Flag Determination
```rust
impl FuseFS {
    fn determine_cache_flags(&self, pid: u32) -> (bool, bool, bool) {
        let config = self.config.read();
        
        match config.cache_files {
            CacheFiles::LibFuse => (
                config.direct_io,
                config.kernel_cache,
                config.auto_cache
            ),
            CacheFiles::Off => (true, false, false),
            CacheFiles::Partial => (false, false, false),
            CacheFiles::Full => (false, true, false),
            CacheFiles::AutoFull => (false, false, true),
            CacheFiles::PerProcess => {
                let process_name = self.get_process_name(pid);
                if config.cache_files_process_names.contains(&process_name) {
                    (false, false, false)  // Cached for listed processes
                } else {
                    (true, false, false)   // Direct I/O for others
                }
            }
        }
    }
    
    fn get_process_name(&self, pid: u32) -> String {
        // Read /proc/{pid}/comm to get process name
        std::fs::read_to_string(format!("/proc/{}/comm", pid))
            .unwrap_or_default()
            .trim()
            .to_string()
    }
}
```

## 5. Configuration Manager Updates

### Add Option Handlers
```rust
// In src/config_manager.rs
impl ConfigManager {
    // Add handlers for new options
    fn handle_cache_files(&self, value: &str) -> Result<(), ConfigError> {
        let cache_files = match value {
            "libfuse" => CacheFiles::LibFuse,
            "off" => CacheFiles::Off,
            "partial" => CacheFiles::Partial,
            "full" => CacheFiles::Full,
            "auto-full" => CacheFiles::AutoFull,
            "per-process" => CacheFiles::PerProcess,
            _ => return Err(ConfigError::InvalidValue(format!("Invalid cache.files value: {}", value))),
        };
        
        self.config.write().cache_files = cache_files;
        Ok(())
    }
}
```

## 6. FUSE Initialization

### Request Capabilities
```rust
// In FUSE mount initialization
fn init(&self, req: &Request) -> io::Result<ReplyInit> {
    let mut reply = ReplyInit::new();
    
    // Request direct I/O with mmap capability if configured
    if self.config.read().direct_io_allow_mmap {
        reply.flags(FUSE_CAP_DIRECT_IO_ALLOW_MMAP);
    }
    
    Ok(reply)
}
```

## 7. Testing

### Unit Tests
1. Test cache flag determination for all CacheFiles modes
2. Test process-specific caching logic
3. Test direct I/O read/write paths
4. Test configuration parsing and validation

### Integration Tests
1. Test file operations with direct I/O enabled/disabled
2. Test cache behavior with different cache.files settings
3. Test process-specific caching with test processes
4. Test parallel writes with direct I/O

## 8. Implementation Order

1. **Phase 1**: Add configuration structures and enums
2. **Phase 2**: Update FileHandle to store direct_io flag
3. **Phase 3**: Implement cache flag determination logic
4. **Phase 4**: Update open/create operations to set FUSE flags
5. **Phase 5**: Implement different read/write paths for direct I/O
6. **Phase 6**: Add configuration manager support
7. **Phase 7**: Add comprehensive tests

## Notes

- The Rust implementation should avoid using unsafe code where possible
- Use standard library file operations instead of libc calls
- Ensure thread safety with appropriate locking
- Consider using tokio for async I/O operations if beneficial
- Default process names for per-process caching: "rtorrent|qbittorrent-nox"