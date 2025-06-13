# Thread Safety and Concurrency Patterns

## Overview

mergerfs implements sophisticated concurrency control to ensure thread safety while maximizing performance. The system uses a combination of reader-writer locks, per-object mutexes, lock-free data structures, and careful synchronization patterns.

## Threading Model

### FUSE Threading Architecture
FUSE provides configurable threading for different operation types:

```cpp
// Thread pool configuration
ConfigINT fuse_read_thread_count;           // Threads for read operations
ConfigINT fuse_process_thread_count;        // Threads for other operations  
ConfigINT fuse_process_thread_queue_depth;  // Queue depth per thread
ConfigSTR fuse_pin_threads;                 // CPU affinity settings
```

### Thread Categories
1. **Read threads**: Handle `read`, `readdir`, `getattr` operations
2. **Process threads**: Handle `write`, `create`, `unlink`, metadata operations
3. **Main thread**: Handles FUSE lifecycle and special operations

## Synchronization Primitives

### Reader-Writer Locks
The primary synchronization mechanism for shared data:

```cpp
namespace rwlock {
    class ReadGuard {
        pthread_rwlock_t &_lock;
    public:
        ReadGuard(pthread_rwlock_t &lock) : _lock(lock) {
            pthread_rwlock_rdlock(&_lock);
        }
        ~ReadGuard() {
            pthread_rwlock_unlock(&_lock);
        }
    };
    
    class WriteGuard {
        pthread_rwlock_t &_lock;
    public:
        WriteGuard(pthread_rwlock_t &lock) : _lock(lock) {
            pthread_rwlock_wrlock(&_lock);
        }
        ~WriteGuard() {
            pthread_rwlock_unlock(&_lock);
        }
    };
}
```

### Per-Object Mutexes
Fine-grained locking for individual resources:

```cpp
class FileInfo : public FH {
public:
    int fd;
    Branch branch;
    u32 direct_io:1;
    std::mutex mutex;  // Per-file synchronization
};
```

## Configuration Thread Safety

### RAII Configuration Guards
Configuration access uses RAII guards that automatically acquire appropriate locks:

```cpp
class Config::Read {
private:
    const Config &_cfg;
    rwlock::ReadGuard _guard;  // Automatic read lock
    
public:
    Read() : _cfg(Config::get()), _guard(_cfg._rwlock) {}
    const Config* operator->() const { return &_cfg; }
};

class Config::Write {
private:
    Config &_cfg;
    rwlock::WriteGuard _guard;  // Automatic write lock
    
public:
    Write() : _cfg(Config::get()), _guard(_cfg._rwlock) {}
    Config* operator->() { return &_cfg; }
};
```

### Configuration Access Patterns
```cpp
// Read-only access (concurrent with other reads)
{
    Config::Read cfg;
    auto policy = cfg->func.create.policy;
    auto branches = cfg->branches.load();
    // ... use configuration
}  // Read lock automatically released

// Write access (exclusive)
{
    Config::Write cfg;
    cfg->cache_attr = new_value;
    cfg->func.create = new_policy;
    // ... modify configuration
}  // Write lock automatically released
```

## Branch Management Thread Safety

### Shared Pointer with Atomic Updates
Branch collections use shared pointers for lock-free reads with atomic updates:

```cpp
class Branches final : public ToFromString {
public:
    using Ptr = std::shared_ptr<Impl>;
    
private:
    mutable std::mutex _mutex;
    Ptr _impl;
    
public:
    Ptr load() const {
        std::lock_guard<std::mutex> lg(_mutex);
        return _impl;
    }
    
    void store(Ptr new_impl) {
        std::lock_guard<std::mutex> lg(_mutex);
        _impl = std::swap(new_impl);
    }
    
    Ptr operator->() const {
        return load();  // Thread-safe copy of shared_ptr
    }
};
```

### Branch Access Pattern
```cpp
// Safe branch access - creates local copy of shared_ptr
auto branches = cfg->branches.load();
for(auto &branch : *branches) {
    // Use branch safely - no locks held during iteration
}
```

## File Handle Thread Safety

### Per-File Synchronization
Each open file has its own mutex to allow concurrent access to different files:

```cpp
class FileInfo : public FH {
public:
    std::mutex mutex;
    
    // File operations must lock this mutex
    int read(char *buf, size_t size, off_t offset) {
        std::lock_guard<std::mutex> lg(mutex);
        return ::pread(fd, buf, size, offset);
    }
    
    int write(const char *buf, size_t size, off_t offset) {
        std::lock_guard<std::mutex> lg(mutex);
        return ::pwrite(fd, buf, size, offset);
    }
};
```

