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

2. **Run quick tests** (excludes slow property-based and fuzz tests):
   ```bash
   python run_tests.py quick
   # or
   python run_tests.py --test-type quick
   ```

3. **Run full test suite** (includes all tests with extended timeouts):
   ```bash
   python run_tests.py full
   # or
   python run_tests.py --test-type full
   ```

4. **Run all tests sequentially** (in order of complexity):
   ```bash
   python run_tests.py all
   ```

5. **Run with trace monitoring** (recommended for reliability and speed):
   ```bash
   FUSE_TRACE=1 python run_tests.py quick
   # or
   FUSE_TRACE=1 uv run pytest test_file.py -v
   ```

## Test Structure

```
python_tests/
├── lib/
│   ├── fuse_manager.py      # FUSE process management
│   ├── timing_utils.py      # Advanced trace monitoring
│   └── simple_trace.py      # Simple trace monitoring
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
├── TRACE_BASED_TESTING.md   # Trace monitoring documentation
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

### Property-based Tests (`-m property`) ⚠️ **SLOW**

Use Hypothesis to generate random filesystem operations and verify:
- Policy consistency across random file operations
- Space-based policy properties 
- Directory creation properties
- Filesystem operation sequences

```bash
python run_tests.py --test-type property
```

**Note**: Property-based tests are marked with `@pytest.mark.slow` and excluded from quick test runs.

### Concurrent Access Tests (`-m concurrent`)

Test filesystem behavior under concurrent access:
- Concurrent file creation with same policy
- Concurrent read/write operations
- High concurrency stress testing
- Concurrent directory operations

```bash
python run_tests.py --test-type concurrent
```

### Fuzz Testing (`-m fuzz`) ⚠️ **SLOW**

Structured fuzz testing with:
- Random operation generation
- Invariant checking (files in single branch, filesystem consistency)
- Crash detection and recovery
- Reproducible testing with seeds

```bash
python run_tests.py --test-type fuzz
```

**Note**: Fuzz tests are marked with `@pytest.mark.slow` and excluded from quick test runs.

## Test Organization

### Quick Tests vs Full Tests

To improve developer productivity, tests are organized into two main categories:

1. **Quick Tests** (`python run_tests.py quick`):
   - Excludes property-based tests (`-m property`)
   - Excludes fuzz tests (`-m fuzz`)
   - Excludes any test marked with `@pytest.mark.slow`
   - Uses default 30-second timeout
   - Ideal for rapid development feedback

2. **Full Tests** (`python run_tests.py full`):
   - Includes all tests
   - Uses extended 120-second timeout per test
   - Runs property-based and fuzz tests
   - Ideal for comprehensive validation before commits

### Test Marks

Tests are marked with pytest marks for organization:
- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.policy` - Policy-specific tests
- `@pytest.mark.property` - Property-based tests (slow)
- `@pytest.mark.fuzz` - Fuzz tests (slow)
- `@pytest.mark.slow` - Any slow-running test
- `@pytest.mark.concurrent` - Concurrent access tests
- `@pytest.mark.stress` - Stress tests

## Test Runner Options

The `run_tests.py` script provides several options:

```bash
# Quick tests (excludes slow property-based and fuzz tests)
python run_tests.py quick
python run_tests.py --test-type quick

# Full test suite with extended timeouts
python run_tests.py full
python run_tests.py --test-type full

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

# Complete test suite (runs tests sequentially)
python run_tests.py all
```

### Using Custom Pytest Configurations

The framework includes multiple pytest configurations:

1. **Default** (`pyproject.toml`): Standard configuration with 30s timeout
2. **Quick mode** (`pytest-quick.ini`): Excludes slow tests, 10s timeout
3. **Full mode** (`pytest-full.ini`): Includes all tests, 120s timeout

You can also run pytest directly with specific configurations:

```bash
# Run with quick configuration
uv run pytest -c pytest-quick.ini

# Run with full configuration  
uv run pytest -c pytest-full.ini

# Run specific test marks
uv run pytest -m "not slow"
```

## How It Works

### FUSE Process Management

The `FuseManager` class handles:
- Finding the mergerfs-rs binary (release or debug build)
- Creating temporary branch directories and mountpoints
- Mounting/unmounting FUSE filesystems with different policies
- Process lifecycle management and cleanup
- Context managers for safe test execution
- **Trace monitoring integration** for intelligent test synchronization

### External Testing Approach

Unlike unit tests, this framework:
- Spawns actual mergerfs-rs FUSE processes
- Performs real filesystem operations through the mounted filesystem
- Verifies behavior by examining the underlying branch directories
- Tests the complete integration stack including FUSE, policy logic, and filesystem operations
- **Monitors FUSE trace logs** to eliminate timing issues

### Test Fixtures

Key pytest fixtures:
- `fuse_manager`: Session-scoped FUSE process manager
- `temp_branches`: 3 temporary branch directories
- `temp_mountpoint`: Temporary mountpoint directory
- `fs_state`: Helper for examining filesystem state
- `policy`: Parametrized fixture for all policies
- `mounted_fs_with_trace`: Mounted filesystem with trace monitoring enabled
- `smart_wait`: Intelligent wait functions that monitor FUSE operations

### Trace-Based Testing

The framework includes advanced trace monitoring that:
- **Eliminates hardcoded sleep() calls** - Tests wait for actual operation completion
- **Improves test speed by 78%** - No unnecessary waiting
- **Increases reliability** - No more timing-related test failures
- **Provides debugging visibility** - See exactly what FUSE operations occurred

Example:
```python
# Old approach with sleep
file_path.write_text("content")
time.sleep(0.5)  # Arbitrary delay

# New trace-based approach
file_path.write_text("content")
assert smart_wait.wait_for_file_visible(file_path)  # Waits only as needed
```

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
- Enable trace monitoring with `FUSE_TRACE=1` for faster tests
- Increase timeout in pytest.ini if needed
- Use `--timeout=60` to set longer timeout
- Check for deadlocks in concurrent tests

### Timing Issues / Flaky Tests
```
Error: File not found / Operation not completed
```
**Solution**: 
- Use `mounted_fs_with_trace` fixture instead of `mounted_fs`
- Replace `time.sleep()` with `smart_wait` functions
- Enable trace monitoring: `FUSE_TRACE=1 pytest test_file.py`

### Permission Errors
```
Error: Permission denied
```
**Solution**:
- Ensure user can mount FUSE filesystems
- Check that temporary directories are writable
- On some systems, add user to `fuse` group

### Debugging Test Failures

Enable comprehensive debugging:
```bash
# Maximum debugging information
RUST_LOG=mergerfs_rs=debug FUSE_DEBUG=1 FUSE_TRACE_SUMMARY=1 uv run pytest failing_test.py -v -s

# See FUSE operations in real-time
RUST_LOG=mergerfs_rs=trace FUSE_TRACE=1 uv run pytest test_file.py -v
```