# Error Handling and Edge Cases

## Overview

mergerfs implements comprehensive error handling to deal with the complexities of union filesystems, including branch failures, partial operations, policy conflicts, and edge cases in distributed file operations. The system prioritizes consistency and data integrity while providing graceful degradation.

## Error Classification System

### Error Priority Hierarchy
mergerfs uses a sophisticated error priority system to determine which error to report when multiple branches fail:

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

#### Priority Order (highest to lowest):
1. **EACCES** (Permission denied) - Always takes precedence
2. **EROFS** (Read-only filesystem) - Overrides ENOENT
3. **ENOSPC** (No space left) - Overrides ENOENT
4. **ENOENT** (No such file/directory) - Default/lowest priority
5. **Other errors** - Context-dependent handling

### Error Context Preservation
```cpp
namespace l {
    static int cleanup_on_error(const int src_fd = -1,
                               const int dst_fd = -1,
                               const std::string &dst_fullpath = {}) {
        int saved_errno = errno;  // Preserve original error
        
        // Cleanup operations that might modify errno
        if(src_fd >= 0) fs::close(src_fd);
        if(dst_fd >= 0) fs::close(dst_fd);
        if(!dst_fullpath.empty()) fs::unlink(dst_fullpath);
        
        errno = saved_errno;  // Restore original error
        return -1;
    }
}
```

## Branch Failure Handling

### Branch Availability Detection
```cpp
namespace fs {
    bool is_branch_available(const std::string &path) {
        struct statvfs st;
        int rv = ::statvfs(path.c_str(), &st);
        if(rv == -1) return false;
        
        // Check if filesystem is accessible
        return !(st.f_flag & ST_RDONLY) || (access == O_RDONLY);
    }
    
    void mark_branch_failed(const std::string &path, time_t duration) {
        // Temporarily mark branch as unavailable
        // Used for network filesystems that may be temporarily inaccessible
    }
}
```

### Graceful Degradation
```cpp
int FUSE::operation(const char *fusepath, /* params */) {
    Config::Read cfg;
    std::vector<Branch*> branches;
    
    int rv = cfg->func.policy(cfg->branches, fusepath, branches);
    if(rv < 0) return rv;
    
    int error = ENOENT;
    bool any_success = false;
    
    for(auto &branch : branches) {
        if(!fs::is_branch_available(branch->path)) {
            error_and_continue(error, ENOENT);
        }
        
        std::string fullpath = fs::path::make(branch->path, fusepath);
        rv = fs::operation(fullpath, /* params */);
        
        if(rv >= 0) {
            any_success = true;
            if(policy_allows_partial_success()) {
                return rv;  // Early success return
            }
        } else {
            error_and_continue(error, errno);
            if(policy_requires_all_success()) {
                return rv;  // Early failure return
            }
        }
    }
    
    return any_success ? 0 : (errno = error, -1);
}
```

## Partial Operation Recovery

### Copy-on-Write Failure Recovery
```cpp
namespace fs {
    namespace cow {
        int break_link_safe(const std::string &path) {
            struct stat st;
            int rv = fs::lstat(path, &st);
            if(rv == -1) return -1;
            
            if(!is_eligible(st)) return 0;  // Not a hard link
            
            // Create temporary file for atomic replacement
            std::string temp_path = fs::mktemp(path + ".XXXXXX");
            if(temp_path.empty()) return -1;
            
            int src_fd = -1, dst_fd = -1;
            
            try {
                src_fd = fs::open(path, O_RDONLY);
                if(src_fd == -1) throw std::runtime_error("open source");
                
                dst_fd = fs::open(temp_path, O_WRONLY | O_CREAT | O_TRUNC, st.st_mode);
                if(dst_fd == -1) throw std::runtime_error("open dest");
                
                // Copy file content
                rv = fs::copydata(src_fd, dst_fd, st.st_size);
                if(rv == -1) throw std::runtime_error("copy data");
                
                // Copy metadata
                rv = copy_metadata(src_fd, dst_fd, st);
                if(rv == -1) throw std::runtime_error("copy metadata");
                
                fs::close(src_fd); src_fd = -1;
                fs::close(dst_fd); dst_fd = -1;
                
                // Atomic replacement
                rv = fs::rename(temp_path, path);
                if(rv == -1) throw std::runtime_error("atomic replace");
                
                return 0;
                
            } catch(...) {
                return cleanup_on_error(src_fd, dst_fd, temp_path);
            }
        }
    }
}
```

