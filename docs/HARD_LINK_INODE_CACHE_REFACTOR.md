# Hard Link Support: Inode Cache Refactor Design

## Executive Summary

The mergerfs-rs project already has a complete inode calculation implementation that matches the C++ version. However, hard links still don't work correctly because the FUSE layer's path-to-inode cache assumes a 1:1 mapping between paths and inodes. This document outlines the minimal refactor needed to support hard links properly.

## Current State Analysis

### What's Already Working

1. **Inode Calculation**: All 7 algorithms implemented in `src/inode.rs`:
   - `passthrough`, `path-hash`, `path-hash32`
   - `devino-hash`, `devino-hash32` (these preserve hard links!)
   - `hybrid-hash`, `hybrid-hash32` (default)

2. **Integration**: The inode calculation is properly integrated:
   - `create_file_attr()` uses `config.inodecalc.calc()` to calculate inodes
   - Configuration supports runtime selection of algorithm
   - Hard links on the same branch DO get the same calculated inode with devino/hybrid modes

3. **Backend Support**: File operations support hard links:
   - `FileManager::create_hard_link()` works correctly
   - The FUSE `link()` operation is implemented

### The Core Problem

The issue is in the FUSE layer's caching model:

```rust
// Current problematic structure in fuse_fs.rs:
path_cache: RwLock<HashMap<String, u64>>,  // Assumes 1 path = 1 inode!
inodes: RwLock<HashMap<u64, InodeData>>,  // Only stores one path per inode

struct InodeData {
    pub path: String,  // Only ONE path stored!
    pub attr: FileAttr,
    pub content_lock: Arc<RwLock<()>>,
}
```

When a hard link is created:
1. The filesystem correctly creates the hard link
2. The inode calculation correctly returns the same inode
3. BUT the cache creates a NEW inode entry because `insert_inode()` doesn't check for existing inodes
4. Result: Two paths with different virtual inodes pointing to the same file

## C++ Implementation Analysis

The C++ mergerfs doesn't maintain a complex inode cache. Instead:
1. It calculates inodes on-demand using the configured algorithm
2. For devino-based algorithms, hard links naturally get the same inode
3. No complex caching or path tracking needed

## Proposed Solution

### Option 1: Minimal Fix (Recommended)

Don't maintain a complex many-to-many cache. Instead, follow the C++ approach:

1. **Remove path_cache entirely** - Calculate inodes on-demand
2. **Store branch + original inode in InodeData** - For recalculation
3. **Always recalculate inodes** - Let the algorithm handle consistency

```rust
pub struct InodeData {
    pub path: String,                    // Primary path for this inode
    pub attr: FileAttr,
    pub content_lock: Arc<RwLock<()>>,
    // Add these fields:
    pub branch_idx: usize,               // Which branch this file is on
    pub original_ino: u64,               // Original inode from filesystem
}

impl MergerFS {
    fn lookup(&mut self, parent: u64, name: &OsStr, reply: ReplyEntry) {
        let path = construct_path(parent, name);
        
        // Get metadata and branch
        let (metadata, branch_idx) = self.find_file_and_branch(&path)?;
        
        // Calculate inode - this handles hard links correctly!
        let ino = self.config.read().inodecalc.calc(
            &self.branches[branch_idx].path,
            &path,
            metadata.file_type(),
            metadata.ino()
        );
        
        // Check if we already have this inode cached
        if let Some(existing) = self.inodes.read().get(&ino) {
            // Update attributes but keep the inode
            reply.entry(&TTL, &existing.attr, 0);
        } else {
            // Create new inode entry
            let attr = create_file_attr_with_ino(ino, &metadata);
            self.inodes.write().insert(ino, InodeData {
                path: path.clone(),
                attr,
                content_lock: Arc::new(RwLock::new(())),
                branch_idx,
                original_ino: metadata.ino(),
            });
            reply.entry(&TTL, &attr, 0);
        }
    }
}
```

### Option 2: Full Many-to-Many Mapping

Implement complete path tracking (more complex, not recommended):

```rust
pub struct InodeManager {
    inodes: RwLock<HashMap<u64, InodeData>>,
    path_to_inode: RwLock<HashMap<String, u64>>,
    inode_to_paths: RwLock<HashMap<u64, HashSet<String>>>,
}
```

This matches some Unix filesystem implementations but adds significant complexity.

## Implementation Plan (Option 1)

### Phase 1: Refactor InodeData (1 day)
1. Add `branch_idx` and `original_ino` fields to `InodeData`
2. Update all places that create `InodeData` to populate these fields
3. Remove the `path_cache` - it's not needed

