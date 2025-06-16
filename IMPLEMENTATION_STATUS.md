# mergerfs-rs Implementation Status

This document tracks the overall implementation progress of mergerfs-rs, a Rust implementation of the mergerfs union filesystem.

## Project Overview

mergerfs-rs aims to be a complete, compatible implementation of mergerfs in Rust, providing:
- Union filesystem functionality combining multiple branches
- Policy-driven file placement and access
- FUSE-based transparent filesystem interface
- Alpine Linux/MUSL compatibility
- Memory-safe implementation without unsafe code

## Overall Progress

- **FUSE Operations**: 24 of 40+ implemented (60%)
- **Policies**: 9 of 36 implemented (25%)
- **Special Features**: 5 of 10+ implemented (50%)
- **Test Coverage**: 175 tests passing (164 Rust + 11 Python)

## Implementation Status by Component

### ✅ Completed Features

#### Core Infrastructure
- [x] Branch management system with ReadWrite/ReadOnly modes
- [x] Basic FUSE filesystem structure
- [x] Inode management and path resolution
- [x] Error handling with proper errno mapping
- [x] Alpine Linux/MUSL compatibility (no libc dependency)
- [x] Permission checking utilities for access control
- [x] Comprehensive tracing/logging infrastructure for all FUSE operations

#### FUSE Operations (24/40+)
- [x] `lookup` - Find files/directories
- [x] `getattr` - Get file attributes
- [x] `setattr` - Set file attributes (chmod, chown, truncate, utimens)
- [x] `open` - Open files
- [x] `read` - Read file data
- [x] `write` - Write file data (with offset support)
- [x] `create` - Create new files
- [x] `mkdir` - Create directories
- [x] `rmdir` - Remove directories
- [x] `unlink` - Delete files
- [x] `readdir` - List directory contents
- [x] `flush` - Flush file buffers
- [x] `fsync` - Sync file to disk
- [x] `statfs` - Get filesystem statistics
- [x] `release` - Close file handles
- [x] `getxattr`/`setxattr`/`listxattr`/`removexattr` - Extended attributes
- [x] `rename` - Rename files and directories (with multi-branch support)
- [x] `symlink` - Create symbolic links (with path cloning)
- [x] `readlink` - Read symbolic links
- [x] `link` - Create hard links (basic functionality, no EXDEV handling)
- [x] `access` - Check file permissions
- [x] `mknod` - Create special files (FIFOs, devices, sockets)
- [x] `opendir` - Open directory handle
- [x] `releasedir` - Release directory handle

#### Policies (8/36)
**Create Policies (5/16)**:
- [x] `ff` (FirstFound) - First writable branch
- [x] `mfs` (MostFreeSpace) - Branch with most free space
- [x] `lfs` (LeastFreeSpace) - Branch with least free space
- [x] `rand` (Random) - Random branch selection
- [x] `epmfs` (ExistingPathMostFreeSpace) - Existing path with most free space

**Action Policies (3/4)**:
- [x] `all` - Apply to all branches
- [x] `epall` (ExistingPathAll) - All branches where path exists
- [x] `epff` (ExistingPathFirstFound) - First branch where path exists

**Search Policies (3/3)**:
- [x] `ff` (FirstFound) - First branch where file exists
- [x] `all` - Return all branches where file exists
- [x] `newest` - Return branch with newest mtime

#### Special Features
- [x] File handle tracking with branch affinity
- [x] Extended attributes (xattr) support with policy integration
- [x] Configuration system (StatFS modes)
- [x] Comprehensive Python integration tests with Hypothesis
- [x] moveonenospc - Automatic file migration on ENOSPC/EDQUOT

### 🚧 In Progress / High Priority

#### FUSE Operations
- [ ] `fsyncdir` - Sync directory (LOW)

#### Policies (9/36)
**Create Policies (6/16)**:
- [x] `pfrd` (ProportionalFillRandomDistribution) - Random weighted by free space
- [ ] `lus` - Least used space (MEDIUM)
- [ ] `eplfs` - Existing path, least free space (MEDIUM)


**Action Policies**:
- [ ] `erofs` - Error read-only filesystem (LOW)

#### Special Features
- [x] Runtime policy configuration via xattr on control file (/.mergerfs)
- [x] Search policy integration into FUSE operations (basic file search)
- [x] moveonenospc - Move files when out of space (COMPLETED)
- [ ] Path preservation for "existing path" policies
- [ ] Direct I/O support

### ❌ Not Implemented

#### FUSE Operations (18+)
- Directory sync: `fsyncdir`
- Advanced I/O: `poll`, `fallocate`, `ftruncate`, `copy_file_range`
- Locking: `lock`, `flock`
- Time operations: separate `utimens` operation
- Advanced readdir: `readdir_plus`

#### Policies (22)
- Most shared path variants: `mspmfs`, `msplfs`, `msplus`, `msppfrd`
- Existing path variants: `eplfs`, `eplus`, `eprand`, `eppfrd`
- Advanced create policies: various weighted and conditional policies

#### Special Features
- symlinkify - Convert old files to symlinks
- Security contexts (SELinux)
- Advanced caching strategies
- Multiple readdir implementations
- Lazy umount support
- Branch management at runtime