### FUSE File Handle Management
```cpp
// File handle creation (exclusive)
int FUSE::create(const char *fusepath, mode_t mode, fuse_file_info_t *ffi) {
    // ... policy selection and file creation
    
    FileInfo *fi = new FileInfo(fd, branch, fusepath, direct_io);
    ffi->fh = reinterpret_cast<uint64_t>(fi);
    
    return 0;
}

// File operations (per-file locking)
int FUSE::read(fuse_file_info_t *ffi, char *buf, size_t size, off_t offset) {
    FileInfo *fi = reinterpret_cast<FileInfo*>(ffi->fh);
    std::lock_guard<std::mutex> lg(fi->mutex);
    return ::pread(fi->fd, buf, size, offset);
}
```

## Memory Pool Thread Safety

### Locked Memory Pools
Memory pools use mutexes to synchronize allocation/deallocation:

```cpp
template<uint64_t SIZE>
class LockedFixedMemPool {
private:
    std::mutex _mutex;
    FixedMemPool<SIZE> _pool;
    
public:
    void* alloc() {
        std::lock_guard<std::mutex> lg(_mutex);
        return _pool.alloc();
    }
    
    void free(void *mem) {
        std::lock_guard<std::mutex> lg(_mutex);
        _pool.free(mem);
    }
};

// Global memory pool for directory buffers
extern LockedFixedMemPool<128 * 1024> g_DENTS_BUF_POOL;
```

### Memory Pool Usage Pattern
```cpp
// Directory reading with memory pool
int FUSE::readdir(fuse_file_info_t *ffi, fuse_dirents_t *buf) {
    auto buffer = g_DENTS_BUF_POOL.alloc();
    
    // Use buffer for directory operations
    
    g_DENTS_BUF_POOL.free(buffer);
    return 0;
}
```

## Caching Thread Safety

### Filesystem Statistics Cache
The statvfs cache uses mutexes to protect cached data:

```cpp
namespace fs {
    struct statvfs_cache_entry {
        time_t timestamp;
        struct statvfs st;
        bool readonly;
    };
    
    static std::unordered_map<std::string, statvfs_cache_entry> g_cache;
    static std::mutex g_cache_mutex;
    static time_t g_cache_timeout = 1;
    
    int statvfs_cache_readonly(const std::string &path, bool *readonly) {
        std::lock_guard<std::mutex> lg(g_cache_mutex);
        
        auto now = ::time(nullptr);
        auto iter = g_cache.find(path);
        
        if((iter != g_cache.end()) && 
           ((now - iter->second.timestamp) < g_cache_timeout)) {
            *readonly = iter->second.readonly;
            return 0;
        }
        
        // Cache miss - update cache
        struct statvfs st;
        int rv = ::statvfs(path.c_str(), &st);
        if(rv == 0) {
            bool ro = (st.f_flag & ST_RDONLY);
            g_cache[path] = {now, st, ro};
            *readonly = ro;
        }
        
        return rv;
    }
}
```

### Directory Entry Caching
Directory entry caching requires careful invalidation:

```cpp
class DirCache {
private:
    mutable std::mutex _mutex;
    std::unordered_map<std::string, CacheEntry> _cache;
    
public:
    bool get(const std::string &path, std::vector<dirent> &entries) {
        std::lock_guard<std::mutex> lg(_mutex);
        auto iter = _cache.find(path);
        if(iter != _cache.end() && !iter->second.expired()) {
            entries = iter->second.entries;
            return true;
        }
        return false;
    }
    
    void invalidate(const std::string &path) {
        std::lock_guard<std::mutex> lg(_mutex);
        _cache.erase(path);
        
        // Invalidate parent directories that might contain this entry
        std::string parent = fs::path::dirname(path);
        while(!parent.empty() && parent != "/") {
            _cache.erase(parent);
            parent = fs::path::dirname(parent);
        }
    }
};
```

## User/Group ID Context

### Thread-Local UID/GID Management
User/group context uses thread-local storage or reader-writer locks:

```cpp
#if UGID_USE_RWLOCK
class ugid::Set {
private:
    static pthread_rwlock_t _rwlock;
    rwlock::WriteGuard _guard;
    
public:
    Set(const ugid::SetImpl &ugid) : _guard(_rwlock) {
        if(ugid.uid != ::geteuid()) ::seteuid(ugid.uid);
        if(ugid.gid != ::getegid()) ::setegid(ugid.gid);
    }
    
    ~Set() {
        // Restore original uid/gid
    }
};
#else
class ugid::Set {
    // Thread-local implementation
    thread_local static uid_t saved_uid;
    thread_local static gid_t saved_gid;
};
#endif
```

### Usage Pattern
```cpp
int FUSE::operation(const char *fusepath, /* params */) {
    Config::Read cfg;
    const ugid::Set ugid(cfg->ugid);  // Set user context for this thread
    
    // Perform filesystem operations with correct permissions
    
    // ugid destructor restores original context
}
```

