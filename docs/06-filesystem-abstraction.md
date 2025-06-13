# Filesystem Abstraction Layer

## Overview

mergerfs implements a comprehensive filesystem abstraction layer that provides cross-platform compatibility, optimized operations, and consistent error handling. The abstraction layer consists of 100+ functions in `fs_*.cpp` files that wrap system calls and provide higher-level functionality.

## Design Principles

### Platform Abstraction
Uses conditional compilation to provide platform-specific optimizations while maintaining a consistent interface:

```cpp
// Example: fs_fallocate.cpp
#ifdef __linux__
# include "fs_fallocate_linux.icpp"
#elif _XOPEN_SOURCE >= 600 || _POSIX_C_SOURCE >= 200112L
# include "fs_fallocate_posix.icpp"
#elif __APPLE__
# include "fs_fallocate_osx.icpp"
#else
# include "fs_fallocate_unsupported.icpp"
#endif
```

### Performance Optimization
Provides optimized paths for common operations with fallbacks:

```cpp
// copy_file_range fallback hierarchy:
// 1. Linux copy_file_range() syscall (zero-copy)
// 2. sendfile() (kernel-space copy)
// 3. read/write loop (userspace copy)
```

### Error Handling Consistency
All functions follow consistent error reporting patterns:
- Return `-1` on error with `errno` set
- Return `0` or positive values on success
- Preserve `errno` across cleanup operations

## Core Abstraction Categories

### 1. File Operations

#### Basic File I/O
```cpp
namespace fs {
    // File descriptor operations
    int open(const std::string &path, int flags);
    int open(const std::string &path, int flags, mode_t mode);
    int close(int fd);
    
    ssize_t read(int fd, void *buf, size_t count);
    ssize_t write(int fd, const void *buf, size_t count);
    ssize_t pread(int fd, void *buf, size_t count, off_t offset);
    ssize_t pwrite(int fd, const void *buf, size_t count, off_t offset);
    
    off_t lseek(int fd, off_t offset, int whence);
    int fsync(int fd);
    int fdatasync(int fd);
}
```

#### Advanced File Operations
```cpp
namespace fs {
    // Efficient copying
    ssize_t copy_file_range(int src_fd, off_t *src_off,
                           int dst_fd, off_t *dst_off,
                           size_t len, unsigned int flags);
    ssize_t sendfile(int out_fd, int in_fd, off_t *offset, size_t count);
    
    // Space allocation
    int fallocate(int fd, int mode, off_t offset, off_t len);
    int posix_fallocate(int fd, off_t offset, off_t len);
    
    // File cloning (CoW)
    int ficlone(int dst_fd, int src_fd);
    int clonefile(const std::string &src, const std::string &dst);
    
    // Advisory operations
    int fadvise(int fd, off_t offset, off_t len, int advice);
    int readahead(int fd, off_t offset, size_t count);
}
```

### 2. Path Operations

#### Path Manipulation
```cpp
namespace fs {
    namespace path {
        std::string dirname(const std::string &path);
        std::string basename(const std::string &path);
        std::string make(const std::string &base, const std::string &append);
        std::string normalize(const std::string &path);
        
        bool is_absolute(const std::string &path);
        bool is_relative(const std::string &path);
        
        // Split path into components
        void split(const std::string &path, std::vector<std::string> &parts);
        std::string join(const std::vector<std::string> &parts);
    }
}
```

#### Path Resolution
```cpp
namespace fs {
    // Symbolic link resolution
    std::string readlink(const std::string &path);
    std::string realpath(const std::string &path);
    
    // Path existence and type checking
    bool exists(const std::string &path);
    bool exists(const std::string &basepath, const std::string &relpath);
    bool is_directory(const std::string &path);
    bool is_regular_file(const std::string &path);
    bool is_symbolic_link(const std::string &path);
}
```

### 3. Directory Operations

