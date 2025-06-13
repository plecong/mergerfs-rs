# Configuration System

## Overview

mergerfs uses a sophisticated configuration system that supports runtime reconfiguration, type-safe option handling, and flexible policy assignment. The system is built around a singleton pattern with reader-writer lock protection for thread safety.

## Configuration Architecture

### Singleton Pattern
```cpp
class Config {
private:
    static Config _singleton;
    
public:
    class Read {
        const Config &_cfg;
    public:
        const Config* operator->() const;
    };
    
    class Write {
        Config &_cfg;
    public:
        Config* operator->();
    };
};
```

### Thread-Safe Access
Configuration access uses RAII guards that manage reader-writer locks:

```cpp
// Read-only access (multiple concurrent readers allowed)
Config::Read cfg;
auto value = cfg->some_setting;

// Write access (exclusive access)
Config::Write cfg;
cfg->some_setting = new_value;
```

## Configuration Types

### Type-Safe Wrappers
All configuration values use type-safe wrappers that handle string conversion:

```cpp
typedef ToFromWrapper<bool>                  ConfigBOOL;
typedef ToFromWrapper<uint64_t>              ConfigUINT64;
typedef ToFromWrapper<int>                   ConfigINT;
typedef ToFromWrapper<std::string>           ConfigSTR;
typedef ToFromWrapper<std::filesystem::path> ConfigPath;
```

### ToFromString Interface
All configuration types implement the ToFromString interface:

```cpp
class ToFromString {
public:
    virtual int from_string(const std::string &str) = 0;
    virtual std::string to_string() const = 0;
};

template<typename T>
class ToFromWrapper : public ToFromString {
private:
    T _value;
public:
    operator const T&() const { return _value; }
    T& operator*() { return _value; }
    const T& operator*() const { return _value; }
    // ... conversion methods
};
```

## Configuration Categories

### Core Settings
```cpp
class Config {
public:
    // Branch management
    ConfigUINT64   minfreespace;
    Branches       branches;
    ConfigUINT64   branches_mount_timeout;
    ConfigBOOL     branches_mount_timeout_fail;
    
    // Caching
    ConfigUINT64   cache_attr;
    ConfigUINT64   cache_entry;
    CacheFiles     cache_files;
    ConfigSet      cache_files_process_names;
    ConfigUINT64   cache_negative_entry;
    ConfigBOOL     cache_readdir;
    ConfigUINT64   cache_statfs;
    ConfigBOOL     cache_symlinks;
    
    // I/O behavior
    ConfigBOOL     async_read;
    ConfigBOOL     direct_io;
    ConfigBOOL     direct_io_allow_mmap;
    ConfigBOOL     writeback_cache;
    ConfigBOOL     kernel_cache;
    ConfigUINT64   readahead;
    
    // Threading
    ConfigINT      fuse_read_thread_count;
    ConfigINT      fuse_process_thread_count;
    ConfigINT      fuse_process_thread_queue_depth;
    ConfigSTR      fuse_pin_threads;
    
    // Policies
    Funcs          func;              // Function-specific policies
    Categories     category;          // Category-based policies (legacy)
    
    // Special features
    FlushOnClose   flushonclose;
    FollowSymlinks follow_symlinks;
    InodeCalc      inodecalc;
    LinkEXDEV      link_exdev;
    RenameEXDEV    rename_exdev;
    MoveOnENOSPC   moveonenospc;
    NFSOpenHack    nfsopenhack;
    Passthrough    passthrough;
    XAttr          xattr;
    StatFS         statfs;
    StatFSIgnore   statfs_ignore;
    
    // FUSE options
    ConfigBOOL     export_support;
    ConfigPageSize fuse_msg_size;
    ConfigBOOL     handle_killpriv;
    ConfigBOOL     handle_killpriv_v2;
    ConfigBOOL     kernel_permissions_check;
    ConfigBOOL     posix_acl;
    ConfigBOOL     readdirplus;
    ConfigBOOL     security_capability;
    
    // System settings
    ConfigPath     mountpoint;
    ConfigSTR      fsname;
    ConfigINT      scheduling_priority;
    ConfigGetPid   pid;
    SrcMounts      srcmounts;
    ConfigSTR      version;
};
```

## Policy Configuration

### Function-Based Policy Assignment
Each FUSE operation can have its own policy:

```cpp
struct Funcs {
    Func::Access      access;      // Search policy
    Func::Chmod       chmod;       // Action policy
    Func::Chown       chown;       // Action policy
    Func::Create      create;      // Create policy
    Func::GetAttr     getattr;     // Search policy
    Func::GetXAttr    getxattr;    // Search policy
    Func::Link        link;        // Action policy
    Func::ListXAttr   listxattr;   // Search policy
    Func::Mkdir       mkdir;       // Create policy
    Func::Mknod       mknod;       // Create policy
    Func::Open        open;        // Search policy
    Func::Readlink    readlink;    // Search policy
    Func::RemoveXAttr removexattr; // Action policy
    Func::Rename      rename;      // Action policy
    Func::Rmdir       rmdir;       // Action policy
    Func::SetXAttr    setxattr;    // Action policy
    Func::Symlink     symlink;     // Create policy
    Func::Truncate    truncate;    // Action policy
    Func::Unlink      unlink;      // Action policy
    Func::Utimens     utimens;     // Action policy
};
```

