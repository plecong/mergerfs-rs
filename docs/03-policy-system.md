# Policy System Architecture

## Overview

The policy system is the core innovation of mergerfs, determining which filesystem branch(es) to use for different operations. It provides a pluggable, configurable architecture that supports diverse storage scenarios and performance requirements.

## Policy Categories

### 1. Create Policies
Determine where to place new files and directories.

| Policy | Description | Algorithm | Use Case |
|--------|-------------|-----------|----------|
| `ff` | First Found | Use first branch with sufficient space | Fast creation, fill in order |
| `mfs` | Most Free Space | Use branch with most available space | Balance storage usage |
| `lfs` | Least Free Space | Use branch with least available space | Fill drives sequentially |
| `eplfs` | Existing Path, Least Free Space | If path exists use it, else LFS | Keep related files together |
| `epmfs` | Existing Path, Most Free Space | If path exists use it, else MFS | Keep related files together with balancing |
| `epff` | Existing Path, First Found | If path exists use it, else FF | Keep related files together, fast |
| `rand` | Random | Randomly select from available branches | Distribute load randomly |
| `pfrd` | Proportional Free Random Distribution | Weight random by available space | Probabilistic load balancing |
| `newest` | Newest | Use branch with most recently modified content | Time-based placement |

### 2. Search Policies
Determine where to look for existing files.

| Policy | Description | Algorithm | Use Case |
|--------|-------------|-----------|----------|
| `ff` | First Found | Return first instance found | Fast access |
| `all` | All | Return all instances | Directory merging |
| `epff` | Existing Path, First Found | Prefer existing path, else FF | Path locality |
| `eppfrd` | Existing Path, Proportional Free Random | Prefer existing path, else PFRD | Balanced path locality |

### 3. Action Policies
Determine which instances to operate on for modifications.

| Policy | Description | Algorithm | Use Case |
|--------|-------------|-----------|----------|
| `all` | All | Operate on all instances | Maintain consistency |
| `epall` | Existing Path, All | All instances on existing paths | Path-aware consistency |
| `epff` | Existing Path, First Found | First instance on existing path | Fast updates |
| `epmfs` | Existing Path, Most Free Space | Instance on path with most space | Space-aware updates |
| `eplfs` | Existing Path, Least Free Space | Instance on path with least space | Fill drives uniformly |
| `eprand` | Existing Path, Random | Random instance on existing path | Distribute update load |
| `eppfrd` | Existing Path, Proportional Free Random | Weighted random on existing path | Probabilistic distribution |

## Policy Implementation Architecture

### Base Classes

#### Policy Interface
```cpp
namespace Policy {
    class ActionImpl {
    public:
        std::string name;
        virtual int operator()(const Branches::Ptr&, 
                             const char*, 
                             std::vector<Branch*>&) const = 0;
    };
    
    class CreateImpl {
    public:
        std::string name;
        virtual bool path_preserving(void) const = 0;
        virtual int operator()(const Branches::Ptr&, 
                             const char*, 
                             std::vector<Branch*>&) const = 0;
    };
    
    class SearchImpl {
    public:
        std::string name;
        virtual int operator()(const Branches::Ptr&, 
                             const char*, 
                             std::vector<Branch*>&) const = 0;
    };
}
```

#### Policy Wrappers
```cpp
namespace Policy {
    class Action {
        ActionImpl *impl;
    public:
        int operator()(const Branches::Ptr&, const char*, std::vector<Branch*>&) const;
        const std::string& name() const;
    };
    
    class Create {
        CreateImpl *impl;
    public:
        bool path_preserving() const;
        int operator()(const Branches::Ptr&, const char*, std::vector<Branch*>&) const;
    };
    
    class Search {
        SearchImpl *impl;
    public:
        int operator()(const Branches::Ptr&, const char*, std::vector<Branch*>&) const;
    };
}
```

### Policy Registration

#### Static Policy Objects
```cpp
// In policies.cpp
struct Policies {
    struct Action {
        static Policy::All::Action     all;
        static Policy::EPAll::Action   epall;
        static Policy::EPFF::Action    epff;
        static Policy::EPMFS::Action   epmfs;
        // ... more policies
    };
    
    struct Create {
        static Policy::FF::Create      ff;
        static Policy::MFS::Create     mfs;
        static Policy::LFS::Create     lfs;
        // ... more policies
    };
    
    struct Search {
        static Policy::FF::Search      ff;
        static Policy::All::Search     all;
        // ... more policies
    };
};
```

#### Policy Lookup Functions
```cpp
namespace Policies {
    struct Action {
        static Policy::ActionImpl* find(const std::string &name);
    };
    struct Create {
        static Policy::CreateImpl* find(const std::string &name);
    };
    struct Search {
        static Policy::SearchImpl* find(const std::string &name);
    };
}
```

## Policy Implementation Patterns

### 1. Simple Selection Policies

