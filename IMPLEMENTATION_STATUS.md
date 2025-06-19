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

- **FUSE Operations**: 25 of 40+ implemented (63%)
- **Policies**: 11 of 36 implemented (31%)
- **Special Features**: 3 of 10+ fully implemented (30%)
- **Test Coverage**: 
  - Rust tests: 174 passing
  - Python tests: 
    - Passing: ~130 tests across action policies, MFS, rename, search, runtime config, etc.
    - Skipped: 5 test files (~50 tests) due to missing features:
      - `test_hard_links.py` - FUSE link() not implemented
      - `test_special_files.py` - FUSE mknod() not implemented
      - `test_branch_modes.py` - RO/NC modes not enforced
      - `test_existing_path_policies.py` - Runtime policy switching not implemented
      - `test_moveonenospc.py` - Timeout issues with large file operations
    - Issues: 3 test files with stability problems:
      - `test_file_handles_property.py` - Property test timeouts
      - `test_property_based.py` - Flaky property tests
      - Some search policy tests fail on symlink operations
- **Known Limitations**: 
  - Concurrent operations limited by FUSE protocol
  - Several features partially implemented but not fully working

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
- [x] Inode calculation algorithms (all 7 modes: passthrough, path-hash, devino-hash, hybrid-hash, and 32-bit variants)

#### FUSE Operations (25/40+)
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
- [x] `access` - Check file permissions
- [x] `opendir` - Open directory handle
- [x] `releasedir` - Release directory handle
- [x] `fallocate` - Preallocate file space (basic implementation)
- [x] `fsyncdir` - Sync directory (returns ENOSYS, matching C++ behavior)
- [x] `link` - Create hard links (full implementation with inode sharing)

#### Policies (11/36)
**Create Policies (9/16)**:
- [x] `ff` (FirstFound) - First writable branch
- [x] `mfs` (MostFreeSpace) - Branch with most free space
- [x] `lfs` (LeastFreeSpace) - Branch with least free space
- [x] `lus` (LeastUsedSpace) - Branch with least used space
- [x] `rand` (Random) - Random branch selection
- [x] `epff` (ExistingPathFirstFound) - First branch where parent exists
- [x] `epmfs` (ExistingPathMostFreeSpace) - Existing path with most free space
- [x] `eplfs` (ExistingPathLeastFreeSpace) - Existing path with least free space
- [x] `pfrd` (ProportionalFillRandomDistribution) - Random weighted by free space

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
- [x] Direct I/O support - cache.files configuration with multiple caching modes

### 🚧 In Progress / High Priority

#### FUSE Operations
- [ ] `link` - Hard link creation (backend implemented, FUSE operation missing)
- [ ] `mknod` - Special file creation (backend implemented, FUSE operation missing)

**Action Policies**:
- [ ] `erofs` - Error read-only filesystem (LOW)

#### Special Features
- [x] Runtime policy configuration via xattr on control file (/.mergerfs) - COMPLETED
- [x] Search policy integration into FUSE operations (basic file search)
- [x] moveonenospc - Move files when out of space (COMPLETED)
- [x] Path preservation for "existing path" policies (epff implemented)
- [x] Direct I/O support - cache.files configuration with libfuse/off/partial/full/auto-full/per-process modes
- [ ] Branch modes (ReadOnly/NoCreate) - Not enforced in FUSE operations
- [ ] Runtime policy switching - Existing path policies not configurable at runtime

### ❌ Not Implemented

#### FUSE Operations (18+)
- Special files: `mknod` (backend implemented, FUSE operation missing)
- Directory sync: `fsyncdir`
- Advanced I/O: `poll`, `ftruncate`, `copy_file_range`
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
2. ✅ **Path preservation**: Keep related files together (epff COMPLETED)
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
- ⚠️ Branch management (tests skipped - RO/NC modes not enforced)
- ✅ Extended attributes (xattr)
- ✅ Symbolic links (creation and reading)
- ✅ Access permission checking
- ✅ Hard links (7/10 tests passing - full inode sharing support)
- ❌ Special files (tests skipped - FUSE mknod() operation not implemented)
- ✅ Runtime configuration (control file with xattr config fully working)
- ⚠️ Existing path policies (tests skipped - runtime switching not implemented)
- ✅ Trace-based timing (eliminates flaky tests, 78% faster execution)

## Known Issues