#### Directory Manipulation
```cpp
namespace fs {
    int mkdir(const std::string &path, mode_t mode);
    int rmdir(const std::string &path);
    
    // Directory traversal
    int opendir(const std::string &path);
    int readdir(int fd, struct dirent **entry);
    int closedir(int fd);
    
    // High-level directory operations
    int mkdirs(const std::string &path, mode_t mode);  // mkdir -p
    int rmdirs(const std::string &path);               // rmdir -r
}
```

#### Directory Listing
```cpp
namespace fs {
    // Optimized directory reading
    int getdents64(int fd, void *buf, size_t count);
    
    // High-level directory listing
    int list_directory(const std::string &path, 
                      std::vector<std::string> &entries);
    
    // Directory merging for union filesystem
    int merge_directories(const std::vector<std::string> &paths,
                         std::set<std::string> &merged_entries);
}
```

### 4. Metadata Operations

#### File Attributes
```cpp
namespace fs {
    int stat(const std::string &path, struct stat *st);
    int lstat(const std::string &path, struct stat *st);
    int fstat(int fd, struct stat *st);
    
    // Attribute modification
    int chmod(const std::string &path, mode_t mode);
    int fchmod(int fd, mode_t mode);
    int lchmod(const std::string &path, mode_t mode);
    
    int chown(const std::string &path, uid_t uid, gid_t gid);
    int fchown(int fd, uid_t uid, gid_t gid);
    int lchown(const std::string &path, uid_t uid, gid_t gid);
    
    // Time modification
    int utimens(const std::string &path, const struct timespec times[2]);
    int futimens(int fd, const struct timespec times[2]);
    int lutimens(const std::string &path, const struct timespec times[2]);
}
```

#### Extended Attributes
```cpp
namespace fs {
    ssize_t getxattr(const std::string &path, const std::string &name,
                    void *value, size_t size);
    ssize_t lgetxattr(const std::string &path, const std::string &name,
                     void *value, size_t size);
    ssize_t fgetxattr(int fd, const std::string &name,
                     void *value, size_t size);
    
    int setxattr(const std::string &path, const std::string &name,
                const void *value, size_t size, int flags);
    int lsetxattr(const std::string &path, const std::string &name,
                 const void *value, size_t size, int flags);
    int fsetxattr(int fd, const std::string &name,
                 const void *value, size_t size, int flags);
    
    ssize_t listxattr(const std::string &path, char *list, size_t size);
    ssize_t llistxattr(const std::string &path, char *list, size_t size);
    ssize_t flistxattr(int fd, char *list, size_t size);
    
    int removexattr(const std::string &path, const std::string &name);
    int lremovexattr(const std::string &path, const std::string &name);
    int fremovexattr(int fd, const std::string &name);
}
```

### 5. Filesystem Information

#### Space and Statistics
```cpp
namespace fs {
    struct info_t {
        uint64_t spacetotal;
        uint64_t spacefree;
        uint64_t spaceavail;
        uint64_t spaceused;
        bool readonly;
    };
    
    int info(const std::string &path, info_t *info);
    int statvfs(const std::string &path, struct statvfs *st);
    
    // Cached filesystem statistics
    int statvfs_cache_readonly(const std::string &path, bool *readonly);
    void statvfs_cache_timeout(time_t timeout);
}
```

#### Mount Point Detection
```cpp
namespace fs {
    struct mount_t {
        std::string device;
        std::string mountpoint;
        std::string fstype;
        std::string options;
    };
    
    int mounts(std::vector<mount_t> &mounts);
    bool is_mount_point(const std::string &path);
    std::string find_mount_point(const std::string &path);
    
    // Wait for mount points to become available
    int wait_for_mount(const std::string &mountpoint,
                      const std::vector<std::string> &paths,
                      std::chrono::milliseconds timeout);
}
```

## Platform-Specific Implementations

### Conditional Compilation Pattern
Most filesystem operations use `.icpp` (implementation C++) files for platform-specific code:

```cpp
// fs_copy_file_range.cpp
#ifdef __linux__
#include "fs_copy_file_range_linux.icpp"
#else
#include "fs_copy_file_range_unsupported.icpp"
#endif
```

### Linux-Specific Optimizations