## Implementation Priorities

### Phase 1: Core Compatibility (Current Focus)
1. ✅ **Essential FUSE operations**: symlink, link operations (COMPLETED)
2. ✅ **Search policy `all`**: Required for many use cases (COMPLETED)
3. ✅ **Create policy `epmfs`**: Common balanced distribution policy (COMPLETED)

### Phase 2: Enhanced Functionality
1. ✅ **moveonenospc**: Automatic file migration on ENOSPC (COMPLETED)
2. **Path preservation**: Keep related files together
3. **Additional policies**: lus, newest (pfrd COMPLETED)
4. ✅ **Directory handles**: Proper opendir/releasedir (COMPLETED)
5. ✅ **Access checks**: Proper permission validation (COMPLETED)

### Phase 3: Advanced Features
1. **Performance optimizations**: Caching, readdir_plus
2. **File locking**: POSIX and BSD locks
3. **Advanced I/O**: fallocate, copy_file_range
4. **Rare policies**: Most shared path variants
5. **symlinkify**: Space-saving feature

## Testing Status

### Test Coverage
- **Unit Tests**: 147 Rust tests covering core functionality
- **Integration Tests**: Python tests with property-based testing
- **FUSE Tests**: Real filesystem mount testing with comprehensive scenarios
- **Trace-Based Testing**: Advanced test infrastructure that monitors FUSE operations for intelligent synchronization

### Test Categories
- ✅ File operations (create, read, write, delete)
- ✅ Directory operations (create, list, remove)
- ✅ Metadata operations (chmod, chown, timestamps)
- ✅ Policy testing (all implemented policies)
- ✅ Branch management (readonly, readwrite)
- ✅ Extended attributes (xattr)
- ✅ Symbolic links (creation and reading)
- ✅ Hard links (basic functionality)
- ✅ Access permission checking
- ✅ Special files (FIFOs/named pipes)
- ✅ Runtime configuration (via xattr)
- ✅ Trace-based timing (eliminates flaky tests, 78% faster execution)

## Known Issues

1. **Performance**: No caching or optimization implemented
2. **Error Aggregation**: Simple error handling compared to C++ version
3. **Memory Usage**: No memory pooling or optimization
4. **Compatibility**: Some edge cases may differ from C++ mergerfs

## Development Guidelines

### Adding New Features
1. **Study C++ implementation**: Review original mergerfs code
2. **Document design**: Create design doc in `docs/`
3. **Implement in Rust**: Follow existing patterns, no unsafe code
4. **Add tracing**: Include comprehensive tracing spans for debugging
5. **Write unit tests**: Comprehensive test coverage
6. **Add integration tests**: Python tests using trace-based framework
7. **Update this status**: Keep implementation status current

### Code Standards
- No unsafe code
- Proper error handling with errno mapping
- Thread-safe implementations using Arc/RwLock
- Policy-driven design for flexibility
- Alpine Linux/MUSL compatibility
- Comprehensive tracing for all operations

### Testing Standards
- Use trace-based testing infrastructure for reliability
- Replace sleep() with intelligent wait functions
- Enable FUSE_TRACE=1 for all test runs
- Monitor operation completion instead of arbitrary delays

## Implementation Details

### Space Calculation
- Uses `f_bavail` (blocks available to unprivileged users) instead of `f_bfree` for space calculations
- This matches the C++ mergerfs behavior and respects filesystem reservations
- Implemented using the `nix` crate for portable `statvfs` support
- See `docs/SPACE_CALCULATION.md` for detailed information

### Symlink Handling
- Uses `symlink_metadata()` instead of `metadata()` to preserve symlink attributes
- Properly detects and reports symlinks as `FileType::Symlink` in FUSE operations
- Matches C++ implementation's default behavior (follow_symlinks=NEVER)

### Access Operation
- Implements POSIX-compliant permission checking
- Supports F_OK, R_OK, W_OK, X_OK access modes
- Manual permission bit checking without libc dependency
- See `docs/ACCESS_OPERATION_DESIGN.md` for implementation details

### Directory Handle Management
- Implements proper opendir/releasedir operations with handle tracking
- Directory handles maintain path context between operations
- Compatible with clients that may not use opendir before readdir
- Thread-safe handle storage using parking_lot RwLock
- See `docs/OPENDIR_RELEASEDIR_DESIGN.md` for implementation details

### MoveOnENOSPC Feature
- Automatically moves files to another branch when write fails with ENOSPC/EDQUOT
- Configurable via xattr with support for any create policy
- Preserves file handles and attributes during migration
- Default policy is PFRD (Proportional Fill Random Distribution)
- See `docs/MOVEONENOSPC_DESIGN.md` for implementation details

## Resources

- **Documentation**: See `docs/` directory for detailed design docs
- **Original Code**: `refs/mergerfs-original/` contains C++ implementation
- **Python Tests**: `python_tests/` for integration testing
- **Examples**: See existing implementations for patterns

## Next Steps

1. Implement lus (least used space) create policy
2. Implement path preservation for remaining "existing path" policies
3. Add fallocate support for preallocation
4. Implement fsyncdir for directory synchronization
5. Add direct I/O support

---

*Last Updated: January 2025*
*Total Progress: ~40% of full mergerfs functionality*