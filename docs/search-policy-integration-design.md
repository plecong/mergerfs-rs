# Search Policy Integration Design

## Overview

This document outlines the design for integrating search policies into FUSE operations in mergerfs-rs. Search policies determine which branch(es) to use when looking for existing files.

## Current State

Currently, our FUSE operations use a simple "first found" approach hardcoded into the logic. We have implemented three search policies but they are not yet integrated:
- `ff` (FirstFound) - Returns first branch where file exists
- `all` - Returns all branches where file exists  
- `newest` - Returns branch with newest modification time

## Operations That Need Search Policies

Based on the C++ implementation analysis, these operations should use search policies:

### Core Operations
1. **lookup** - Find inode for a path
2. **getattr** - Get file attributes
3. **open** - Open existing file
4. **access** - Check file access permissions

### Extended Attribute Operations
5. **getxattr** - Get extended attributes
6. **listxattr** - List extended attributes

### Symbolic Link Operations
7. **readlink** - Read symbolic link target

## Design Approach

### 1. Add Search Policy to FileManager

```rust
pub struct FileManager {
    pub branches: Vec<Arc<Branch>>,
    pub create_policy: Arc<dyn CreatePolicy>,
    pub search_policy: Arc<dyn SearchPolicy>, // NEW
    // ...
}
```

### 2. Create Search Method in FileManager

```rust
impl FileManager {
    /// Search for a path using the configured search policy
    pub fn search_path(&self, path: &Path) -> Result<Vec<Arc<Branch>>, PolicyError> {
        self.search_policy.search_branches(&self.branches, path)
    }
    
    /// Get the first branch where path exists (common case)
    pub fn find_first_branch(&self, path: &Path) -> Result<Arc<Branch>, PolicyError> {
        let branches = self.search_path(path)?;
        branches.into_iter().next()
            .ok_or(PolicyError::NoBranchesAvailable)
    }
}
```

### 3. Update FUSE Operations

Example for `lookup`:

```rust
fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
    // ... build child_path ...
    
    // Use search policy to find the file
    match self.file_manager.find_first_branch(&child_path) {
        Ok(branch) => {
            let full_path = branch.full_path(&child_path);
            // ... rest of lookup logic ...
        }
        Err(_) => {
            reply.error(ENOENT);
            return;
        }
    }
}
```

### 4. Configuration Integration

Add search policy configuration to ConfigManager:

```rust
struct SearchPolicyOption {
    file_manager: Arc<RwLock<FileManager>>,
    current_value: RwLock<String>,
}

impl ConfigOption for SearchPolicyOption {
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        let policy: Arc<dyn SearchPolicy> = match value {
            "ff" => Arc::new(FirstFoundSearchPolicy::new()),
            "all" => Arc::new(AllSearchPolicy::new()),
            "newest" => Arc::new(NewestSearchPolicy::new()),
            _ => return Err(ConfigError::InvalidValue),
        };
        
        // Update file_manager's search policy
        self.file_manager.write().search_policy = policy;
        *self.current_value.write() = value.to_string();
        Ok(())
    }
}
```

## Implementation Steps

1. **Add search_policy field to FileManager**
   - Default to FirstFoundSearchPolicy
   - Make it configurable

2. **Add search helper methods to FileManager**
   - `search_path()` - Returns all matching branches
   - `find_first_branch()` - Returns first matching branch
   - `file_exists_in_any_branch()` - Check existence

3. **Update FUSE operations one by one**
   - Start with `lookup` as it's most critical
   - Then `getattr`, `open`, `access`
   - Finally xattr and readlink operations

4. **Add configuration support**
   - Add "func.search" configuration option
   - Wire it through ConfigManager
   - Update runtime config tests

5. **Test each operation**
   - Unit tests for search integration
   - Python integration tests
   - Verify different policies work correctly

## Benefits

1. **Flexibility**: Users can choose search behavior
2. **Performance**: "newest" policy useful for cache scenarios
3. **Debugging**: "all" policy helps understand file distribution
4. **Consistency**: All read operations use same search logic

## Testing Strategy

1. **Unit Tests**: Test FileManager search methods
2. **Integration Tests**: Test each FUSE operation with different policies
3. **Python Tests**: Verify behavior through filesystem operations
4. **Policy Comparison**: Ensure different policies produce expected results