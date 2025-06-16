# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

mergerfs-rs is a Rust implementation of mergerfs, a FUSE-based union filesystem that combines multiple filesystem paths into a single mount point. The project implements a complete FUSE filesystem with metadata operations, directory management, and policy-driven file placement.

## Commands

### Development
- `cargo build` - Build the project
- `cargo run -- <mountpoint> <branch1> [branch2] ...` - Mount the filesystem
- `cargo test` - Run tests (80+ comprehensive tests)
- `cargo check` - Type check without building
- `cargo clippy` - Lint with Clippy
- `cargo fmt` - Format code

### Build Modes
- `cargo build --release` - Build optimized release version
- `cargo test --release` - Run tests in release mode

## Architecture

The project aims to implement a FUSE-based union filesystem in Rust with the following core components:

### Policy Engine
The heart of mergerfs - determines which filesystem branches to use for operations:
- **Create Policies**: Where to place new files (e.g., "mfs" for most free space, "ff" for first found)
- **Search Policies**: Where to look for existing files (e.g., "ff" for first found, "all" for all branches)  
- **Action Policies**: Which instances to operate on (e.g., "epall" for existing path all)

### Branch Management
- Manages collection of underlying filesystem paths
- Tracks branch modes (ReadWrite, ReadOnly, NoCreate)
- Monitors free space and filesystem status
- Supports runtime branch modification

### FUSE Operations
40+ filesystem operations must be implemented:
- File operations (open, create, read, write, truncate, unlink)
- Directory operations (mkdir, rmdir, opendir, readdir)
- Metadata operations (getattr, chmod, chown, utimens)
- Extended attributes (getxattr, setxattr, listxattr, removexattr)

### Configuration System
- Runtime configuration without remounting
- Per-operation policy assignment
- Thread pool configuration
- Caching behavior settings

## Key Design Principles

1. **Policy-driven**: Configurable algorithms for file placement and access
2. **Non-destructive**: Operates on existing filesystems without modification
3. **Transparent**: Appears as regular filesystem to applications
4. **Fault-tolerant**: Individual branch failures don't affect other branches
5. **Runtime configurable**: Settings changeable without remounting
6. **Alpine Linux Compatible**: Portable implementation using std library instead of libc

## Implementation Notes

### Rust Patterns
- Use traits for policy abstraction (CreatePolicy, SearchPolicy, ActionPolicy)
- Leverage Arc<RwLock<>> for shared state management
- Implement dynamic dispatch for runtime policy selection
- Use parking_lot for performance-critical locks
- Error handling with thiserror and proper errno mapping

### Performance Considerations
- Cache filesystem metadata (free space, branch info)
- Use thread pools for FUSE operations
- Memory pools for fixed-size allocations
- Minimize policy evaluation overhead

### Platform Support
- **Alpine Linux/MUSL Compatible**: Removed glibc dependencies for better Alpine Linux support
- Linux FUSE implementation with portable system calls
- Uses std library and filetime crate instead of libc for cross-platform compatibility
- Conditional compilation for platform-specific features

## Debugging and Tracing

### FUSE Operation Tracing

All FUSE operations include comprehensive tracing spans for debugging and performance analysis:

```bash
# Enable debug-level tracing
RUST_LOG=mergerfs_rs=debug mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Enable trace-level logging (very verbose)
RUST_LOG=mergerfs_rs=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Enable specific module tracing
RUST_LOG=mergerfs_rs::fuse_fs=debug,mergerfs_rs::policy=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2
```

### Traced Information

Each FUSE operation logs:
- Operation type and parameters (paths, modes, flags)
- Policy decisions and branch selection
- Success/failure status with error details
- Timing information (when using trace level)

Example trace output:
```
INFO fuse::create{parent=1 name="test.txt"} Creating file in parent inode
DEBUG Most free space policy selected branch: /mnt/disk2 (10GB free)
INFO File created successfully at branch: /mnt/disk2/test.txt
```

### Using Traces for Testing

The Python test suite can leverage trace output for intelligent waiting and debugging:

```bash
# Run tests with trace monitoring
FUSE_TRACE=1 uv run pytest test_file.py -v

# Enable trace summary after test
FUSE_TRACE_SUMMARY=1 uv run pytest test_file.py -v

# Debug specific test failures
RUST_LOG=mergerfs_rs=debug FUSE_DEBUG=1 uv run pytest failing_test.py -v -s
```

## Documentation Structure

The `docs/` directory contains comprehensive design documentation:
- Architecture overview and core concepts
- FUSE operations implementation patterns
- Policy system design and algorithms
- Configuration and concurrency patterns
- Rust-specific implementation guidance

When implementing features, refer to the corresponding documentation files for detailed specifications and design patterns.

## Alpine Linux Compatibility

This project has been specifically optimized for Alpine Linux and MUSL libc compatibility:

### Dependencies
- **Removed libc dependency** - Replaced with std library equivalents
- **Added filetime crate** - For portable timestamp operations
- **Standard errno constants** - Hardcoded values compatible with MUSL