#### copy_file_range Implementation
```cpp
// fs_copy_file_range_linux.icpp
namespace fs {
    int64_t copy_file_range(int src_fd, int64_t *src_off,
                           int dst_fd, int64_t *dst_off,
                           uint64_t len, unsigned int flags) {
#ifdef SYS_copy_file_range
        return ::syscall(SYS_copy_file_range, src_fd, src_off, 
                        dst_fd, dst_off, len, flags);
#else
        return (errno = EOPNOTSUPP, -1);
#endif
    }
}
```

#### fallocate Implementation
```cpp
// fs_fallocate_linux.icpp
namespace fs {
    int fallocate(int fd, int mode, off_t offset, off_t len) {
#ifdef FALLOC_FL_KEEP_SIZE
        return ::fallocate(fd, mode, offset, len);
#else
        return ::posix_fallocate(fd, offset, len);
#endif
    }
}
```

### macOS-Specific Optimizations

#### File Cloning
```cpp
// fs_clonefile_osx.icpp
namespace fs {
    int clonefile(const std::string &src, const std::string &dst) {
        // Use macOS clonefile() for CoW file duplication
        return ::clonefile(src.c_str(), dst.c_str(), 0);
    }
}
```

#### fallocate Emulation
```cpp
// fs_fallocate_osx.icpp  
namespace fs {
    int fallocate(int fd, int mode, off_t offset, off_t len) {
        fstore_t store = {F_ALLOCATECONTIG, F_PEOFPOSMODE, 0, len, 0};
        int rv = ::fcntl(fd, F_PREALLOCATE, &store);
        if(rv == -1) {
            store.fst_flags = F_ALLOCATEALL;
            rv = ::fcntl(fd, F_PREALLOCATE, &store);
        }
        return rv;
    }
}
```

### POSIX Fallbacks

#### Generic Implementations
```cpp
// fs_fallocate_posix.icpp
namespace fs {
    int fallocate(int fd, int mode, off_t offset, off_t len) {
        return ::posix_fallocate(fd, offset, len);
    }
}

// fs_copy_file_range_unsupported.icpp  
namespace fs {
    int64_t copy_file_range(int src_fd, int64_t *src_off,
                           int dst_fd, int64_t *dst_off,
                           uint64_t len, unsigned int flags) {
        // Fall back to read/write loop
        return fs::copydata_readwrite(src_fd, dst_fd, len);
    }
}
```

## Advanced Features

### Copy-on-Write (CoW) Support

#### CoW Detection and Implementation
```cpp
namespace fs {
    namespace cow {
        // Check if file is eligible for CoW
        bool is_eligible(const struct stat &st) {
            return (S_ISREG(st.st_mode) && st.st_nlink > 1);
        }
        
        bool is_eligible(int flags) {
            int accmode = (flags & O_ACCMODE);
            return (accmode == O_RDWR || accmode == O_WRONLY);
        }
        
        // Perform CoW operation
        int break_link(const std::string &path) {
            // Create temporary file
            // Copy content
            // Atomically replace original
        }
    }
}
```

### Efficient File Copying

#### Multi-Strategy Copying
```cpp
namespace fs {
    namespace copydata {
        // Strategy 1: copy_file_range (Linux, zero-copy)
        ssize_t copy_file_range(int src_fd, int dst_fd, size_t len);
        
        // Strategy 2: sendfile (kernel-space copy)
        ssize_t sendfile(int src_fd, int dst_fd, size_t len);
        
        // Strategy 3: read/write loop (userspace copy)
        ssize_t readwrite(int src_fd, int dst_fd, size_t len);
        
        // Adaptive strategy selection
        ssize_t copy(int src_fd, int dst_fd, size_t len) {
            // Try strategies in order of efficiency
            ssize_t rv = copy_file_range(src_fd, dst_fd, len);
            if(rv >= 0) return rv;
            
            rv = sendfile(src_fd, dst_fd, len);
            if(rv >= 0) return rv;
            
            return readwrite(src_fd, dst_fd, len);
        }
    }
}
```

### Path and Filename Utilities

