# mergerfs-rs Python Testing Framework

This directory contains a comprehensive Python-based testing framework for mergerfs-rs, designed to test the FUSE filesystem through external process interaction and verify policy behaviors through real filesystem operations.

## Overview

The testing framework includes:

- **Policy Behavior Tests**: Verify that different create policies (FirstFound, MostFreeSpace, LeastFreeSpace, Random) work correctly
- **Property-based Tests**: Use Hypothesis to generate random operations and verify invariants hold
- **Concurrent Access Tests**: Test filesystem behavior under concurrent operations
- **Fuzz Testing Foundation**: Framework for fuzz testing with random operations and invariant checking
- **Union Filesystem Tests**: Verify union behavior, file precedence, and directory operations

## Quick Start

1. **Install dependencies** (using uv):
   ```bash
   cd python_tests
   uv sync
   ```

   Or if you don't have uv installed:
   ```bash
   pip install uv
   uv sync
   ```

2. **Run a quick verification test**:
   ```bash
   python run_tests.py quick
   ```

3. **Run all tests**:
   ```bash
   python run_tests.py all
   ```

## Test Structure

```
python_tests/
├── lib/
│   └── fuse_manager.py      # FUSE process management
├── tests/
│   ├── test_policy_behavior.py      # Policy behavior tests  
│   ├── test_random_policy.py        # Random policy specific tests
│   ├── test_property_based.py       # Property-based tests with Hypothesis
│   ├── test_concurrent_access.py    # Concurrent access tests
│   └── test_fuzz_foundation.py      # Fuzz testing framework
├── conftest.py              # Pytest configuration and fixtures
├── pytest.ini              # Pytest settings
├── pyproject.toml          # Python project configuration (uv)
├── uv.lock                 # Locked dependencies
├── run_tests.py            # Test runner script
└── README.md               # This file
```

## Test Categories

### Policy Behavior Tests (`-m policy`)

Test that create policies work correctly:
- **FirstFound (ff)**: Files created in first writable branch
- **MostFreeSpace (mfs)**: Files created in branch with most available space  
- **LeastFreeSpace (lfs)**: Files created in branch with least available space

```bash
python run_tests.py --test-type policy
```

### Property-based Tests (`-m property`)

Use Hypothesis to generate random filesystem operations and verify:
- Policy consistency across random file operations
- Space-based policy properties 
- Directory creation properties
- Filesystem operation sequences

```bash
python run_tests.py --test-type property
```

### Concurrent Access Tests (`-m concurrent`)

Test filesystem behavior under concurrent access:
- Concurrent file creation with same policy
- Concurrent read/write operations
- High concurrency stress testing
- Concurrent directory operations

```bash
python run_tests.py --test-type concurrent
```

### Fuzz Testing (`-m fuzz`)

Structured fuzz testing with:
- Random operation generation
- Invariant checking (files in single branch, filesystem consistency)
- Crash detection and recovery
- Reproducible testing with seeds

```bash
python run_tests.py --test-type fuzz
```

## Test Runner Options

The `run_tests.py` script provides several options:

```bash
# Test specific policy only
python run_tests.py --policy mfs

# Run tests in parallel
python run_tests.py --parallel 4

# Verbose output
python run_tests.py --verbose

# Force rebuild binary
python run_tests.py --build

# Pass additional pytest arguments
python run_tests.py --test-type policy --verbose -- --tb=short

# Quick verification
python run_tests.py quick

# Complete test suite
python run_tests.py all
```

## How It Works

### FUSE Process Management

The `FuseManager` class handles:
- Finding the mergerfs-rs binary (release or debug build)
- Creating temporary branch directories and mountpoints
- Mounting/unmounting FUSE filesystems with different policies
- Process lifecycle management and cleanup
- Context managers for safe test execution

### External Testing Approach

Unlike unit tests, this framework:
- Spawns actual mergerfs-rs FUSE processes
- Performs real filesystem operations through the mounted filesystem
- Verifies behavior by examining the underlying branch directories
- Tests the complete integration stack including FUSE, policy logic, and filesystem operations

### Test Fixtures

Key pytest fixtures:
- `fuse_manager`: Session-scoped FUSE process manager
- `temp_branches`: 3 temporary branch directories
- `temp_mountpoint`: Temporary mountpoint directory
- `fs_state`: Helper for examining filesystem state
- `policy`: Parametrized fixture for all policies

### Property-based Testing

Uses Hypothesis to:
- Generate random valid filenames and content
- Create sequences of filesystem operations
- Verify invariants hold across all generated scenarios
- Provide reproducible test cases with seeds

### Concurrent Testing

Concurrent tests use:
- `ThreadPoolExecutor` for thread-based concurrency
- Multiple workers performing simultaneous operations
- Verification that operations complete correctly
- Stress testing with high operation counts

## Key Classes

### `FuseManager`
Manages FUSE process lifecycle:
```python
with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
    # Perform filesystem operations
    file_path = mountpoint / "test.txt"
    file_path.write_text("content")
```

### `FuseConfig`
Configuration for FUSE mounts:
```python
config = FuseConfig(
    policy="mfs",
    branches=temp_branches,
    mountpoint=temp_mountpoint
)
```

### `FileSystemState`
Helper for examining filesystem state:
```python
# Check which branches contain a file
locations = fs_state.get_file_locations(branches, "test.txt")

# Get branch disk usage
sizes = fs_state.get_branch_sizes(branches)
```

### `FuzzTester`
Orchestrates fuzz testing:
```python
fuzz_tester = FuzzTester(fuse_manager, config, seed=12345)
results = fuzz_tester.run_fuzz_session(num_operations=100)
```

## Integration with CI/CD

The framework is designed to work in CI environments:
- Automatic binary building if needed
- Timeout handling for stuck operations
- Clear pass/fail criteria
- Structured output for result analysis
- Cleanup of temporary resources

## Future Enhancements

This framework provides the foundation for:
- **Advanced Fuzz Testing**: More sophisticated operation generation and crash detection
- **Performance Benchmarking**: Integration with pytest-benchmark for performance regression testing  
- **Stress Testing**: Extended concurrent access and load testing
- **Policy Development**: Easy addition of new create policies and their tests
- **Property Verification**: Additional invariants and filesystem properties

## Troubleshooting

### Binary Not Found
```
Error: Could not find mergerfs-rs binary
```
**Solution**: Run `cargo build` in the project root, or use `--build` flag

### Mount Failures
```
Error: Failed to mount FUSE filesystem
```
**Solution**: Check that:
- FUSE is available on the system
- No existing mounts at the mountpoint
- Sufficient permissions for FUSE operations

### Test Timeouts
```
Error: Test timed out
```
**Solution**: 
- Increase timeout in pytest.ini
- Use `--timeout=60` to set longer timeout
- Check for deadlocks in concurrent tests

### Permission Errors
```
Error: Permission denied
```
**Solution**:
- Ensure user can mount FUSE filesystems
- Check that temporary directories are writable
- On some systems, add user to `fuse` group