#### First Found (FF)
```cpp
namespace ff {
    static int create(const Branches::Ptr &branches, std::vector<Branch*> &paths) {
        int error = ENOENT;
        for(auto &branch : *branches) {
            if(branch.ro_or_nc())
                error_and_continue(error, EROFS);
            
            fs::info_t info;
            int rv = fs::info(branch.path, &info);
            if(rv == -1)
                error_and_continue(error, ENOENT);
            if(info.readonly)
                error_and_continue(error, EROFS);
            if(info.spaceavail < branch.minfreespace())
                error_and_continue(error, ENOSPC);
            
            paths.emplace_back(&branch);
            return 0;  // Return first valid branch
        }
        return (errno = error, -1);
    }
}
```

### 2. Space-Based Selection Policies

#### Most Free Space (MFS)
```cpp
namespace mfs {
    static int create(const Branches::Ptr &branches, std::vector<Branch*> &paths) {
        int error = ENOENT;
        u64 max_space = 0;
        Branch *best_branch = nullptr;
        
        for(auto &branch : *branches) {
            if(branch.ro_or_nc())
                error_and_continue(error, EROFS);
            
            fs::info_t info;
            int rv = fs::info(branch.path, &info);
            if(rv == -1)
                error_and_continue(error, ENOENT);
            if(info.readonly)
                error_and_continue(error, EROFS);
            if(info.spaceavail < branch.minfreespace())
                error_and_continue(error, ENOSPC);
            
            if(info.spaceavail > max_space) {
                max_space = info.spaceavail;
                best_branch = &branch;
            }
        }
        
        if(!best_branch)
            return (errno = error, -1);
        
        paths.push_back(best_branch);
        return 0;
    }
}
```

### 3. Existing Path Policies

#### Existing Path, All (EPAll)
```cpp
namespace epall {
    static int action(const Branches::Ptr &branches, 
                     const char *fusepath, 
                     std::vector<Branch*> &paths) {
        int error = ENOENT;
        
        for(auto &branch : *branches) {
            if(branch.ro())
                error_and_continue(error, EROFS);
            if(!fs::exists(branch.path, fusepath))
                error_and_continue(error, ENOENT);
            
            bool readonly;
            int rv = fs::statvfs_cache_readonly(branch.path, &readonly);
            if(rv == -1)
                error_and_continue(error, ENOENT);
            if(readonly)
                error_and_continue(error, EROFS);
            
            paths.emplace_back(&branch);
        }
        
        if(paths.empty())
            return (errno = error, -1);
        return 0;
    }
}
```

### 4. Probabilistic Policies

#### Proportional Free Random Distribution (PFRD)
```cpp
namespace pfrd {
    struct BranchInfo {
        uint64_t spaceavail;
        Branch *branch;
    };
    
    static int get_branchinfo(const Branches::Ptr &branches,
                             std::vector<BranchInfo> *branchinfo,
                             uint64_t *sum) {
        *sum = 0;
        int error = ENOENT;
        
        for(auto &branch : *branches) {
            if(branch.ro_or_nc())
                error_and_continue(error, EROFS);
            
            fs::info_t info;
            int rv = fs::info(branch.path, &info);
            if(rv == -1)
                error_and_continue(error, ENOENT);
            if(info.readonly)
                error_and_continue(error, EROFS);
            if(info.spaceavail < branch.minfreespace())
                error_and_continue(error, ENOSPC);
            
            *sum += info.spaceavail;
            branchinfo->push_back({info.spaceavail, &branch});
        }
        return error;
    }
    
    static Branch* get_branch(const std::vector<BranchInfo> &branchinfo,
                             const uint64_t sum) {
        if(sum == 0) return nullptr;
        
        uint64_t threshold = RND::rand64(sum);
        uint64_t idx = 0;
        
        for(auto &bi : branchinfo) {
            idx += bi.spaceavail;
            if(idx >= threshold)
                return bi.branch;
        }
        return nullptr;
    }
}
```

### 5. Composite Policies

#### Random Selection from All Valid
```cpp
namespace rand {
    static int create(const Branches::Ptr &branches, std::vector<Branch*> &paths) {
        // First get all valid branches
        int rv = Policies::Create::all(branches, nullptr, paths);
        if(rv == 0 && !paths.empty()) {
            // Then randomly select one
            RND::shrink_to_rand_elem(paths);
        }
        return rv;
    }
}
```

**Implementation Details:**
- Uses a two-stage approach: first finds all eligible branches, then randomly selects one
- Ensures uniform distribution across all valid branches
- The `shrink_to_rand_elem` function uses a thread-local Mersenne Twister for high-quality randomness
- Reuses the error accumulation logic from the `all` policy
- See [Random Policy C++ Implementation Details](policies/create/random-cpp-implementation.md) for comprehensive analysis

## Path Preservation

### Concept
Some policies are "path preserving" - they attempt to keep related files (same directory path) on the same branch.

### Implementation
```cpp
class CreateImpl {
public:
    virtual bool path_preserving(void) const = 0;
    // ...
};

// Example implementations:
bool FF::Create::path_preserving(void) const { return false; }
bool EPFF::Create::path_preserving(void) const { return true; }
bool EPAll::Create::path_preserving(void) const { return true; }
```