#### Safe Path Operations
```cpp
namespace fs {
    namespace path {
        // Build path safely without double slashes
        std::string make(const std::string &base, const std::string &append) {
            if(base.empty()) return append;
            if(append.empty()) return base;
            
            bool base_slash = (base.back() == '/');
            bool append_slash = (append.front() == '/');
            
            if(base_slash && append_slash) {
                return base + append.substr(1);
            } else if(!base_slash && !append_slash) {
                return base + '/' + append;
            } else {
                return base + append;
            }
        }
        
        // Normalize path (remove .., ., double slashes)
        std::string normalize(const std::string &path) {
            std::vector<std::string> parts;
            split(path, '/', parts);
            
            std::vector<std::string> normalized;
            for(const auto &part : parts) {
                if(part == "." || part.empty()) {
                    continue;
                } else if(part == "..") {
                    if(!normalized.empty()) {
                        normalized.pop_back();
                    }
                } else {
                    normalized.push_back(part);
                }
            }
            
            return '/' + join(normalized, '/');
        }
    }
}
```

### Inode Calculation

#### Custom Inode Generation
```cpp
namespace fs {
    namespace inode {
        // Calculate inode based on path hash
        ino_t path_hash(const std::string &fusepath) {
            return XXH64(fusepath.c_str(), fusepath.size(), 0);
        }
        
        // Hybrid approach: combine path hash with device inode
        ino_t hybrid(const std::string &fusepath, const struct stat &st) {
            return st.st_ino + path_hash(fusepath);
        }
        
        // Passthrough original inode
        ino_t passthrough(const struct stat &st) {
            return st.st_ino;
        }
    }
}
```

## Error Handling Patterns

### Consistent Error Reporting
```cpp
namespace fs {
    // All functions follow this pattern:
    int operation(/* parameters */) {
        int rv = ::system_call(/* args */);
        if(rv == -1) {
            // errno is already set by system call
            return -1;
        }
        return rv;  // or 0 for success
    }
}
```

### Error Preservation During Cleanup
```cpp
namespace l {
    static int cleanup_on_error(int src_fd = -1, 
                               int dst_fd = -1,
                               const std::string &temp_path = {}) {
        int saved_errno = errno;  // Preserve original error
        
        if(src_fd >= 0) fs::close(src_fd);
        if(dst_fd >= 0) fs::close(dst_fd);
        if(!temp_path.empty()) fs::unlink(temp_path);
        
        errno = saved_errno;  // Restore original error
        return -1;
    }
}
```

## Performance Optimizations

### Memory-Mapped Operations
```cpp
namespace fs {
    // Memory-mapped file access for large files
    class MMapFile {
        void *addr;
        size_t length;
        int fd;
        
    public:
        MMapFile(const std::string &path, int flags);
        ~MMapFile();
        
        void* data() const { return addr; }
        size_t size() const { return length; }
        
        int sync(int flags = MS_SYNC);
        int advise(int advice);
    };
}
```

### Bulk Operations
```cpp
namespace fs {
    // Bulk directory operations
    int find_all_files(const std::string &basepath,
                      std::vector<std::string> &files) {
        // Optimized recursive directory traversal
        // Uses getdents64 for performance
    }
    
    // Bulk attribute retrieval
    int stat_all(const std::vector<std::string> &paths,
                std::vector<struct stat> &stats) {
        // Parallel stat operations where supported
    }
}
```

### Caching Infrastructure
```cpp
namespace fs {
    // Generic cache template for filesystem metadata
    template<typename Key, typename Value>
    class FSCache {
        mutable std::mutex mutex;
        std::unordered_map<Key, CacheEntry<Value>> cache;
        std::chrono::seconds timeout;
        
    public:
        bool get(const Key &key, Value &value);
        void set(const Key &key, const Value &value);
        void invalidate(const Key &key);
        void clear();
        void set_timeout(std::chrono::seconds t);
    };
    
    // Specialized caches
    extern FSCache<std::string, struct statvfs> statvfs_cache;
    extern FSCache<std::string, bool> readonly_cache;
}
```