### Directory Operation Consistency
```cpp
int FUSE::mkdir(const char *fusepath, mode_t mode) {
    Config::Read cfg;
    std::vector<Branch*> branches;
    
    int rv = cfg->func.mkdir.policy(cfg->branches, fusepath, branches);
    if(rv < 0) return rv;
    
    std::vector<std::string> created_paths;
    int error = ENOENT;
    
    for(auto &branch : branches) {
        std::string fullpath = fs::path::make(branch->path, fusepath);
        rv = fs::mkdir(fullpath, mode);
        
        if(rv >= 0) {
            created_paths.push_back(fullpath);
        } else {
            error_and_continue(error, errno);
            
            // Cleanup on failure
            for(const auto &created : created_paths) {
                fs::rmdir(created);  // Best effort cleanup
            }
            return (errno = error, -1);
        }
    }
    
    return 0;
}
```

## Concurrency Error Handling

### Race Condition Detection
```cpp
int FUSE::rename(const char *from, const char *to) {
    Config::Read cfg;
    const ugid::Set ugid(cfg->ugid);
    
    // Check for cross-branch rename
    std::vector<Branch*> src_branches, dst_branches;
    
    int rv = cfg->func.action(cfg->branches, from, src_branches);
    if(rv < 0) return rv;
    
    rv = cfg->func.create(cfg->branches, to, dst_branches);
    if(rv < 0) return rv;
    
    // Handle race condition: file might be deleted between operations
    for(auto &src_branch : src_branches) {
        std::string src_fullpath = fs::path::make(src_branch->path, from);
        
        struct stat st;
        rv = fs::lstat(src_fullpath, &st);
        if(rv == -1) {
            if(errno == ENOENT) continue;  // File deleted, try next branch
            return -1;
        }
        
        // Find or create destination
        Branch *dst_branch = find_destination_branch(src_branch, dst_branches);
        if(!dst_branch) return (errno = EXDEV, -1);
        
        std::string dst_fullpath = fs::path::make(dst_branch->path, to);
        
        if(src_branch == dst_branch) {
            // Same branch - simple rename
            rv = fs::rename(src_fullpath, dst_fullpath);
        } else {
            // Cross-branch - move operation
            rv = move_file_cross_branch(src_fullpath, dst_fullpath);
        }
        
        if(rv >= 0) return rv;
        if(errno != ENOENT) return rv;  // Real error
        // ENOENT - file deleted during operation, try next
    }
    
    return (errno = ENOENT, -1);
}
```

### Deadlock Prevention
```cpp
class OrderedLock {
private:
    static std::mutex global_order_mutex;
    static std::unordered_map<void*, int> lock_order;
    static int next_order;
    
    std::vector<std::pair<std::mutex*, int>> locks;
    
public:
    void add_lock(std::mutex *m) {
        std::lock_guard<std::mutex> lg(global_order_mutex);
        
        auto iter = lock_order.find(m);
        if(iter == lock_order.end()) {
            lock_order[m] = next_order++;
        }
        locks.emplace_back(m, lock_order[m]);
    }
    
    void lock_all() {
        // Sort by order to prevent deadlocks
        std::sort(locks.begin(), locks.end(), 
                 [](const auto &a, const auto &b) {
                     return a.second < b.second;
                 });
        
        for(auto &pair : locks) {
            pair.first->lock();
        }
    }
    
    void unlock_all() {
        // Unlock in reverse order
        for(auto iter = locks.rbegin(); iter != locks.rend(); ++iter) {
            iter->first->unlock();
        }
    }
};
```