### Policy Type Hierarchy
```cpp
namespace Func {
    namespace Base {
        class Action : public ToFromString {
            Policy::Action policy;
        };
        
        class Create : public ToFromString {
            Policy::Create policy;
        };
        
        class Search : public ToFromString {
            Policy::Search policy;
        };
        
        // Default policy assignments
        class ActionDefault : public Action {
            ActionDefault() : Action(&Policies::Action::epall) {}
        };
        
        class CreateDefault : public Create {
            CreateDefault() : Create(&Policies::Create::pfrd) {}
        };
        
        class SearchDefault : public Search {
            SearchDefault() : Search(&Policies::Search::ff) {}
        };
    }
    
    // Function-specific policy classes
    class Access final : public Base::SearchDefault {};
    class Chmod final : public Base::ActionDefault {};
    class Create final : public Base::CreateDefault {};
    // ... etc
}
```

### Default Policy Assignments
- **Action policies default**: `epall` (existing path, all instances)
- **Create policies default**: `pfrd` (proportional free random distribution)
- **Search policies default**: `ff` (first found)

## Specialized Configuration Types

### Branch Configuration
```cpp
class Branches final : public ToFromString {
public:
    class Impl final : public ToFromString, public std::vector<Branch> {
        const u64 &_default_minfreespace;
    public:
        Impl(const u64 &default_minfreespace);
        int from_string(const std::string &str) final;
        std::string to_string() const final;
        fs::PathVector to_paths() const;
    };
    
    using Ptr = std::shared_ptr<Impl>;
    
private:
    Ptr _impl;
    mutable std::mutex _mutex;
public:
    Ptr operator->() const;
    Ptr load() const;
    void store(Ptr new_impl);
};
```

### Cache Configuration
```cpp
namespace CacheFiles {
    enum Enum {
        OFF,
        PARTIAL,
        FULL,
        AUTO_FULL
    };
}

class CacheFiles : public ToFromString {
    CacheFiles::Enum _enum;
public:
    operator CacheFiles::Enum() const;
    int from_string(const std::string &str) final;
    std::string to_string() const final;
};
```

### Enum-Based Configuration
Many configuration options use enums with string conversion:

```cpp
namespace InodeCalc {
    enum Enum {
        PASSTHROUGH,
        PATH_HASH,
        HYBRID
    };
}

namespace StatFS {
    enum Enum {
        BASE,
        FULL
    };
}

namespace XAttr {
    enum Enum {
        PASSTHROUGH,
        NOATTR,
        NOSYS
    };
}
```

## Configuration File Format

### Mount Options
Configuration is primarily set via mount options:

```bash
# Basic usage
mergerfs -o create=mfs,search=ff,action=all /disk1:/disk2 /merged

# Function-specific policies
mergerfs -o func.create=mfs,func.mkdir=eplfs,func.open=ff /disk1:/disk2 /merged

# Caching options
mergerfs -o cache.files=partial,cache.attr=1,cache.entry=1 /disk1:/disk2 /merged

# Threading options
mergerfs -o fuse.read-thread-count=4,fuse.process-thread-count=4 /disk1:/disk2 /merged
```

### Control File Runtime Configuration
Configuration can be modified at runtime via the special control file:

```bash
# Change create policy
echo "func.create=lfs" > /merged/.mergerfs

# Change caching
echo "cache.attr=5" > /merged/.mergerfs

# Change branch list
echo "branches=/disk1=RW:/disk2=RO:/disk3=NC" > /merged/.mergerfs

# Query current settings
cat /merged/.mergerfs
```

## Configuration Parsing

### Option Parser
```cpp
// In option_parser.cpp
static int mergerfs_opt_proc(void *data, const char *arg, int key, fuse_args *outargs);

static struct fuse_opt mergerfs_opts[] = {
    // Mount options
    {"async_read=%s", offsetof(Config, async_read), 0},
    {"cache.attr=%s", offsetof(Config, cache_attr), 0},
    {"cache.files=%s", offsetof(Config, cache_files), 0},
    // ... hundreds of options
    {NULL, 0, 0}
};
```

### Key-Value Parsing
```cpp
class Config {
public:
    int set(const std::string &key, const std::string &val);
    int set(const std::string &kv);  // "key=value" format
    int get(const std::string &key, std::string *val) const;
    bool has_key(const std::string &key) const;
    void keys(std::string &s) const;
};

private:
    Str2TFStrMap _map;  // Maps option names to ToFromString objects
```

### String-to-Object Mapping
The configuration system maintains a map from option names to configuration objects:

```cpp
// In config constructor
_map["async_read"] = &async_read;
_map["cache.attr"] = &cache_attr;
_map["cache.files"] = &cache_files;
_map["func.create"] = &func.create;
_map["branches"] = &branches;
// ... etc
```

## Runtime Reconfiguration

