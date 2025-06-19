# Inode Management Refactor Design for Hard Link Support

## Executive Summary

The current mergerfs-rs implementation maintains a 1:1 mapping between paths and inodes, which prevents proper hard link support. This document outlines a comprehensive refactor to align with the C++ mergerfs behavior where hard links on the same branch share the same virtual inode.

## Current Issues

### 1. Separate Virtual Inodes for Hard Links
- **Problem**: Each hard link gets a new virtual inode, even when pointing to the same file
- **Impact**: 
  - `st_nlink` counts are inconsistent between hard links
  - Applications cannot detect that files are hard linked
  - Breaks POSIX semantics for hard links

### 2. Path-to-Inode Cache Assumes 1:1 Mapping
- **Problem**: The `path_cache: HashMap<String, u64>` assumes each path has exactly one inode
- **Impact**: Cannot represent multiple paths (hard links) pointing to the same inode

### 3. Cached Attributes Not Updated
- **Problem**: When hard links are created, existing inodes don't get their `nlink` count updated
- **Impact**: `stat()` returns stale link counts

### 4. No Inode Calculation Algorithm
- **Problem**: Inodes are assigned sequentially without considering the underlying filesystem
- **Impact**: 
  - Hard links on the same branch get different inodes
  - Inodes change between mounts
  - Cannot preserve hard link relationships

## How C++ mergerfs Handles These Issues

### 1. Inode Calculation Algorithms
The C++ implementation provides 7 different inode calculation modes:

```cpp
namespace InodeCalc {
  enum Enum {
    PASSTHROUGH,      // Use original inode
    PATH_HASH,        // Hash the FUSE path
    PATH_HASH32,      // 32-bit path hash
    DEVINO_HASH,      // Hash(branch_path + original_inode)
    DEVINO_HASH32,    // 32-bit devino hash
    HYBRID_HASH,      // Path hash for dirs, devino hash for files (default)
    HYBRID_HASH32     // 32-bit hybrid
  };
}
```

### 2. Key Design Principles

1. **Devino-based algorithms preserve hard links**: By hashing the branch path + original inode, all hard links on the same branch get the same calculated inode

2. **Path-based algorithms provide consistency**: Files always get the same inode based on their path, regardless of which branch they're on

3. **Hybrid mode balances both**: Uses path-hash for directories (consistency) and devino-hash for files (hard link preservation)

### 3. Implementation Details

```cpp
// Simplified inode calculation
uint64_t calc(const char *fusepath, struct stat *st, InodeCalc::Enum algo) {
  switch(algo) {
    case PASSTHROUGH:
      return st->st_ino;
    
    case DEVINO_HASH:
      // Hash branch path + original inode
      // This ensures hard links get same inode
      return hash(branch_path + st->st_ino);
    
    case PATH_HASH:
      // Hash just the FUSE path
      return hash(fusepath);
    
    case HYBRID_HASH:
      if(S_ISDIR(st->st_mode))
        return path_hash(fusepath);
      else
        return devino_hash(branch_path, st->st_ino);
  }
}
```

## Proposed Architecture

### 1. Multi-Path Inode Mapping

Replace the current 1:1 mapping with a bidirectional many-to-many relationship:

```rust
pub struct InodeManager {
    // Forward mapping: inode -> inode data
    inodes: RwLock<HashMap<u64, InodeData>>,
    
    // Reverse mapping: path -> inode
    path_to_inode: RwLock<HashMap<String, u64>>,
    
    // Track all paths for an inode (for hard links)
    inode_to_paths: RwLock<HashMap<u64, HashSet<String>>>,
    
    // Inode calculation algorithm
    inode_calc: InodeCalc,
}

pub struct InodeData {
    pub primary_path: String,        // Original path (for lookup)
    pub attr: FileAttr,              // Cached attributes
    pub content_lock: Arc<RwLock<()>>,
    pub branch_idx: Option<usize>,   // Which branch this inode belongs to
    pub underlying_ino: u64,         // Original inode from filesystem
}
```

### 2. Inode Calculation Module

```rust
pub enum InodeCalc {
    Passthrough,
    PathHash,
    PathHash32,
    DevinoHash,
    DevinoHash32,
    HybridHash,     // Default
    HybridHash32,
}

impl InodeCalc {
    pub fn calculate(&self, path: &Path, metadata: &Metadata, branch: &Branch) -> u64 {
        match self {
            Self::Passthrough => metadata.ino(),
            Self::DevinoHash => self.hash_devino(branch.path(), metadata.ino()),
            Self::PathHash => self.hash_path(path),
            Self::HybridHash => {
                if metadata.is_dir() {
                    self.hash_path(path)
                } else {
                    self.hash_devino(branch.path(), metadata.ino())
                }
            }
            // ... 32-bit variants
        }
    }
}
```

### 3. Updated FUSE Operations

#### Link Operation
```rust
fn link(&mut self, ino: u64, newparent: u64, newname: &OsStr, reply: ReplyEntry) {
    // 1. Get source inode data
    let source_data = self.inode_mgr.get_inode(ino)?;
    
    // 2. Create hard link on filesystem
    self.file_manager.create_hard_link(&source_data.primary_path, &link_path)?;
    
    // 3. Add new path to existing inode (don't create new inode!)
    self.inode_mgr.add_path_to_inode(ino, link_path);
    
    // 4. Refresh attributes to get updated nlink
    let attr = self.refresh_inode_attr(ino)?;
    
    reply.entry(&TTL, &attr, 0);
}
```

