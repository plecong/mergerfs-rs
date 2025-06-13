# Data Structures and Memory Management

## Overview

mergerfs employs sophisticated data structures and memory management patterns to achieve high performance while maintaining thread safety. The system uses custom memory pools, smart pointers, lock-free data structures, and careful object lifecycle management.

## Core Data Structures

### Branch Representation

#### Individual Branch
```cpp
class Branch final : public ToFromString {
public:
    enum class Mode {
        INVALID,
        RO,    // Read-only
        RW,    // Read-write  
        NC     // No create (read-write but no new files)
    };
    
    std::variant<u64, const u64*> _minfreespace;  // Value or reference
    Mode mode;
    std::string path;
    
public:
    bool ro() const;
    bool nc() const; 
    bool ro_or_nc() const;
    u64 minfreespace() const;
    void set_minfreespace(const u64);
};
```

#### Branch Collection
```cpp
class Branches final : public ToFromString {
public:
    class Impl final : public ToFromString, public std::vector<Branch> {
        const u64 &_default_minfreespace;
    public:
        fs::PathVector to_paths() const;
        // Thread-safe iteration support
    };
    
    using Ptr = std::shared_ptr<Impl>;
    
private:
    mutable std::mutex _mutex;
    Ptr _impl;
    
public:
    Ptr load() const;           // Thread-safe copy
    void store(Ptr new_impl);   // Atomic update
    Ptr operator->() const;     // Convenience access
};
```

### File Handle Management

#### File Information Structure
```cpp
class FileInfo : public FH {
public:
    int fd;                    // File descriptor
    Branch branch;             // Source branch
    u32 direct_io:1;          // Direct I/O flag
    std::mutex mutex;          // Per-file synchronization
    
    FileInfo(int fd, const Branch &branch, const char *fusepath, bool direct_io);
    FileInfo(int fd, const Branch *branch, const char *fusepath, bool direct_io);
    FileInfo(const FileInfo *fi);  // Copy constructor
};

class FH {  // Base file handle
protected:
    std::string fusepath;
public:
    FH(const std::string &fusepath_);
    virtual ~FH() = default;
};
```

#### Directory Information Structure
```cpp
class DirInfo : public FH {
public:
    std::vector<Branch*> branches;     // Branches containing directory
    std::set<std::string> seen;        // Deduplicated entries
    mutable std::mutex mutex;          // Directory-level synchronization
    
    DirInfo(const std::string &fusepath_);
    void add_entry(const std::string &name);
    bool has_entry(const std::string &name) const;
};
```

### Configuration Data Structures

#### Type-Safe Configuration Wrappers
```cpp
template<typename T>
class ToFromWrapper : public ToFromString {
private:
    T _value;
    
public:
    ToFromWrapper() = default;
    ToFromWrapper(const T &value) : _value(value) {}
    
    operator const T&() const { return _value; }
    T& operator*() { return _value; }
    const T& operator*() const { return _value; }
    
    ToFromWrapper& operator=(const T &value) {
        _value = value;
        return *this;
    }
    
    int from_string(const std::string &str) final;
    std::string to_string() const final;
};

// Type aliases for common configuration types
typedef ToFromWrapper<bool>                  ConfigBOOL;
typedef ToFromWrapper<uint64_t>              ConfigUINT64;
typedef ToFromWrapper<int>                   ConfigINT;
typedef ToFromWrapper<std::string>           ConfigSTR;
typedef ToFromWrapper<std::filesystem::path> ConfigPath;
```

#### Configuration Object Mapping
```cpp
class Config {
private:
    typedef std::map<std::string, ToFromString*> Str2TFStrMap;
    Str2TFStrMap _map;  // Maps option names to configuration objects
    
public:
    Config() {
        // Build string-to-object mapping
        _map["async_read"] = &async_read;
        _map["cache.attr"] = &cache_attr;
        _map["func.create"] = &func.create;
        // ... hundreds of mappings
    }
    
    int set(const std::string &key, const std::string &val);
    int get(const std::string &key, std::string *val) const;
    bool has_key(const std::string &key) const;
};
```

## Memory Pool System