### Read-Only vs Modifiable Options
Some options are read-only after mount:

```cpp
namespace l {
    static bool readonly(const std::string &s) {
        // These options cannot be changed at runtime
        if(s == "async_read") return true;
        if(s == "branches-mount-timeout") return true;
        if(s == "cache.symlinks") return true;
        if(s == "cache.writeback") return true;
        if(s == "export-support") return true;
        if(s == "fsname") return true;
        if(s == "fuse_msg_size") return true;
        if(s == "mount") return true;
        if(s == "nullrw") return true;
        if(s == "pid") return true;
        if(s == "threads") return true;
        if(s == "version") return true;
        return false;
    }
}
```

### Control File Handler
```cpp
// In fuse_getattr.cpp - special handling for /.mergerfs
if(fusepath == CONTROLFILE) {
    return getattr_controlfile(st);
}

// Control file appears as a regular file for configuration
static int getattr_controlfile(struct stat *st) {
    static const uid_t uid = ::getuid();
    static const gid_t gid = ::getgid();
    static const time_t now = ::time(NULL);
    
    st->st_dev = 0;
    st->st_ino = 0;
    st->st_mode = (S_IFREG | S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH);
    st->st_nlink = 1;
    st->st_uid = uid;
    st->st_gid = gid;
    st->st_size = 0;
    st->st_blocks = 0;
    st->st_blksize = 1024;
    st->st_atime = now;
    st->st_mtime = now;
    st->st_ctime = now;
    
    return 0;
}
```

## Configuration Validation

### Type-Safe Validation
Each configuration type validates input during parsing:

```cpp
// Example: Boolean validation
int ConfigBOOL::from_string(const std::string &str) {
    if((str == "true") || (str == "1") || (str == "on") || (str == "yes")) {
        _value = true;
        return 0;
    }
    if((str == "false") || (str == "0") || (str == "off") || (str == "no")) {
        _value = false;
        return 0;
    }
    return -EINVAL;
}

// Example: Policy validation
int Func::Base::Create::from_string(const std::string &s) {
    Policy::CreateImpl *impl = Policies::Create::find(s);
    if(impl == nullptr)
        return -EINVAL;
    policy = impl;
    return 0;
}
```

### Range Validation
Numeric options validate ranges:

```cpp
// Page size validation
int ConfigPageSize::from_string(const std::string &str) {
    uint64_t pagesize = ::sysconf(_SC_PAGESIZE);
    uint64_t value;
    
    int rv = str::to(str, &value);
    if(rv < 0)
        return rv;
    
    if(value < pagesize)
        return -EINVAL;
    if((value % pagesize) != 0)
        return -EINVAL;
    
    _value = value;
    return 0;
}
```

## Configuration Dependencies

### Initialization Order
Configuration objects have dependencies that require careful initialization:

```cpp
Config::Config() 
    : minfreespace(MINFREESPACE_DEFAULT),
      branches(minfreespace),  // branches depends on minfreespace
      category(func),          // category depends on func
      // ... other dependencies
{
    _map["minfreespace"] = &minfreespace;
    _map["branches"] = &branches;
    // ... build string->object map
}
```

### Post-Initialization Setup
Some configuration requires post-initialization setup:

```cpp
void Config::finish_initializing() {
    // Set up FUSE threading
    fuse_config_set_read_thread_count(fuse_read_thread_count);
    fuse_config_set_process_thread_count(fuse_process_thread_count);
    fuse_config_set_process_thread_queue_depth(fuse_process_thread_queue_depth);
    
    // Initialize readdir implementation
    readdir.initialize();
    
    _initialized = true;
}
```

## Error Handling

### Error Collection
Configuration parsing collects all errors rather than failing on first error:

```cpp
struct Config::Err {
    int err;
    std::string str;
};

typedef std::vector<Err> ErrVec;

int Config::from_stream(std::istream &istrm, ErrVec *errs) {
    std::string line;
    while(std::getline(istrm, line)) {
        int rv = set(line);
        if(rv < 0) {
            errs->push_back({rv, line});
        }
    }
    return (errs->empty() ? 0 : -1);
}
```

### Error Reporting
Errors include context information:

```cpp
int Config::set_raw(const std::string &key, const std::string &val) {
    auto iter = _map.find(key);
    if(iter == _map.end())
        return -ENOENT;  // Unknown option
    
    int rv = iter->second->from_string(val);
    if(rv < 0)
        return -EINVAL;  // Invalid value
    
    return 0;
}
```

## Performance Considerations

### Read-Heavy Optimization
Configuration is optimized for frequent reads, infrequent writes:
- Reader-writer locks allow concurrent reads
- Most operations only need read access
- Write operations are rare (runtime reconfiguration)

### Memory Layout
Configuration uses value types rather than pointers for better cache locality:
```cpp
// Good: values stored inline
ConfigBOOL async_read;
ConfigUINT64 cache_attr;

// Bad: would require pointer indirection
ConfigBOOL* async_read;
ConfigUINT64* cache_attr;
```

### String Interning
Policy names and other frequently-used strings could benefit from interning, though the current implementation uses direct string comparison.