#### Lookup Operation
```rust
fn lookup(&mut self, parent: u64, name: &OsStr, reply: ReplyEntry) {
    let path = construct_path(parent, name);
    
    // 1. Check if path already has an inode
    if let Some(ino) = self.inode_mgr.get_inode_for_path(&path) {
        let attr = self.inode_mgr.get_attr(ino)?;
        reply.entry(&TTL, &attr, 0);
        return;
    }
    
    // 2. Path not cached, check filesystem
    let metadata = get_metadata(&path)?;
    let branch = find_branch(&path)?;
    
    // 3. Calculate inode using configured algorithm
    let ino = self.inode_calc.calculate(&path, &metadata, &branch);
    
    // 4. Check if this inode already exists (hard link case)
    if self.inode_mgr.inode_exists(ino) {
        // Add this path to existing inode
        self.inode_mgr.add_path_to_inode(ino, path);
    } else {
        // Create new inode entry
        self.inode_mgr.create_inode(ino, path, metadata, branch);
    }
    
    let attr = self.inode_mgr.get_attr(ino)?;
    reply.entry(&TTL, &attr, 0);
}
```

## Implementation Steps

### Phase 1: Add Inode Calculation (2-3 days)
1. Create `inode_calc.rs` module with all calculation algorithms
2. Add configuration option for inode calculation mode
3. Write comprehensive unit tests for each algorithm
4. Integrate into `create_file_attr()` function

### Phase 2: Refactor Inode Management (3-4 days)
1. Create new `InodeManager` struct with bidirectional mappings
2. Update `InodeData` to include branch and underlying inode info
3. Implement methods for:
   - Adding/removing paths to inodes
   - Checking if inode exists
   - Refreshing attributes
4. Migrate existing code to use `InodeManager`

### Phase 3: Update FUSE Operations (2-3 days)
1. Update `lookup()` to check for existing inodes before creating new ones
2. Update `link()` to reuse existing inodes
3. Update `unlink()` to only remove path mapping, not inode (unless last link)
4. Update `getattr()` to always return fresh `nlink` counts
5. Update `rename()` to handle hard link path updates

### Phase 4: Testing and Validation (2-3 days)
1. Update hard link tests to verify:
   - Same inode for hard links
   - Correct nlink counts
   - Proper cleanup on unlink
2. Add stress tests for many hard links
3. Test inode calculation mode switching
4. Verify no regressions in existing functionality

## Validation Against Current Implementation

### 1. File Handle Manager
- **Impact**: Minimal - file handles already track paths independently
- **Changes**: Ensure file handles work with shared inodes

### 2. Metadata Operations
- **Impact**: Low - operations already work on paths
- **Changes**: Ensure `nlink` updates propagate to all cached inodes

### 3. Directory Operations
- **Impact**: None - directories cannot have hard links
- **Changes**: None required

### 4. Extended Attributes
- **Impact**: Low - xattrs are already path-based
- **Changes**: Ensure xattrs work correctly with hard links

### 5. Rename Operations
- **Impact**: Medium - need to update path mappings
- **Changes**: Update inode manager's path mappings on rename

## Test Scenarios

### 1. Basic Hard Link Tests
- Create file and hard link, verify same inode
- Verify nlink count increases
- Delete original, verify link still works
- Delete all links, verify inode cleanup

### 2. Cross-Branch Hard Links
- Attempt hard link across branches (should fail with EXDEV)
- Verify error handling

### 3. Many Hard Links
- Create 100+ hard links to same file
- Verify performance and correctness
- Test cleanup when deleting many links

### 4. Inode Calculation Modes
- Test each mode's behavior
- Verify hard links work correctly in devino/hybrid modes
- Test mode switching at runtime

### 5. Edge Cases
- Hard links in subdirectories
- Rename operations on hard links
- Hard links with special permissions
- Concurrent operations on hard links

## Performance Considerations

1. **Memory Usage**: Additional HashMap for inode-to-paths mapping
   - Mitigation: Only populated for files with nlink > 1

2. **Lookup Performance**: Extra check for existing inodes
   - Mitigation: Efficient HashMap lookups, early returns

3. **Cache Invalidation**: Changing inode calc mode requires cache clear
   - Mitigation: Rare operation, document requirement

## Risks and Mitigations

1. **Risk**: Breaking existing functionality
   - **Mitigation**: Comprehensive test suite, phased implementation

2. **Risk**: Performance regression
   - **Mitigation**: Benchmark before/after, optimize hot paths

3. **Risk**: Memory leaks with complex mappings
   - **Mitigation**: Careful lifecycle management, leak tests

4. **Risk**: Incompatibility with C++ mergerfs
   - **Mitigation**: Use same hashing algorithms, test interoperability

## Success Criteria

1. All hard link tests pass
2. Hard links report same inode number
3. Correct nlink counts maintained
4. No performance regression > 5%
5. No memory leaks
6. Compatible with C++ mergerfs behavior

## Future Enhancements

1. Implement rapidhash for exact C++ compatibility
2. Add inode generation numbers for NFS support
3. Optimize memory usage for single-link files
4. Add metrics/debugging for inode management