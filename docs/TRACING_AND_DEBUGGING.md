# Tracing and Debugging Guide

This guide covers the comprehensive tracing infrastructure in mergerfs-rs and how to use it for debugging and testing.

## Overview

mergerfs-rs uses the Rust `tracing` crate to provide structured, hierarchical logging throughout the FUSE implementation. This enables:

- Detailed debugging of FUSE operations
- Performance analysis and bottleneck identification
- Intelligent test synchronization (no more sleep() calls!)
- Production monitoring and troubleshooting

## Enabling Tracing

### Basic Usage

```bash
# Info level (basic operation logging)
RUST_LOG=mergerfs_rs=info mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Debug level (detailed operation flow)
RUST_LOG=mergerfs_rs=debug mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Trace level (very verbose, includes all operations)
RUST_LOG=mergerfs_rs=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2
```

### Module-Specific Tracing

```bash
# Debug FUSE operations, trace policy decisions
RUST_LOG=mergerfs_rs::fuse_fs=debug,mergerfs_rs::policy=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Focus on specific subsystems
RUST_LOG=mergerfs_rs::file_ops=debug,mergerfs_rs::xattr=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2
```

## Traced Operations

### FUSE Operations

All major FUSE operations include tracing spans:

| Operation | Traced Information |
|-----------|-------------------|
| `lookup` | Parent inode, filename, result |
| `getattr` | Inode, file metadata |
| `create` | Parent, filename, mode, policy decision, selected branch |
| `open` | Inode, flags, branch selection |
| `read` | Inode, offset, size, bytes read |
| `write` | Inode, offset, size, bytes written, branch |
| `mkdir` | Parent, dirname, mode, policy decision |
| `unlink` | Parent, filename, affected branches |
| `rmdir` | Parent, dirname, affected branches |
| `rename` | Old path, new path, strategy used |
| `chmod/chown` | Path, new permissions/ownership |
| `setxattr/getxattr` | Path, attribute name, value size |

### Policy Decisions

Policy evaluation is traced to show:
- Which policy was used (e.g., "mfs", "ff", "rand")
- Branch evaluation results
- Selected branch and reasoning
- Free space calculations

Example trace output:
```
DEBUG mergerfs_rs::policy::create::mfs: Evaluating branches for file creation
DEBUG mergerfs_rs::policy::create::mfs: Branch /mnt/disk1: 5.2 GB free
DEBUG mergerfs_rs::policy::create::mfs: Branch /mnt/disk2: 10.8 GB free
INFO mergerfs_rs::policy::create::mfs: Selected branch /mnt/disk2 (most free space)
```

## Using Tracing in Tests

### Python Test Integration

The Python test suite includes intelligent trace monitoring that eliminates timing issues:

```python
# Use the trace-aware fixtures
def test_file_operations(self, mounted_fs_with_trace, smart_wait):
    process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
    
    # Create a file
    test_file = mountpoint / "test.txt"
    test_file.write_text("content")
    
    # Wait for the operation to complete (no sleep needed!)
    assert smart_wait.wait_for_file_visible(test_file)
```

### Available Wait Functions

| Function | Purpose |
|----------|---------|
| `wait_for_file_visible(path)` | Wait for file creation to complete |
| `wait_for_write_complete(path)` | Wait for write operation to finish |
| `wait_for_dir_visible(path)` | Wait for directory creation |
| `wait_for_deletion(path)` | Wait for file/dir deletion |
| `wait_for_xattr_operation(path, op)` | Wait for xattr operation |

### Running Tests with Tracing

```bash
# Enable trace monitoring (recommended)
FUSE_TRACE=1 uv run pytest test_file.py -v

# Debug failing tests
RUST_LOG=mergerfs_rs=debug FUSE_DEBUG=1 uv run pytest -v -s

# Get operation summary after tests
FUSE_TRACE_SUMMARY=1 uv run pytest test_file.py
```

## Performance Analysis

### Timing Analysis

At trace level, operations include timing information:

```
TRACE fuse::write{inode=42 fh=1 offset=0 size=4096} enter
DEBUG Writing 4096 bytes to branch /mnt/disk1/data/file.txt
TRACE fuse::write{inode=42 fh=1 offset=0 size=4096} exit duration=1.2ms
```

### Identifying Bottlenecks

Use tracing to identify slow operations:

```bash
# Capture trace output
RUST_LOG=mergerfs_rs=trace mergerfs /mnt/union /mnt/disk1 /mnt/disk2 2> trace.log

# Analyze slow operations
grep "duration=" trace.log | awk -F'duration=' '{print $2}' | sort -rn | head -20
```

## Debugging Common Issues

### File Not Found

Enable lookup tracing to see search patterns:
```bash
RUST_LOG=mergerfs_rs::fuse_fs=debug,mergerfs_rs::policy::search=trace
```

### Permission Denied

Trace metadata operations:
```bash
RUST_LOG=mergerfs_rs::metadata_ops=debug,mergerfs_rs::permissions=trace
```

### Policy Not Working as Expected

Debug policy evaluation:
```bash
RUST_LOG=mergerfs_rs::policy=trace
```

### Race Conditions in Tests

Use trace monitoring to ensure operations complete:
```python
# Instead of guessing with sleep()
file.write_text("data")
time.sleep(0.5)  # Bad!

# Use trace-based waiting
file.write_text("data")
assert smart_wait.wait_for_write_complete(file)  # Good!
```

## Advanced Tracing Features

### Custom Trace Filtering

Create a custom filter for specific scenarios:

```bash
# Only show errors and specific operations
RUST_LOG="error,mergerfs_rs::fuse_fs::create=debug,mergerfs_rs::fuse_fs::write=debug"

# Exclude noisy modules
RUST_LOG="mergerfs_rs=debug,mergerfs_rs::fuse_fs::readdir=warn"
```

### Integration with External Tools

The structured output works with log analysis tools:

```bash
# JSON output for processing
RUST_LOG=mergerfs_rs=debug mergerfs /mnt/union /mnt/disk1 /mnt/disk2 2>&1 | jq
```

## Best Practices

1. **Development**: Use `debug` level for general development
2. **Testing**: Enable `FUSE_TRACE=1` for all test runs
3. **Production**: Use `info` level, increase to `debug` for issues
4. **Performance Testing**: Use `trace` level to capture timing data
5. **CI/CD**: Run tests with `FUSE_TRACE=1` for better reliability

## Troubleshooting

### No Trace Output

1. Ensure `RUST_LOG` is set correctly
2. Check that stderr is not redirected
3. Verify the binary was built with tracing enabled

### Too Much Output

1. Use module-specific filters
2. Redirect to a file and grep for specific patterns
3. Use `warn` or `error` level for specific modules

### Test Timing Issues

1. Always use `mounted_fs_with_trace` fixture
2. Replace all `sleep()` calls with `smart_wait` functions
3. Check trace logs to understand operation order

## Future Enhancements

- Structured JSON logging for easier parsing
- OpenTelemetry integration for distributed tracing
- Performance profiling integration
- Real-time monitoring dashboard