### Phase 2: Update Lookup Logic (1 day)
1. Modify `lookup()` to:
   - Find the file and determine its branch
   - Calculate the inode using the existing calculation
   - Check if inode already exists before creating new entry
2. Update `create_file_attr()` to accept branch info

### Phase 3: Fix Link Operation (1 day)
1. Update `link()` to:
   - Not create a new inode entry
   - Reuse the existing inode from the source file
   - Just return the existing inode in the reply

### Phase 4: Update Other Operations (1 day)
1. Update `getattr()` to handle inode lookups correctly
2. Update `unlink()` to only remove inode when no more hard links exist
3. Ensure `rename()` updates the path in InodeData if needed

### Phase 5: Testing (1 day)
1. Enable all hard link tests
2. Add specific tests for cache behavior
3. Performance testing to ensure no regression

## Code Changes Required

### 1. Remove path_cache
```rust
// DELETE these lines from MergerFS struct:
// path_cache: parking_lot::RwLock<HashMap<String, u64>>,

// DELETE these methods:
// pub fn path_to_inode(&self, path: &str) -> Option<u64>
// And all path_cache operations
```

### 2. Update InodeData
```rust
#[derive(Debug, Clone)]
pub struct InodeData {
    pub path: String,
    pub attr: FileAttr,
    pub content_lock: Arc<parking_lot::RwLock<()>>,
    pub branch_idx: usize,      // NEW
    pub original_ino: u64,      // NEW
}
```

### 3. Update lookup() 
```rust
fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
    // ... construct path ...
    
    // Find file and branch
    let (metadata, branch_idx) = match self.find_file_and_branch(&path) {
        Some(result) => result,
        None => {
            reply.error(ENOENT);
            return;
        }
    };
    
    // Calculate inode using existing algorithm
    let calculated_ino = self.config.read().inodecalc.calc(
        &self.branches[branch_idx].path,
        &path,
        metadata.file_type(),
        metadata.ino()
    );
    
    // Check if this inode already exists (hard link case)
    let mut inodes = self.inodes.write();
    if let Some(existing) = inodes.get(&calculated_ino) {
        // Hard link detected! Same inode already exists
        reply.entry(&TTL, &existing.attr, 0);
    } else {
        // New inode
        let attr = self.create_file_attr_with_ino(calculated_ino, &metadata);
        inodes.insert(calculated_ino, InodeData {
            path: path.clone(),
            attr,
            content_lock: Arc::new(RwLock::new(())),
            branch_idx,
            original_ino: metadata.ino(),
        });
        reply.entry(&TTL, &attr, 0);
    }
}
```

### 4. Simplify link()
```rust
fn link(&mut self, _req: &Request<'_>, ino: u64, newparent: u64, newname: &OsStr, reply: ReplyEntry) {
    // Get source inode
    let source_data = match self.get_inode_data(ino) {
        Some(data) => data,
        None => {
            reply.error(ENOENT);
            return;
        }
    };
    
    // Create hard link on filesystem
    let link_path = construct_path(newparent, newname);
    if let Err(e) = self.file_manager.create_hard_link(&source_data.path, &link_path) {
        reply.error(error_to_errno(e));
        return;
    }
    
    // Return the SAME inode - no new entry needed!
    // The inode calculation will ensure future lookups find this inode
    reply.entry(&TTL, &source_data.attr, 0);
}
```

## Testing Strategy

### 1. Unit Tests
- Test inode calculation returns same value for hard links
- Test inode cache handles duplicate inodes correctly
- Test cleanup when last hard link is removed

### 2. Integration Tests
- All existing hard link tests should pass
- Add tests for many hard links (100+)
- Test hard links across directories
- Test rename operations on hard links

### 3. Performance Tests
- Ensure no regression in lookup performance
- Memory usage should stay reasonable
- Large directory listing performance

## Risk Assessment

### Low Risk
- Changes are localized to FUSE layer
- Backend already supports hard links
- Inode calculation already implemented

### Mitigations
- Extensive testing before deployment
- Can be feature-flagged if needed
- Fallback to current behavior possible

## Success Criteria

1. ✅ Hard links report the same inode number
2. ✅ `nlink` counts are correct
3. ✅ All hard link tests pass
4. ✅ No performance regression
5. ✅ Compatible with C++ mergerfs behavior

## Conclusion

The infrastructure for proper hard link support already exists in mergerfs-rs. The only missing piece is updating the FUSE layer's caching model to handle many-to-one path-to-inode mappings. The proposed solution removes unnecessary complexity and follows the C++ implementation's approach of calculating inodes on-demand, letting the devino-hash algorithm naturally handle hard link consistency.