### Fixed-Size Memory Pools
```cpp
template<uint64_t SIZE>
class FixedMemPool {
private:
    struct fixed_mem_pool_t {
        fixed_mem_pool_t *next;
    };
    
    fixed_mem_pool_t list;  // Free list head
    
public:
    FixedMemPool() { list.next = nullptr; }
    
    ~FixedMemPool() {
        void *mem;
        while(!empty()) {
            mem = alloc();
            ::free(mem);
        }
    }
    
    bool empty() const { return (list.next == nullptr); }
    uint64_t size() const { return SIZE; }
    
    void* alloc() {
        if(list.next == nullptr)
            return ::malloc(SIZE);  // Allocate new if pool empty
        
        void *rv = static_cast<void*>(list.next);
        list.next = list.next->next;
        return rv;
    }
    
    void free(void *mem) {
        if(mem == nullptr) return;
        
        auto *node = static_cast<fixed_mem_pool_t*>(mem);
        node->next = list.next;
        list.next = node;
    }
};
```

### Thread-Safe Memory Pools
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
    
    bool empty() const {
        std::lock_guard<std::mutex> lg(_mutex);
        return _pool.empty();
    }
    
    uint64_t size() const { return SIZE; }
};
```

### Memory Pool Usage
```cpp
// Global memory pools for common buffer sizes
extern LockedFixedMemPool<128 * 1024> g_DENTS_BUF_POOL;  // Directory buffers
extern LockedFixedMemPool<64 * 1024>  g_IO_BUF_POOL;     // I/O buffers
extern LockedFixedMemPool<4096>       g_PAGE_BUF_POOL;   // Page-sized buffers

// Usage pattern
int FUSE::readdir(fuse_file_info_t *ffi, fuse_dirents_t *buf) {
    auto buffer = g_DENTS_BUF_POOL.alloc();
    
    try {
        // Use buffer for directory operations
        int rv = read_directory_entries(buffer, g_DENTS_BUF_POOL.size());
        
        g_DENTS_BUF_POOL.free(buffer);
        return rv;
    } catch(...) {
        g_DENTS_BUF_POOL.free(buffer);
        throw;
    }
}
```

## Smart Pointer Patterns

### Shared Pointer for Immutable Data
```cpp
// Branch collections use shared_ptr for lock-free reads
class Branches {
    using Ptr = std::shared_ptr<Impl>;
    
    Ptr load() const {
        std::lock_guard<std::mutex> lg(_mutex);
        return _impl;  // Atomic shared_ptr copy
    }
    
    void store(Ptr new_impl) {
        std::lock_guard<std::mutex> lg(_mutex);
        _impl = std::move(new_impl);  // Atomic update
    }
};

// Usage: Lock-free iteration
auto branches = cfg->branches.load();  // Quick shared_ptr copy
for(const auto &branch : *branches) {
    // Safe iteration without locks
}
```

### RAII for Resource Management
```cpp
// Configuration access guards
class Config::Read {
private:
    const Config &_cfg;
    rwlock::ReadGuard _guard;  // RAII lock management
    
public:
    Read() : _cfg(Config::get()), _guard(_cfg._rwlock) {}
    const Config* operator->() const { return &_cfg; }
    // Destructor automatically releases lock
};

// File descriptor management
class ScopedFD {
    int _fd;
public:
    ScopedFD(int fd) : _fd(fd) {}
    ~ScopedFD() { if(_fd >= 0) ::close(_fd); }
    
    int get() const { return _fd; }
    int release() { int fd = _fd; _fd = -1; return fd; }
};
```

## String Management

### String Utilities and Optimization
```cpp
namespace str {
    // Efficient string splitting without copying
    void split(const std::string &str, char delim, std::vector<std::string> *result);
    void split(const std::string &str, const std::string &delim, std::vector<std::string> *result);
    
    // String joining
    template<typename Container>
    std::string join(const Container &container, char delim);
    template<typename Container>
    std::string join(const Container &container, const std::string &delim);
    
    // Numeric conversions
    template<typename T>
    int to(const std::string &str, T *value);
    template<typename T>
    std::string from(const T &value);
    