## I/O Error Recovery

### Partial Read/Write Handling
```cpp
namespace fs {
    ssize_t read_all(int fd, void *buf, size_t count) {
        char *ptr = static_cast<char*>(buf);
        size_t remaining = count;
        ssize_t total = 0;
        
        while(remaining > 0) {
            ssize_t rv = ::read(fd, ptr, remaining);
            if(rv == -1) {
                if(errno == EINTR) continue;  // Interrupted, retry
                return -1;
            }
            if(rv == 0) break;  // EOF
            
            ptr += rv;
            remaining -= rv;
            total += rv;
        }
        
        return total;
    }
    
    ssize_t write_all(int fd, const void *buf, size_t count) {
        const char *ptr = static_cast<const char*>(buf);
        size_t remaining = count;
        ssize_t total = 0;
        
        while(remaining > 0) {
            ssize_t rv = ::write(fd, ptr, remaining);
            if(rv == -1) {
                if(errno == EINTR) continue;  // Interrupted, retry
                if(errno == EAGAIN || errno == EWOULDBLOCK) {
                    // Non-blocking I/O would block, wait and retry
                    usleep(1000);  // 1ms delay
                    continue;
                }
                return -1;
            }
            if(rv == 0) return total;  // No progress
            
            ptr += rv;
            remaining -= rv;
            total += rv;
        }
        
        return total;
    }
}
```

### Network Filesystem Error Recovery
```cpp
namespace fs {
    int robust_operation(const std::string &path, 
                        std::function<int()> operation,
                        int max_retries = 3) {
        int retries = 0;
        
        while(retries < max_retries) {
            int rv = operation();
            if(rv >= 0) return rv;
            
            switch(errno) {
                case EIO:          // I/O error
                case ETIMEDOUT:    // Network timeout
                case ECONNRESET:   // Connection reset
                case EHOSTUNREACH: // Host unreachable
                    // Temporary network issues - retry with backoff
                    ++retries;
                    usleep(1000 * (1 << retries));  // Exponential backoff
                    continue;
                    
                case EACCES:       // Permission denied
                case ENOENT:       // File not found
                case EEXIST:       // File exists
                    // Permanent errors - don't retry
                    return rv;
                    
                default:
                    // Unknown error - try once more
                    if(retries == 0) {
                        ++retries;
                        continue;
                    }
                    return rv;
            }
        }
        
        return -1;  // All retries exhausted
    }
}
```

## Policy Conflict Resolution

### Inconsistent Branch States
```cpp
namespace policy {
    int resolve_conflicts(const std::vector<Branch*> &branches,
                         const char *fusepath,
                         ConflictResolution strategy) {
        
        struct BranchState {
            Branch *branch;
            bool exists;
            struct stat st;
            int error;
        };
        
        std::vector<BranchState> states;
        
        // Gather state from all branches
        for(auto *branch : branches) {
            BranchState state;
            state.branch = branch;
            
            std::string fullpath = fs::path::make(branch->path, fusepath);
            int rv = fs::lstat(fullpath, &state.st);
            
            state.exists = (rv == 0);
            state.error = state.exists ? 0 : errno;
            states.push_back(state);
        }
        
        switch(strategy) {
            case ConflictResolution::MOST_RECENT:
                return resolve_by_mtime(states);
                
            case ConflictResolution::LARGEST_SIZE:
                return resolve_by_size(states);
                
            case ConflictResolution::FIRST_FOUND:
                return resolve_by_order(states);
                
            case ConflictResolution::MAJORITY_VOTE:
                return resolve_by_majority(states);
                
            default:
                return -EINVAL;
        }
    }
}
```

