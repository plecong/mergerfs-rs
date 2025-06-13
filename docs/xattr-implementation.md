# Extended Attributes (xattr) Implementation Design

## Overview

Extended attributes (xattrs) provide a mechanism to associate metadata with files and directories beyond the standard attributes (permissions, timestamps, etc.). In mergerfs, xattr operations must be policy-aware and handle the complexity of files potentially existing across multiple branches.

## C++ Implementation Analysis

### Core Operations

#### 1. getxattr (Get Extended Attribute)

```cpp
// Pseudocode for getxattr operation
int getxattr(fusepath, attrname, attrvalue, attrvaluesize) {
    // Handle special mergerfs attributes
    if (attrname.startsWith("user.mergerfs.")) {
        return handle_mergerfs_xattr(fusepath, attrname, attrvalue, attrvaluesize);
    }
    
    // Use search policy to find file
    vector<string> basepaths;
    searchPolicy(branches, fusepath, basepaths);
    
    if (basepaths.empty()) {
        return -ENOENT;
    }
    
    // Get xattr from first found branch
    fullpath = basepaths[0] + fusepath;
    return lgetxattr(fullpath, attrname, attrvalue, attrvaluesize);
}
```

**Special mergerfs attributes:**
- `user.mergerfs.basepath`: Returns the branch path containing the file
- `user.mergerfs.relpath`: Returns the relative path (same as fusepath)
- `user.mergerfs.fullpath`: Returns complete path to actual file
- `user.mergerfs.allpaths`: Returns null-separated list of all paths where file exists

#### 2. setxattr (Set Extended Attribute)

```cpp
// Pseudocode for setxattr operation
int setxattr(fusepath, attrname, attrvalue, attrvaluesize, flags) {
    // Block setting mergerfs special attributes
    if (attrname.startsWith("user.mergerfs.")) {
        return -EPERM;
    }
    
    // Check security.capability configuration
    if (attrname == "security.capability" && !config.security_capability) {
        return -ENOATTR;
    }
    
    // Use action policy to get target branches
    vector<string> basepaths;
    actionPolicy(branches, fusepath, basepaths);
    
    PolicyRV rv;
    for (const auto& basepath : basepaths) {
        fullpath = basepath + fusepath;
        int result = lsetxattr(fullpath, attrname, attrvalue, attrvaluesize, flags);
        
        if (result == 0) {
            rv.successes++;
        } else {
            rv.errors.push_back({result, errno});
        }
    }
    
    return process_policy_rv(rv, fusepath);
}
```

#### 3. listxattr (List Extended Attributes)

```cpp
// Pseudocode for listxattr operation
int listxattr(fusepath, list, listsize) {
    // Use search policy to find file
    vector<string> basepaths;
    searchPolicy(branches, fusepath, basepaths);
    
    if (basepaths.empty()) {
        return -ENOENT;
    }
    
    // List from first found branch
    fullpath = basepaths[0] + fusepath;
    
    // Handle size query
    if (list == NULL || listsize == 0) {
        return llistxattr(fullpath, NULL, 0);
    }
    
    // Get actual list with retry on ERANGE
    while (true) {
        ssize_t result = llistxattr(fullpath, list, listsize);
        if (result >= 0 || errno != ERANGE) {
            return result;
        }
        // Resize buffer and retry...
    }
}
```

#### 4. removexattr (Remove Extended Attribute)

```cpp
// Pseudocode for removexattr operation
int removexattr(fusepath, attrname) {
    // Block removing mergerfs special attributes
    if (attrname.startsWith("user.mergerfs.")) {
        return -EPERM;
    }
    
    // Use action policy
    vector<string> basepaths;
    actionPolicy(branches, fusepath, basepaths);
    
    PolicyRV rv;
    for (const auto& basepath : basepaths) {
        fullpath = basepath + fusepath;
        int result = lremovexattr(fullpath, attrname);
        
        if (result == 0) {
            rv.successes++;
        } else {
            rv.errors.push_back({result, errno});
        }
    }
    
    return process_policy_rv(rv, fusepath);
}
```

### Policy Return Value Processing