    // String comparison utilities
    bool startswith(const std::string &str, const std::string &prefix);
    bool endswith(const std::string &str, const std::string &suffix);
    bool contains(const std::string &str, const std::string &substr);
}
```

### String Vector for Paths
```cpp
class StrVec : public std::vector<std::string> {
public:
    std::string to_string() const;
    int from_string(const std::string &str);
    
    // Path-specific operations
    void to_absolute_paths();
    void remove_duplicates();
    void sort_by_usage();  // Sort by filesystem usage statistics
};

// Path vector specialization
namespace fs {
    class PathVector : public std::vector<std::string> {
    public:
        void expand_globs();           // Expand wildcards
        void resolve_symlinks();      // Resolve symbolic links
        void filter_existing();       // Remove non-existent paths
        void canonicalize();          // Convert to canonical form
    };
}
```

## Hash Tables and Indexing

### Policy Lookup Tables
```cpp
// Policy registration using static initialization
struct Policies {
    struct Create {
        static std::unordered_map<std::string, Policy::CreateImpl*> registry;
        
        static Policy::CreateImpl* find(const std::string &name) {
            auto iter = registry.find(name);
            return (iter != registry.end()) ? iter->second : nullptr;
        }
        
        // Static initialization ensures thread-safe registration
        static bool register_policy(const std::string &name, Policy::CreateImpl *impl) {
            registry[name] = impl;
            return true;
        }
    };
};

// Automatic registration
static bool ff_registered = Policies::Create::register_policy("ff", &Policies::Create::ff);
```

### Filesystem Metadata Caching
```cpp
// Generic cache template
template<typename Key, typename Value>
class FSCache {
private:
    struct CacheEntry {
        Value value;
        std::chrono::steady_clock::time_point timestamp;
        
        bool expired(std::chrono::seconds timeout) const {
            auto now = std::chrono::steady_clock::now();
            return (now - timestamp) > timeout;
        }
    };
    
    mutable std::mutex _mutex;
    std::unordered_map<Key, CacheEntry> _cache;
    std::chrono::seconds _timeout;
    
public:
    bool get(const Key &key, Value &value) {
        std::lock_guard<std::mutex> lg(_mutex);
        auto iter = _cache.find(key);
        if(iter != _cache.end() && !iter->second.expired(_timeout)) {
            value = iter->second.value;
            return true;
        }
        return false;
    }
    
    void set(const Key &key, const Value &value) {
        std::lock_guard<std::mutex> lg(_mutex);
        _cache[key] = {value, std::chrono::steady_clock::now()};
    }
    
    void invalidate(const Key &key) {
        std::lock_guard<std::mutex> lg(_mutex);
        _cache.erase(key);
    }
    
    void clear() {
        std::lock_guard<std::mutex> lg(_mutex);
        _cache.clear();
    }
    
    void set_timeout(std::chrono::seconds timeout) {
        std::lock_guard<std::mutex> lg(_mutex);
        _timeout = timeout;
    }
};
```

## Object Lifecycle Management

### FUSE Object Lifecycle
```cpp
// File handle lifecycle managed by FUSE
class FileInfo : public FH {
public:
    static FileInfo* create(int fd, const Branch &branch, 
                           const char *fusepath, bool direct_io) {
        return new FileInfo(fd, branch, fusepath, direct_io);
    }
    
    static void destroy(FileInfo *fi) {
        delete fi;  // Safe due to FUSE guarantees
    }
    
private:
    // Private destructor - only destroy() can delete
    ~FileInfo() {
        if(fd >= 0) ::close(fd);
    }
};

// FUSE operation pattern
int FUSE::create(const char *fusepath, mode_t mode, fuse_file_info_t *ffi) {
    // ... create file and get fd
    FileInfo *fi = FileInfo::create(fd, branch, fusepath, direct_io);
    ffi->fh = reinterpret_cast<uint64_t>(fi);
    return 0;
}

int FUSE::release(fuse_file_info_t *ffi) {
    FileInfo *fi = reinterpret_cast<FileInfo*>(ffi->fh);
    FileInfo::destroy(fi);  // Safe - no more operations will occur
    return 0;
}
```

### Configuration Object Lifecycle
```cpp
// Configuration objects have static storage duration
class Config {
private:
    static Config _singleton;  // Static storage, never destroyed
    
public:
    static Config& get() { return _singleton; }
    
