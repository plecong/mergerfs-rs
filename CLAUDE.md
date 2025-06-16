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
```

### Writing Python Tests

1. Use pytest fixtures from `conftest.py`:
   - `mounted_fs` - Provides a mounted filesystem tuple: (process, mountpoint, branches)
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

### Common Testing Mistakes to Avoid

1. **Don't use pip/venv directly** - Always use `uv` for package management
2. **Don't import non-existent modules** - Check existing test files for patterns
3. **Use Path objects** - The fixtures return pathlib.Path objects, not strings
4. **Check file existence** - Ensure control files like `.mergerfs` are actually created
5. **Update pyproject.toml** - Add new dependencies to pyproject.toml, then run `uv sync`

## External Documentation References

- Documentation for original implementation is at https://trapexit.github.io/mergerfs/latest/