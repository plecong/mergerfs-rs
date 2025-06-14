# Rename Operation Design for mergerfs-rs

## Overview

The rename operation in a union filesystem is complex because it must handle renaming files that may exist on multiple branches while maintaining consistency and respecting configured policies.

## Requirements

1. **Atomic-like behavior**: Either all renames succeed or none do
2. **Policy compliance**: Respect action, search, and create policies
3. **Cross-branch support**: Handle files existing on multiple branches
4. **Directory support**: Rename directories with all contents
5. **Overwrite support**: Handle destination files that already exist
6. **Error handling**: Graceful handling of partial failures

## Design

### Core Components

```rust
pub trait RenameOperation {
    fn rename(
        &self,
        old_path: &Path,
        new_path: &Path,
        config: &Config,
    ) -> Result<(), RenameError>;
}

pub struct RenameManager {
    branches: Vec<Arc<Branch>>,
    action_policy: Box<dyn ActionPolicy>,
    search_policy: Box<dyn SearchPolicy>,
    create_policy: Box<dyn CreatePolicy>,
}
```

### Rename Strategies

#### 1. Path-Preserving Rename
- Keep files on their current branches only
- Don't create new paths on additional branches
- Used when create policy is path-preserving

#### 2. Create-Path Rename (Default)
- Can create parent directories on new branches
- Uses search policy to determine target branches
- More flexible, allows spreading across branches

### Implementation Flow

```rust
impl RenameManager {
    pub fn rename(&self, old_path: &Path, new_path: &Path) -> Result<()> {
        // 1. Find source files using action policy
        let source_branches = self.action_policy.select_branches(
            &self.branches,
            old_path,
            ActionContext::Rename
        )?;
        
        // 2. Determine target branches
        let target_branches = if self.should_preserve_path() {
            // Keep on same branches
            source_branches.clone()
        } else {
            // Use search policy for destination
            self.search_policy.find_branches(
                &self.branches,
                new_path.parent()?,
                SearchContext::Rename
            )?
        };
        
        // 3. Perform renames
        let mut to_remove = Vec::new();
        let mut errors = Vec::new();
        
        for branch in &target_branches {
            match self.rename_on_branch(branch, old_path, new_path) {
                Ok(()) => {
                    // Track source files to remove from other branches
                    for src_branch in &source_branches {
                        if src_branch.path != branch.path {
                            to_remove.push((src_branch, old_path));
                        }
                    }
                }
                Err(e) => errors.push(e),
            }
        }
        
        // 4. Handle errors
        if errors.is_empty() {
            // Success - clean up orphaned files
            for (branch, path) in to_remove {
                let _ = fs::remove_file(branch.path.join(path));
            }
            Ok(())
        } else {
            // Failure - return most significant error
            Err(self.prioritize_error(errors))
        }
    }
    
    fn rename_on_branch(
        &self,
        branch: &Branch,
        old_path: &Path,
        new_path: &Path
    ) -> Result<()> {
        // Check branch is writable
        if branch.is_readonly() {
            return Err(RenameError::ReadOnly);
        }
        
        let old_full = branch.path.join(old_path);
        let new_full = branch.path.join(new_path);
        
        // Create parent directory if needed
        if let Some(parent) = new_full.parent() {
            if !parent.exists() {
                fs::create_dir_all(parent)?;
            }
        }
        
        // Perform rename
        fs::rename(&old_full, &new_full)?;
        
        Ok(())
    }
}
```

### Edge Cases

#### 1. Overwriting Existing Files
```rust
// Before rename, check if destination exists
if new_full.exists() {
    // Policy decision: overwrite or error
    match self.config.rename_overwrite {
        OverwritePolicy::Allow => {
            // Continue with rename (will overwrite)
        }
        OverwritePolicy::Error => {
            return Err(RenameError::DestinationExists);
        }
    }
}
```

#### 2. Directory Renames
```rust
// Check if source is directory
let metadata = old_full.metadata()?;
if metadata.is_dir() {
    // Directory rename - same logic applies
    // All contents move automatically with parent
}
```

#### 3. Cross-Device (EXDEV) Handling
```rust
match fs::rename(&old_full, &new_full) {
    Err(e) if e.raw_os_error() == Some(libc::EXDEV) => {
        // Handle based on configuration
        match self.config.rename_exdev {
            ExdevPolicy::Passthrough => Err(RenameError::CrossDevice),
            ExdevPolicy::RelSymlink => self.create_relative_symlink(old_full, new_full),
            ExdevPolicy::AbsSymlink => self.create_absolute_symlink(old_full, new_full),
        }
    }
    other => other,
}
```

### Error Priorities

```rust
impl RenameError {
    fn priority(&self) -> u32 {
        match self {
            RenameError::NotFound => 1,
            RenameError::PermissionDenied => 2,
            RenameError::ReadOnly => 3,
            RenameError::NoSpace => 4,
            RenameError::CrossDevice => 5,
            RenameError::Io(_) => 6,
        }
    }
}
```

### FUSE Integration

```rust
impl Filesystem for MergerFS {
    fn rename(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        newparent: u64,
        newname: &OsStr,
        flags: u32,
        reply: ReplyEmpty,
    ) {
        let old_path = self.resolve_path(parent, name);
        let new_path = self.resolve_path(newparent, newname);
        
        match self.rename_manager.rename(&old_path, &new_path) {
            Ok(()) => reply.ok(),
            Err(e) => reply.error(e.to_errno()),
        }
    }
}
```

## Testing Strategy

### Unit Tests
1. Single branch rename
2. Multi-branch rename
3. Directory rename
4. Overwrite scenarios
5. Read-only branch handling
6. Error cases

### Integration Tests
1. Cross-directory renames
2. Large directory trees
3. Concurrent rename operations
4. Policy interaction tests
5. EXDEV handling

### Property Tests
- Rename preserves file contents
- Rename maintains permissions
- Rename respects policies
- No data loss on failures

## Implementation Plan

1. **Phase 1**: Basic rename support
   - Single file rename on single branch
   - Basic error handling
   
2. **Phase 2**: Multi-branch support
   - Action policy integration
   - Source file cleanup
   
3. **Phase 3**: Advanced features
   - Directory rename
   - Create-path mode
   - EXDEV handling
   
4. **Phase 4**: Polish
   - Performance optimization
   - Comprehensive error handling
   - Configuration options