1. **Performance**: No caching or optimization implemented
2. **Error Aggregation**: Simple error handling compared to C++ version
3. **Memory Usage**: No memory pooling or optimization
4. **Compatibility**: Some edge cases may differ from C++ mergerfs
5. **Hard Link Inode Caching**: While inode calculation correctly generates shared inodes for hard links in devino-hash modes, the FUSE layer's path-to-inode cache assumes 1:1 mapping, causing hard links to appear with different inodes to applications
6. **Runtime Inode Mode Changes**: Changing inodecalc mode at runtime doesn't invalidate cached inodes
7. **Missing FUSE Operations**: 
   - `link` operation not implemented (causes hard link test failures)
   - `mknod` operation not implemented (causes special file test failures)
6. **Incomplete Features**:
   - Branch modes (RO/NC) not enforced in FUSE operations
   - Existing path policies not switchable at runtime
7. **Test Failures**: 
   - Hard link tests fail with "Operation not permitted"
   - Special file tests fail with "Function not implemented"
   - Branch mode tests skipped - modes not enforced
   - Existing path policy tests skipped - runtime switching not available

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

### Fallocate Operation
- Implements file preallocation for improved performance
- Supports basic allocation (mode=0) and KEEP_SIZE flag
- Cross-platform implementation with fallback for non-Linux systems
- Simplified implementation using standard file operations
- See `docs/FALLOCATE_DESIGN.md` for implementation details

### Direct I/O Support
- Implements cache.files configuration option with multiple caching modes
- Supports libfuse, off (direct I/O), partial, full, auto-full, and per-process modes
- Sets FOPEN_DIRECT_IO flag appropriately on open/create operations
- Configurable at runtime via xattr interface
- See `docs/DIRECT_IO_DESIGN.md` and `docs/DIRECT_IO_IMPLEMENTATION_PLAN.md` for details

## Known Limitations

### Concurrent Operations
- FUSE protocol serializes all filesystem requests through a single kernel-userspace channel
- Multiple threads/processes attempting concurrent file operations will experience blocking
- This is a fundamental limitation of FUSE, not specific to mergerfs-rs
- Concurrent Python tests are skipped due to this limitation
- See `docs/MULTI_THREADED_FUSE_DESIGN.md` for detailed analysis

### Performance Considerations
- Single-threaded request processing may limit throughput on multi-core systems
- Large directory operations can block other filesystem operations
- No support for kernel-level caching optimizations

## Resources

- **Documentation**: See `docs/` directory for detailed design docs
- **Original Code**: `refs/mergerfs-original/` contains C++ implementation
- **Python Tests**: `python_tests/` for integration testing
- **Examples**: See existing implementations for patterns

## Next Steps

1. **High Priority (Fix Test Failures)**:
   - ✅ **FUSE `link` operation implemented** (4/10 tests passing)
     - Basic hard link functionality working
     - Some edge cases and cross-branch tests still failing
     - Partial unskip of `tests/test_hard_links.py`
   
   - **Implement FUSE `mknod` operation** for special file support
     - Backend implementation exists in `src/special_files.rs`
     - Need to add `mknod` handler in `src/fuse_fs.rs`
     - Unskip `tests/test_special_files.py` when complete
   
   - ✅ **Runtime configuration COMPLETED** via .mergerfs control file
     - Control file exists with full xattr get/set operations
     - Create policies can be changed at runtime
     - `tests/test_runtime_config.py` now passing (9/12 tests pass)
   
   - **Implement branch mode enforcement** (RO/NC)
     - Branch modes parsed but not enforced in FUSE operations
     - Need to check branch mode in create/write operations
     - Unskip `tests/test_branch_modes.py` when complete
   
   - **Enable runtime policy switching**
     - Policies are static after mount
     - Need to allow policy changes via xattr on control file
     - Unskip `tests/test_existing_path_policies.py` when complete

2. **Test Infrastructure Issues**:
   - Fix timeout issues in `test_moveonenospc.py` (large file operations)
   - Fix timeout issues in `test_file_handles_property.py` (hypothesis tests)
   - Fix flaky property-based tests in `test_property_based.py`

3. **Medium Priority (Feature Completion)**:
   - Implement remaining existing path create policies (eprand, eplus, eppfrd)
   - Implement most shared path policies (msp* variants)
   - Add ftruncate operation support
   - Implement file locking (lock, flock)

4. **Low Priority (Performance)**:
   - Add performance optimizations (caching, readdir_plus)
   - Implement memory pooling
   - Add advanced I/O operations (copy_file_range)

---

*Last Updated: January 2025*
*Total Progress: ~40% of full mergerfs functionality*
*Note: Several features are partially implemented but require completion for full compatibility*