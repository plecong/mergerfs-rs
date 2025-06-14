# Testing Guide for mergerfs-rs

This guide explains how to run tests for the mergerfs-rs project.

## Quick Start

From the root of the workspace, use the `test.sh` script:

```bash
# Run all tests (Rust unit tests + Python integration tests)
./test.sh all

# Run only Rust unit tests
./test.sh unit

# Run only Python integration tests
./test.sh int

# Run specific test file
./test.sh specific test_mfs_policy.py

# Run with debug logging
./test.sh debug mfs
```

## Test Scripts

### `test.sh` - Main test runner
A convenient wrapper that handles common testing scenarios:
- Runs from any directory within the workspace
- Automatically builds the Rust project before running Python tests
- Provides colored output for better readability
- Supports various test subsets (unit, integration, policy tests, etc.)

### `run_python_tests.sh` - Python test runner
Lower-level script that:
- Changes to the python_tests directory
- Syncs dependencies with `uv`
- Runs pytest with the specified arguments
- Returns to the original directory

## Available Commands

### Basic Commands
- `./test.sh unit` - Run Rust unit tests
- `./test.sh int` - Run Python integration tests
- `./test.sh all` - Run all tests

### Policy Tests
- `./test.sh mfs` - Run MFS (Most Free Space) policy tests
- `./test.sh policy` - Run all policy-related tests

### Specific Tests
- `./test.sh specific test_file.py` - Run a specific test file
- `./test.sh specific test_file.py::TestClass::test_method` - Run a specific test

### Debug Mode
- `./test.sh debug mfs` - Run MFS tests with debug logging
- `./test.sh debug all` - Run all tests with debug logging

### Maintenance
- `./test.sh clean` - Clean build artifacts and temp files

## Direct pytest Usage

You can also use `run_python_tests.sh` directly with pytest arguments:

```bash
# Run with verbose output
./run_python_tests.sh -v

# Run specific test with short traceback
./run_python_tests.sh tests/test_mfs_policy.py -v --tb=short

# Run with specific markers
./run_python_tests.sh -m "policy and not slow"
```

## Test Categories

The Python tests are organized into several categories:

- **Policy Tests**: Test file creation policies (FF, MFS, LFS, Random)
- **File Operations**: Test basic file operations through FUSE
- **Directory Operations**: Test directory creation and traversal
- **Metadata Tests**: Test chmod, chown, timestamps
- **Extended Attributes**: Test xattr operations
- **Concurrent Access**: Test multi-threaded access patterns
- **Property-based Tests**: Hypothesis-based generative testing

## Debugging Failed Tests

When tests fail:

1. Run with verbose output: `./test.sh specific failing_test.py -v`
2. Enable debug logging: `./test.sh debug specific failing_test.py`
3. Check for leftover mount points: `mount | grep mergerfs`
4. Clean up temp files: `./test.sh clean`

## Requirements

- Rust toolchain (for building mergerfs-rs)
- Python 3.8+ 
- `uv` package manager
- FUSE development libraries

## Troubleshooting

### Tests hang or timeout
- Check for stuck FUSE processes: `ps aux | grep mergerfs-rs`
- Kill stuck processes: `pkill -9 mergerfs-rs`
- Clean temp directories: `./test.sh clean`

### Permission errors
- Ensure you have permissions to mount FUSE filesystems
- On some systems, you may need to be in the `fuse` group

### Build failures
- Run `cargo build` manually to see detailed errors
- Ensure all Rust dependencies are installed

### Python dependency issues
- Run `cd python_tests && uv sync` to update dependencies
- Check `python_tests/pyproject.toml` for required packages