### Usage
Path preservation affects how mergerfs handles certain operations:
- Hard link creation across branches
- Directory structure maintenance
- File locality optimization

## Policy Selection Logic

### Configuration-Based Selection
```cpp
// In Config class
Category category;  // Contains policy assignments

struct Category {
    Policy::Action action;
    Policy::Create create;
    Policy::Search search;
};

// Policy assignment
category.action = &Policies::Action::all;
category.create = &Policies::Create::mfs;
category.search = &Policies::Search::ff;
```

### Function-Based Policy Mapping
```cpp
// In config.hpp
struct Functions {
    Policy::Action access;
    Policy::Action chmod;
    Policy::Create create;
    Policy::Action getattr;
    Policy::Action link;
    Policy::Create mkdir;
    Policy::Search open;
    Policy::Action removexattr;
    // ... one policy per FUSE operation
};
```

## Error Handling in Policies

### Error Priority System
```cpp
#define error_and_continue(error, errno_val) \
    do { \
        if(errno_val == EACCES) \
            error = EACCES; \
        else if((errno_val == EROFS) && (error == ENOENT)) \
            error = EROFS; \
        else if((errno_val == ENOSPC) && (error != EACCES) && (error != EROFS)) \
            error = ENOSPC; \
        continue; \
    } while(0)
```

### Error Priority Order
1. `EACCES` (Permission denied) - highest priority
2. `EROFS` (Read-only filesystem) - overrides ENOENT
3. `ENOSPC` (No space left) - overrides ENOENT
4. `ENOENT` (No such file/directory) - default/lowest priority

**Note:** The original C++ implementation actually uses a different priority order in `policy_error.hpp`:
1. `EROFS` (Read-only filesystem) - highest priority
2. `ENOSPC` (No space left) - medium priority
3. `ENOENT` (No such file/directory) - lowest priority

This simplified system ensures that more specific/actionable errors take precedence over generic "not found" errors.

### Policy Failure Handling
```cpp
int rv = policy(branches, fusepath, selected_branches);
if(rv < 0) {
    return rv;  // Propagate policy error
}

if(selected_branches.empty()) {
    return -ENOENT;  // No branches selected
}
```

## Performance Considerations

### Branch Information Caching
Some policies cache filesystem information to avoid repeated `statvfs()` calls:

```cpp
// In fs_statvfs_cache.cpp
struct CacheEntry {
    time_t timestamp;
    struct statvfs st;
    bool readonly;
};

static std::unordered_map<std::string, CacheEntry> g_cache;
static std::mutex g_cache_mutex;
static time_t g_cache_timeout = 1; // 1 second default
```

### Policy Evaluation Cost
- **Low cost**: `ff`, `all` - no filesystem queries
- **Medium cost**: `mfs`, `lfs` - one `statvfs()` per branch
- **High cost**: `pfrd` - `statvfs()` plus random number generation
- **Variable cost**: `ep*` policies - depends on existing file distribution

### Optimization Strategies
1. **Lazy evaluation**: Only evaluate policies when needed
2. **Caching**: Cache filesystem statistics for short periods
3. **Early termination**: Stop on first success for FF policies
4. **Batch operations**: Group operations to amortize policy costs

## Policy Configuration

### Mount Option Format
```bash
# Single policy for all operations
mergerfs -o create=mfs,search=ff,action=all /disk1:/disk2 /merged

# Function-specific policies
mergerfs -o func.create=mfs,func.mkdir=eplfs,func.open=ff /disk1:/disk2 /merged

# Category-based (older format)
mergerfs -o category.action=all,category.create=mfs /disk1:/disk2 /merged
```

### Runtime Reconfiguration
```bash
# Change policies at runtime via control file
echo "func.create=lfs" > /merged/.mergerfs
echo "func.action=epall" > /merged/.mergerfs
```

### Policy Validation
```cpp
bool Policies::Create::valid(const std::string &name) {
    return (find(name) != nullptr);
}

Policy::CreateImpl* Policies::Create::find(const std::string &name) {
    if(name == "ff") return &ff;
    if(name == "mfs") return &mfs;
    if(name == "lfs") return &lfs;
    // ... check all policies
    return nullptr;
}
```

## Advanced Policy Features

### Branch Mode Filtering
Policies automatically respect branch modes:
- **RO (Read-Only)**: Excluded from create/action policies
- **NC (No Create)**: Excluded from create policies only
- **RW (Read-Write)**: Available for all policies

### Minimum Free Space Enforcement
```cpp
if(info.spaceavail < branch.minfreespace()) {
    error_and_continue(error, ENOSPC);
}
```

### Filesystem Readonly Detection
```cpp
if(info.readonly) {
    error_and_continue(error, EROFS);
}
```

### Dynamic Branch Addition/Removal
Policies work with runtime branch modifications:
- New branches automatically included in policy evaluation
- Removed branches gracefully excluded
- No restart required for branch list changes