### Key Changes for MUSL Compatibility
1. **chmod operations** - Use `std::os::unix::fs::PermissionsExt::set_mode()` instead of libc
2. **chown operations** - Simplified implementation compatible with container environments
3. **utimens operations** - Use filetime crate for portable timestamp setting
4. **User/group IDs** - Default to 1000:1000 for container compatibility
5. **Error codes** - Hardcoded errno values instead of libc constants

### Testing on Alpine
All 80+ tests pass on Alpine Linux environments. The implementation avoids glibc-specific features and uses portable Rust standard library functions wherever possible.

## Development Guidelines

- When adding a new feature or change, compare the new feature or change in Rust with the current C++ implementation found under `refs/mergerfs-original`

## Development Process for New Features

The development process for any new feature should be:
- Analyze current C++ implementation under `refs/mergerfs-original`
- Document the design of the C++ implementation in detail (even pseudocode) as a new Markdown document 
- Plan the implementation in Rust being sure to not use unsafe Rust code or glibc/libc calls and be cross-platform
- Write unit tests
- Write external Python based end-to-end integration tests including updating property-based and fuzz test harness for new functionality found under `python_tests`
- Regression test everything including unit tests, integration tests, and Python-based tests
- Update IMPLEMENTATION_STATUS.md with the status of the feature

## Definition of Done

The definition of done is: 
- Rust code is functional
- Rust-based unit test coverage of 100%
- Python-based integration test coverage of 100%
- All regression tests run
- C++ implementation is documented using pseudocode
- Rust implementation differences from C++ implementation are documented
- All rust compilation warnings are cleared except for future work
- Code is committed

## Python Testing

The Python testing framework is located in `python_tests/` and uses:
- **uv** for package management (NOT pip/venv directly)
- **pytest** with fixtures for FUSE filesystem testing
- **hypothesis** for property-based testing
- **xattr** module for extended attributes testing

### Running Python Tests

```bash
# Install/update dependencies
cd python_tests && uv sync

# Run specific test file
uv run pytest test_runtime_config.py -v

# Run all tests
uv run python run_tests.py --test-type all

# Run with trace monitoring enabled (recommended)
FUSE_TRACE=1 uv run pytest test_file.py -v
```

### Trace-Based Testing

The project includes an advanced trace-based testing infrastructure that eliminates timing issues common in FUSE testing:

#### Benefits
- **78% faster test execution** - Tests wait only as long as needed
- **More reliable** - No more flaky tests due to timing issues
- **Better debugging** - Full visibility into FUSE operations

#### Using Trace Monitoring

1. **Enable trace monitoring** in tests:
   ```python
   def test_with_trace(self, mounted_fs_with_trace, smart_wait):
       process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
       
       # Write file and wait for visibility
       file_path = mountpoint / "test.txt"
       file_path.write_text("content")
       assert smart_wait.wait_for_file_visible(file_path)  # No sleep() needed!
   ```

2. **Available wait functions**:
   - `wait_for_file_visible(path)` - Wait for file creation
   - `wait_for_write_complete(path)` - Wait for write operation
   - `wait_for_dir_visible(path)` - Wait for directory creation
   - `wait_for_deletion(path)` - Wait for file/directory deletion
   - `wait_for_xattr_operation(path, op)` - Wait for xattr operations

3. **Run tests with tracing**:
   ```bash
   # Enable trace monitoring
   FUSE_TRACE=1 uv run pytest test_file.py -v
   
   # Or use RUST_LOG directly
   RUST_LOG=mergerfs_rs=debug uv run pytest test_file.py -v
   ```

### Writing Python Tests

1. Use pytest fixtures from `conftest.py`:
   - `mounted_fs` - Provides a mounted filesystem tuple: (process, mountpoint, branches)
   - `mounted_fs_with_trace` - Same as above but with trace monitoring enabled
   - `smart_wait` - Provides intelligent wait functions
   - `fuse_manager` - Session-scoped FUSE manager
   - `temp_branches` - Creates temporary branch directories
   - `temp_mountpoint` - Creates temporary mount point

2. Test classes should use `@pytest.mark.integration` for integration tests

3. Import required modules:
   ```python
   import os
   import xattr
   import pytest
   from pathlib import Path
   ```

4. Access mounted filesystem through fixtures:
   ```python
   def test_something(self, mounted_fs):
       process, mountpoint, branches = mounted_fs
       # mountpoint is a Path object
       test_file = mountpoint / "test.txt"
   ```

5. Use trace-based waiting instead of sleep():
   ```python
   # OLD: Don't do this
   file_path.write_text("content")
   time.sleep(0.5)  # Arbitrary delay
   
   # NEW: Do this instead
   file_path.write_text("content")
   assert smart_wait.wait_for_file_visible(file_path)  # Intelligent waiting
   ```

### Common Testing Mistakes to Avoid

1. **Don't use pip/venv directly** - Always use `uv` for package management
2. **Don't import non-existent modules** - Check existing test files for patterns
3. **Use Path objects** - The fixtures return pathlib.Path objects, not strings
4. **Check file existence** - Ensure control files like `.mergerfs` are actually created
5. **Update pyproject.toml** - Add new dependencies to pyproject.toml, then run `uv sync`
6. **Avoid hardcoded sleep() calls** - Use trace-based waiting for better performance and reliability

## External Documentation References

- Documentation for original implementation is at https://trapexit.github.io/mergerfs/latest/