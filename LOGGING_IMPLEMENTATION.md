# Logging and Tracing Implementation

## Overview

This document describes the comprehensive logging and tracing implementation added to mergerfs-rs to diagnose timing issues and improve test reliability.

## Implementation Details

### Rust Implementation

1. **Tracing Initialization** (`src/main.rs`)
   - Uses `tracing_subscriber` with `env_filter` feature
   - Configurable via `RUST_LOG` environment variable
   - Default log level: `info`
   - Includes target, thread IDs, line numbers, and file information

2. **FUSE Operation Tracing** (`src/fuse_fs.rs`)
   - Added tracing spans to all major operations:
     - `fuse::lookup` - File/directory lookups
     - `fuse::getattr` - Get file attributes
     - `fuse::open` - File open operations
     - `fuse::read` - File read operations
     - `fuse::write` - File write operations
     - `fuse::create` - File creation
     - `fuse::readdir` - Directory listing
   - Each span includes relevant parameters (inode, path, size, etc.)

3. **Policy Tracing**
   - **MFS Policy** (`src/policy/create/most_free_space.rs`)
     - Logs branch evaluation with free space information
     - Reports selected branch and available space
     - Warns when no writable branches found
   - **File Operations** (`src/file_ops.rs`)
     - Logs file creation with full path details
     - Traces write operations with offset and size

4. **Metadata Operations** (`src/metadata_ops.rs`)
   - Traces chmod operations across branches
   - Logs branch selection and failures

### Python Test Infrastructure

1. **Timing Utilities** (`python_tests/lib/timing_utils.py`)
   - `FuseLogCapture` - Captures FUSE debug logs from stderr
   - `TimingAnalyzer` - Analyzes operation timings
   - `wait_for_operation` - Replaces sleep() with intelligent polling
   - Performance reporting capabilities

2. **FuseManager Updates** (`python_tests/lib/fuse_manager.py`)
   - Reduced mount wait from 0.5s to 0.1s
   - Intelligent polling with 0.05s intervals
   - Optional log capture for debug sessions
   - Environment variable support for log levels

3. **Test Configuration** (`python_tests/pytest.ini`)
   - Default RUST_LOG=info for all tests
   - 30-second timeout for slow operations
   - Custom markers for test categorization

## Usage

### Running with Debug Logging

```bash
# Run specific test with debug logging
RUST_LOG=debug pytest test_file.py -v

# Run with trace logging (very verbose)
RUST_LOG=trace cargo run -- /mnt/point /branch1 /branch2

# Enable FUSE debug log capture in tests
FUSE_DEBUG=1 RUST_LOG=debug pytest test_file.py
```

### Example Log Output

```
2024-06-16T10:30:45.123Z DEBUG fuse::create{parent=1 name="test.txt"} mergerfs_rs::fuse_fs: Starting create
2024-06-16T10:30:45.124Z DEBUG mfs::select_branch{path="test.txt"} mergerfs_rs::policy::create::most_free_space: Evaluating 3 branches
2024-06-16T10:30:45.125Z DEBUG mergerfs_rs::policy::create::most_free_space: Branch "/branch1" has 5000000000 bytes available
2024-06-16T10:30:45.126Z INFO mergerfs_rs::policy::create::most_free_space: MFS policy selected branch "/branch1" with 5000000000 bytes free
```

## Performance Improvements

1. **Reduced Sleep Times**
   - Mount wait: 0.5s → 0.1s
   - Polling interval: 0.1s → 0.05s
   - Removed artificial delays in concurrent tests

2. **Test Execution Time**
   - Concurrent test example: ~2s → 0.36s
   - MFS policy tests: ~30s → ~28s
   - Overall test suite: Noticeably faster

## Benefits

1. **Debugging**
   - Clear visibility into FUSE operation flow
   - Policy decision transparency
   - Performance bottleneck identification

2. **Test Reliability**
   - No more guessing with sleep() durations
   - Intelligent waiting for operations
   - Better understanding of timing issues

3. **Performance Analysis**
   - Operation timing metrics
   - Slow operation detection
   - Branch selection patterns

## Future Enhancements

1. Add structured logging with JSON output option
2. Create Grafana/Prometheus metrics export
3. Add operation correlation IDs for request tracking
4. Implement log sampling for high-volume operations
5. Add performance regression detection in CI