```cpp
int process_policy_rv(PolicyRV& rv, const string& fusepath) {
    // All succeeded
    if (rv.errors.empty()) {
        return 0;
    }
    
    // All failed - return first error
    if (rv.successes == 0) {
        errno = rv.errors[0].error;
        return rv.errors[0].rv;
    }
    
    // Mixed results - check target branch
    vector<string> basepaths;
    getxattrPolicy(branches, fusepath, basepaths);
    
    // Find if target branch had an error
    for (const auto& error : rv.errors) {
        if (error.basepath == basepaths[0]) {
            errno = error.error;
            return error.rv;
        }
    }
    
    // Target branch succeeded
    return 0;
}
```

## Rust Implementation Plan

### Key Design Decisions

1. **No unsafe code**: Use safe Rust abstractions for all xattr operations
2. **Cross-platform**: Abstract platform differences behind traits
3. **Policy integration**: Reuse existing policy infrastructure
4. **Error handling**: Implement PolicyRV equivalent for consistent error aggregation

### Module Structure

```rust
// src/xattr/mod.rs
pub mod operations;
pub mod special_attrs;
pub mod platform;

// Platform-specific implementations
#[cfg(target_os = "linux")]
pub use platform::linux::*;

#[cfg(target_os = "macos")]
pub use platform::macos::*;

#[cfg(windows)]
pub use platform::windows::*;
```

### Core Traits

```rust
pub trait XattrOperations {
    fn get_xattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, XattrError>;
    fn set_xattr(&self, path: &Path, name: &str, value: &[u8], flags: XattrFlags) -> Result<(), XattrError>;
    fn list_xattr(&self, path: &Path) -> Result<Vec<String>, XattrError>;
    fn remove_xattr(&self, path: &Path, name: &str) -> Result<(), XattrError>;
}

#[derive(Debug, Error)]
pub enum XattrError {
    #[error("Attribute not found")]
    NotFound,
    #[error("Permission denied")]
    PermissionDenied,
    #[error("Attribute name too long")]
    NameTooLong,
    #[error("Value too large")]
    ValueTooLarge,
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}
```

### Special Attributes Handler

```rust
pub struct MergerfsXattrHandler {
    file_manager: Arc<FileManager>,
}

impl MergerfsXattrHandler {
    pub fn handle_special_attr(&self, path: &Path, name: &str) -> Option<Result<Vec<u8>, XattrError>> {
        match name {
            "user.mergerfs.basepath" => Some(self.get_basepath(path)),
            "user.mergerfs.relpath" => Some(Ok(path.to_string_lossy().into_bytes())),
            "user.mergerfs.fullpath" => Some(self.get_fullpath(path)),
            "user.mergerfs.allpaths" => Some(self.get_allpaths(path)),
            _ => None,
        }
    }
}
```

### Platform Abstraction

For Linux (using the `xattr` crate):
```rust
// src/xattr/platform/linux.rs
use xattr;

pub struct LinuxXattr;

impl XattrOperations for LinuxXattr {
    fn get_xattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, XattrError> {
        xattr::get(path, name)
            .map_err(|e| match e.raw_os_error() {
                Some(libc::ENOATTR) => XattrError::NotFound,
                Some(libc::EPERM) => XattrError::PermissionDenied,
                _ => XattrError::Io(e),
            })
    }
    // ... other operations
}
```

### FUSE Integration

```rust
impl Filesystem for MergerFS {
    fn getxattr(&mut self, _req: &Request, ino: u64, name: &OsStr, size: u32, reply: ReplyXattr) {
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        // Handle special mergerfs attributes
        if let Some(result) = self.xattr_handler.handle_special_attr(path, name_str) {
            match result {
                Ok(data) => {
                    if size == 0 {
                        reply.size(data.len() as u32);
                    } else if (data.len() as u32) <= size {
                        reply.data(&data);
                    } else {
                        reply.error(ERANGE);
                    }
                }
                Err(_) => reply.error(ENOATTR),
            }
            return;
        }
        
        // Regular xattr handling with policy
        // ...
    }
}
```

## Testing Strategy

### Unit Tests
1. Test each platform implementation
2. Test special attribute handling
3. Test policy integration
4. Test error aggregation

### Integration Tests
1. Test xattr operations through FUSE mount
2. Test across multiple branches
3. Test special mergerfs attributes
4. Test size queries and buffer management
5. Test namespace filtering (security.capability)

### Property-Based Tests
1. Random attribute names and values
2. Concurrent xattr operations
3. Large attribute values
4. Mixed success/failure scenarios