### Policy Fallback Chain
```cpp
int apply_policy_with_fallback(const Branches::Ptr &branches,
                              const char *fusepath,
                              Policy::Action primary_policy,
                              std::vector<Branch*> &result) {
    
    // Try primary policy
    int rv = primary_policy(branches, fusepath, result);
    if(rv >= 0 && !result.empty()) {
        return rv;
    }
    
    // Primary policy failed, try fallbacks
    static const std::vector<Policy::Action> fallbacks = {
        &Policies::Action::epall,  // Existing path, all
        &Policies::Action::all,    // All branches
        &Policies::Action::ff      // First found
    };
    
    for(auto &fallback : fallbacks) {
        if(fallback == primary_policy) continue;  // Skip if same as primary
        
        result.clear();
        rv = fallback(branches, fusepath, result);
        if(rv >= 0 && !result.empty()) {
            return rv;
        }
    }
    
    return (errno = ENOENT, -1);
}
```

## File System Edge Cases

### Hard Link Consistency
```cpp
namespace fs {
    int safe_link(const std::string &from, const std::string &to) {
        // Check if source and destination are on same filesystem
        struct stat from_st, to_parent_st;
        
        int rv = fs::stat(from, &from_st);
        if(rv == -1) return rv;
        
        std::string to_parent = fs::path::dirname(to);
        rv = fs::stat(to_parent, &to_parent_st);
        if(rv == -1) return rv;
        
        if(from_st.st_dev != to_parent_st.st_dev) {
            // Cross-device link - use copy-on-write
            return fs::cow::copy_file(from, to);
        }
        
        // Same device - regular hard link
        rv = ::link(from.c_str(), to.c_str());
        if(rv == -1 && errno == EMLINK) {
            // Too many links - fall back to CoW
            return fs::cow::copy_file(from, to);
        }
        
        return rv;
    }
}
```

### Symlink Loop Detection
```cpp
namespace fs {
    std::string resolve_symlinks(const std::string &path, int max_depth = 40) {
        std::string current = path;
        std::set<std::string> seen;
        
        for(int i = 0; i < max_depth; ++i) {
            // Check for loops
            if(seen.count(current)) {
                errno = ELOOP;
                return {};
            }
            seen.insert(current);
            
            struct stat st;
            int rv = fs::lstat(current, &st);
            if(rv == -1) return {};
            
            if(!S_ISLNK(st.st_mode)) {
                return current;  // Not a symlink
            }
            
            std::string target = fs::readlink(current);
            if(target.empty()) return {};
            
            if(fs::path::is_absolute(target)) {
                current = target;
            } else {
                current = fs::path::make(fs::path::dirname(current), target);
            }
        }
        
        errno = ELOOP;  // Too many symlink levels
        return {};
    }
}
```

### Directory Consistency Checks
```cpp
namespace fs {
    bool verify_directory_consistency(const std::vector<std::string> &branch_paths,
                                     const std::string &relpath) {
        std::set<std::string> all_entries;
        std::map<std::string, std::vector<struct stat>> entry_stats;
        
        // Collect entries from all branches
        for(const auto &branch : branch_paths) {
            std::string fullpath = fs::path::make(branch, relpath);
            
            std::vector<std::string> entries;
            int rv = fs::list_directory(fullpath, entries);
            if(rv == -1) continue;  // Branch doesn't have directory
            
            for(const auto &entry : entries) {
                all_entries.insert(entry);
                
                std::string entry_path = fs::path::make(fullpath, entry);
                struct stat st;
                if(fs::lstat(entry_path, &st) == 0) {
                    entry_stats[entry].push_back(st);
                }
            }
        }
        
        // Check for conflicts
        for(const auto &entry : all_entries) {
            const auto &stats = entry_stats[entry];
            if(stats.size() <= 1) continue;  // No conflict
            
            // Check if all instances have same type
            mode_t first_type = stats[0].st_mode & S_IFMT;
            for(size_t i = 1; i < stats.size(); ++i) {
                mode_t type = stats[i].st_mode & S_IFMT;
                if(type != first_type) {
                    // Type conflict - file vs directory vs symlink
                    return false;
                }
            }
        }
        
        return true;
    }
}
```

