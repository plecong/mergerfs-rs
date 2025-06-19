# Inode Calculation in mergerfs

## Overview

mergerfs uses configurable inode calculation algorithms to generate consistent inode numbers for files and directories across the union filesystem. This is important for applications that rely on inode numbers for file identification, particularly for hard links.

## C++ Implementation

### Algorithm Types

The C++ implementation provides the following inode calculation modes:

1. **passthrough** - Uses the original inode from the underlying filesystem
2. **path-hash** - Hashes the FUSE path (virtual path) to generate inode
3. **path-hash32** - 32-bit version of path-hash
4. **devino-hash** - Hashes the branch path + original inode (device+inode)
5. **devino-hash32** - 32-bit version of devino-hash
6. **hybrid-hash** (default) - Uses path-hash for directories, devino-hash for files
7. **hybrid-hash32** - 32-bit version of hybrid-hash

### Implementation Details

```cpp
// Pseudocode for inode calculation

uint64_t calc_inode(branch_path, fuse_path, mode, original_ino) {
    switch (algorithm) {
        case passthrough:
            return original_ino;
            
        case path_hash:
            return rapidhash(fuse_path);
            
        case devino_hash:
            seed = rapidhash(branch_path);
            return rapidhash_withSeed(original_ino, seed);
            
        case hybrid_hash:
            if (S_ISDIR(mode))
                return path_hash(branch_path, fuse_path, mode, original_ino);
            else
                return devino_hash(branch_path, fuse_path, mode, original_ino);
    }
}
```

### Key Features

1. **Hard Link Support**: With devino-hash modes, hard links on the same branch share the same calculated inode
2. **Cross-Branch Consistency**: Path-hash modes provide consistent inodes regardless of which branch contains the file
3. **Runtime Configuration**: The algorithm can be changed at runtime via xattr interface
4. **32-bit Compatibility**: 32-bit variants are provided for systems with 32-bit inode limitations

### Usage Patterns

- **Default (hybrid-hash)**: Best general-purpose mode
  - Directories use path-hash for consistency across branches
  - Files use devino-hash to preserve hard link relationships
  
- **passthrough**: Direct mapping, useful when branch inodes are already unique
- **path-hash**: Useful when consistent inodes across branches is more important than hard link preservation
- **devino-hash**: Best for preserving hard link relationships

## Rust Implementation

### Current Status

The Rust implementation includes:

1. All seven inode calculation algorithms
2. Runtime configuration via xattr interface
3. Proper calculation for all file operations

### Implementation Differences

1. **Hashing Algorithm**: Uses Rust's DefaultHasher instead of rapidhash
   - This may produce different inode values than the C++ implementation
   - The behavior is consistent within the Rust implementation

2. **Caching Model**: Current limitation with hard links
   - The path-to-inode cache assumes a 1:1 mapping
   - Hard links with shared inodes may not be properly cached
   - This can result in hard links appearing to have different inodes through FUSE

3. **Cache Invalidation**: Not implemented
   - Changing inode calculation mode at runtime doesn't invalidate cached inodes
   - Requires remount for changes to take full effect

### Known Issues

1. **Hard Link Inode Sharing**: While the inode calculation correctly generates the same inode for hard links in devino-hash modes, the FUSE layer's caching may cause them to appear with different inode numbers to applications.

2. **Runtime Mode Changes**: Changing the inode calculation mode at runtime updates new calculations but doesn't affect already-cached inodes.

### Future Improvements

1. **Bidirectional Cache**: Implement a cache that can handle multiple paths mapping to the same inode
2. **Cache Invalidation**: Add proper cache invalidation when configuration changes
3. **Rapidhash Integration**: Consider using rapidhash for compatibility with C++ implementation
4. **Persistent Inode Mapping**: Consider implementing persistent inode mapping for better stability across remounts

## Testing

The implementation includes comprehensive unit tests for all algorithms:

```rust
// Test that hard links share inodes with devino-hash
let file_attr = merger_fs.create_file_attr(file_path).unwrap();
let link_attr = merger_fs.create_file_attr(link_path).unwrap();
assert_eq!(file_attr.ino, link_attr.ino);
```

Integration tests verify the behavior through the FUSE interface, though some tests may fail due to the caching limitations mentioned above.