## Lock Ordering and Deadlock Prevention

### Lock Hierarchy
To prevent deadlocks, locks must be acquired in consistent order:

1. **Global locks** (configuration, caches)
2. **Branch-level locks** (branch collection)
3. **File-level locks** (per-file mutexes)
4. **Memory pool locks** (allocation/deallocation)

### Lock-Free Patterns Where Possible
```cpp
// Branch access uses shared_ptr for lock-free reads
auto branches = cfg->branches.load();  // Atomic shared_ptr copy
// No locks held during iteration
for(auto &branch : *branches) {
    // Safe to access branch data
}
```

## Performance Optimizations

### Read-Heavy Workload Optimization
Configuration and branch access optimized for read-heavy workloads:
- Reader-writer locks allow concurrent reads
- Shared pointers enable lock-free access to immutable data
- Short critical sections minimize contention

### Lock Contention Reduction
```cpp
// Bad: Long critical section
{
    Config::Read cfg;
    for(auto &branch : *cfg->branches) {
        expensive_operation(branch);  // Lock held during expensive work
    }
}

// Good: Short critical section
auto branches = cfg->branches.load();  // Quick copy of shared_ptr
for(auto &branch : *branches) {
    expensive_operation(branch);  // No locks held
}
```

### Memory Barrier Considerations
Shared pointer operations provide necessary memory barriers:
```cpp
// Publisher thread
auto new_branches = std::make_shared<Branches::Impl>();
// ... populate new_branches
cfg->branches.store(new_branches);  // Memory barrier ensures visibility

// Consumer thread
auto branches = cfg->branches.load();  // Memory barrier ensures consistency
```

## Race Condition Prevention

### Configuration Updates
Configuration updates use write locks to prevent races:

```cpp
// Runtime configuration change
int Config::set(const std::string &key, const std::string &val) {
    Config::Write cfg;  // Exclusive access
    
    auto iter = _map.find(key);
    if(iter == _map.end())
        return -ENOENT;
    
    return iter->second->from_string(val);  // Safe to modify
}
```

### File Handle Lifecycle
File handle lifecycle managed through FUSE reference counting:

```cpp
// FUSE guarantees:
// - create() called before any other operations
// - release() called after all operations complete
// - No operations after release()
// - Multiple operations can be concurrent on same file

int FUSE::release(fuse_file_info_t *ffi) {
    FileInfo *fi = reinterpret_cast<FileInfo*>(ffi->fh);
    delete fi;  // Safe - no more operations will occur
    return 0;
}
```

### Directory Consistency
Directory operations ensure consistency across branches:

```cpp
int FUSE::mkdir(const char *fusepath, mode_t mode) {
    Config::Read cfg;
    std::vector<Branch*> branches;
    
    // Policy selects target branch
    int rv = cfg->func.mkdir.policy(cfg->branches, fusepath, branches);
    if(rv < 0) return rv;
    
    // Create directory on selected branch
    for(auto &branch : branches) {
        std::string fullpath = fs::path::make(branch->path, fusepath);
        rv = fs::mkdir(fullpath, mode);
        if(rv < 0) {
            // Cleanup on failure
            cleanup_partial_mkdir(branches, fusepath);
            return rv;
        }
    }
    
    return 0;
}
```

## Testing Concurrency

### Thread Safety Testing
mergerfs includes tests for concurrent operations:

```cpp
// Stress test: concurrent reads/writes to same file
void test_concurrent_file_access() {
    const int num_threads = 10;
    const int operations_per_thread = 1000;
    
    std::vector<std::thread> threads;
    for(int i = 0; i < num_threads; ++i) {
        threads.emplace_back([=]() {
            for(int j = 0; j < operations_per_thread; ++j) {
                // Mix of read/write operations
                test_file_operation();
            }
        });
    }
    
    for(auto &t : threads) {
        t.join();
    }
    
    // Verify file integrity
}
```

### Configuration Concurrency Testing
```cpp
// Test: concurrent configuration reads with occasional writes
void test_config_concurrency() {
    std::atomic<bool> stop{false};
    
    // Reader threads
    std::vector<std::thread> readers;
    for(int i = 0; i < 8; ++i) {
        readers.emplace_back([&]() {
            while(!stop) {
                Config::Read cfg;
                auto policy = cfg->func.create.policy;
                // Use configuration
            }
        });
    }
    
    // Writer thread
    std::thread writer([&]() {
        while(!stop) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            Config::Write cfg;
            cfg->cache_attr = new_value;
        }
    });
    
    std::this_thread::sleep_for(std::chrono::seconds(10));
    stop = true;
    
    for(auto &r : readers) r.join();
    writer.join();
}
```