## Error Reporting and Debugging

### Comprehensive Error Context
```cpp
struct ErrorContext {
    std::string operation;
    std::string fusepath;
    std::vector<std::string> branch_paths;
    std::vector<int> branch_errors;
    std::string additional_info;
    
    std::string to_string() const {
        std::ostringstream oss;
        oss << "Operation: " << operation << "\n";
        oss << "Path: " << fusepath << "\n";
        oss << "Branches attempted:\n";
        
        for(size_t i = 0; i < branch_paths.size(); ++i) {
            oss << "  " << branch_paths[i];
            if(i < branch_errors.size()) {
                oss << " (error: " << strerror(branch_errors[i]) << ")";
            }
            oss << "\n";
        }
        
        if(!additional_info.empty()) {
            oss << "Additional info: " << additional_info << "\n";
        }
        
        return oss.str();
    }
};

void log_error(const ErrorContext &ctx, int final_errno) {
    if(cfg->log_level >= LOG_ERROR) {
        syslog(LOG_ERR, "mergerfs error: %s (final errno: %s)", 
               ctx.to_string().c_str(), strerror(final_errno));
    }
}
```

### Debug Trace Support
```cpp
#ifdef DEBUG_TRACE
class OperationTracer {
private:
    std::string operation;
    std::string path;
    std::chrono::steady_clock::time_point start_time;
    
public:
    OperationTracer(const std::string &op, const std::string &p) 
        : operation(op), path(p), start_time(std::chrono::steady_clock::now()) {
        
        printf("TRACE: BEGIN %s(%s)\n", operation.c_str(), path.c_str());
    }
    
    ~OperationTracer() {
        auto end_time = std::chrono::steady_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::microseconds>(
            end_time - start_time);
        
        printf("TRACE: END %s(%s) [%ld μs]\n", 
               operation.c_str(), path.c_str(), duration.count());
    }
    
    void log_branch_attempt(const std::string &branch, int result) {
        printf("TRACE:   %s -> branch %s: %s\n",
               operation.c_str(), branch.c_str(),
               (result >= 0) ? "SUCCESS" : strerror(errno));
    }
};

#define TRACE_OPERATION(op, path) OperationTracer _tracer(op, path)
#define TRACE_BRANCH(branch, result) _tracer.log_branch_attempt(branch, result)
#else
#define TRACE_OPERATION(op, path) do {} while(0)
#define TRACE_BRANCH(branch, result) do {} while(0)
#endif
```

### Metrics Collection
```cpp
class OperationMetrics {
private:
    std::atomic<uint64_t> success_count{0};
    std::atomic<uint64_t> error_count{0};
    std::atomic<uint64_t> total_duration_us{0};
    std::map<int, std::atomic<uint64_t>> error_histogram;
    
public:
    void record_success(uint64_t duration_us) {
        ++success_count;
        total_duration_us += duration_us;
    }
    
    void record_error(int errno_val, uint64_t duration_us) {
        ++error_count;
        total_duration_us += duration_us;
        ++error_histogram[errno_val];
    }
    
    void print_stats() const {
        uint64_t total = success_count + error_count;
        if(total == 0) return;
        
        printf("Operation statistics:\n");
        printf("  Total operations: %lu\n", total);
        printf("  Success rate: %.2f%%\n", 
               100.0 * success_count / total);
        printf("  Average duration: %.2f μs\n",
               (double)total_duration_us / total);
        
        printf("  Error breakdown:\n");
        for(const auto &pair : error_histogram) {
            printf("    %s: %lu\n", 
                   strerror(pair.first), pair.second.load());
        }
    }
};
```