    // No destructor needed - static storage
};

// Configuration components managed by main config object
Config::Config() 
    : branches(minfreespace),  // Dependency injection
      category(func),          // Reference to other components
      _initialized(false)
{
    // All members have automatic storage within config object
}
```

## Memory Layout Optimizations

### Structure Packing
```cpp
// Bit fields for flags to reduce memory usage
class FileInfo : public FH {
public:
    int fd;                // 4 bytes
    Branch branch;         // ~32 bytes (string + enums)
    u32 direct_io:1;      // 1 bit
    // Implicit padding to alignment boundary
    std::mutex mutex;      // Platform-dependent size
};

// Explicit packing for protocol structures
#pragma pack(push, 1)
struct fuse_dirent {
    uint64_t ino;
    uint64_t off;
    uint32_t namelen;
    uint32_t type;
    char name[];  // Flexible array member
};
#pragma pack(pop)
```

### Cache-Friendly Data Layout
```cpp
// Policy objects designed for cache efficiency
class Policy::ActionImpl {
public:
    std::string name;  // Accessed frequently, stored inline
    
    // Virtual function - indirect call but better than function pointers
    virtual int operator()(const Branches::Ptr&, const char*, 
                          std::vector<Branch*>&) const = 0;
};

// Configuration values stored by value for cache locality
class Config {
    // Good: values stored inline
    ConfigBOOL async_read;
    ConfigUINT64 cache_attr;
    ConfigBOOL direct_io;
    
    // Avoid: pointers would cause cache misses
    // ConfigBOOL* async_read;
};
```

## Debugging and Profiling Support

### Memory Usage Tracking
```cpp
#ifdef DEBUG_MEMORY
class MemoryTracker {
private:
    static std::atomic<size_t> total_allocated;
    static std::atomic<size_t> peak_allocated;
    static std::mutex allocation_mutex;
    static std::unordered_map<void*, size_t> allocations;
    
public:
    static void* track_malloc(size_t size) {
        void *ptr = ::malloc(size);
        if(ptr) {
            std::lock_guard<std::mutex> lg(allocation_mutex);
            allocations[ptr] = size;
            total_allocated += size;
            peak_allocated = std::max(peak_allocated.load(), total_allocated.load());
        }
        return ptr;
    }
    
    static void track_free(void *ptr) {
        if(!ptr) return;
        
        std::lock_guard<std::mutex> lg(allocation_mutex);
        auto iter = allocations.find(ptr);
        if(iter != allocations.end()) {
            total_allocated -= iter->second;
            allocations.erase(iter);
        }
        ::free(ptr);
    }
    
    static void print_stats() {
        std::lock_guard<std::mutex> lg(allocation_mutex);
        printf("Current allocated: %zu bytes\n", total_allocated.load());
        printf("Peak allocated: %zu bytes\n", peak_allocated.load());
        printf("Outstanding allocations: %zu\n", allocations.size());
    }
};
#endif
```

### Pool Statistics
```cpp
template<uint64_t SIZE>
class LockedFixedMemPool {
private:
    std::atomic<size_t> _alloc_count{0};
    std::atomic<size_t> _free_count{0};
    std::atomic<size_t> _malloc_count{0};  // Fallback to malloc
    
public:
    void* alloc() {
        std::lock_guard<std::mutex> lg(_mutex);
        ++_alloc_count;
        
        if(_pool.empty()) {
            ++_malloc_count;
            return ::malloc(SIZE);
        }
        
        return _pool.alloc();
    }
    
    void free(void *mem) {
        std::lock_guard<std::mutex> lg(_mutex);
        ++_free_count;
        _pool.free(mem);
    }
    
    // Statistics
    size_t alloc_count() const { return _alloc_count; }
    size_t free_count() const { return _free_count; }
    size_t malloc_count() const { return _malloc_count; }
    double hit_rate() const {
        size_t total = _alloc_count;
        return total ? (double)(total - _malloc_count) / total : 0.0;
    }
};
```