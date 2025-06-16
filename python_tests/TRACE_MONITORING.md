# FUSE Trace Monitoring Infrastructure

This document describes the enhanced Python test infrastructure that monitors FUSE trace logs in real-time to intelligently wait for operations instead of using hardcoded `sleep()` calls.

## Overview

The trace monitoring infrastructure provides:

1. **Real-time log parsing** - Captures and parses FUSE debug/trace logs as operations occur
2. **Intelligent waiting** - Wait for specific FUSE operations to complete rather than using arbitrary delays
3. **Operation tracking** - Track success/failure of operations with detailed information
4. **Performance insights** - Measure actual operation timing and identify bottlenecks

## Components

### FuseTraceMonitor

The core component that captures and parses FUSE logs in real-time:

```python
from lib.timing_utils import FuseTraceMonitor, OperationStatus

# Created automatically when trace is enabled
trace_monitor = FuseTraceMonitor(fuse_process)
trace_monitor.start_capture()

# Wait for specific operations
op = trace_monitor.wait_for_operation('create', path='/test.txt', timeout=2.0)
if op and op.status == OperationStatus.COMPLETED:
    print("File created successfully")

# Get operation statistics
create_count = trace_monitor.get_operation_count('create')
failed_ops = trace_monitor.get_failed_operations()
```

### SmartWaitHelper

High-level helper that provides common wait patterns:

```python
from lib.timing_utils import SmartWaitHelper

# Get helper from fixture
smart_wait = fuse_manager.get_smart_wait_helper(mountpoint)

# Common operations
smart_wait.wait_for_file_visible(filepath, timeout=2.0)
smart_wait.wait_for_write_complete(filepath, timeout=2.0)
smart_wait.wait_for_dir_visible(dirpath, timeout=2.0)
smart_wait.wait_for_deletion(path, timeout=2.0)
smart_wait.wait_for_xattr_operation(path, 'setxattr', timeout=2.0)
```

## Usage

### 1. Enable Trace Monitoring

Set the environment variable:
```bash
export FUSE_TRACE=1
pytest test_file.py
```

Or enable in code:
```python
config = FuseConfig(
    branches=branches,
    mountpoint=mountpoint,
    enable_trace=True  # Enable trace monitoring
)
```

### 2. Use Enhanced Fixtures

The test fixtures automatically support trace monitoring:

```python
def test_with_trace(mounted_fs_with_trace, smart_wait):
    """Test using trace monitoring."""
    process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
    
    # Create file
    test_file = mountpoint / "test.txt"
    test_file.write_text("content")
    
    # Wait intelligently instead of sleep()
    success = smart_wait.wait_for_file_visible(test_file)
    assert success
```

### 3. Traditional vs Trace-Based Approach

**Traditional approach (avoid this):**
```python
def test_traditional(mounted_fs):
    # Write file
    (mountpoint / "test.txt").write_text("content")
    
    # Hardcoded sleep - wasteful and unreliable!
    time.sleep(0.5)
    
    # Hope the operation completed...
    assert (mountpoint / "test.txt").exists()
```

**Trace-based approach (use this):**
```python
def test_traced(mounted_fs_with_trace, smart_wait):
    # Write file
    test_file = mountpoint / "test.txt"
    test_file.write_text("content")
    
    # Wait for actual completion - fast and reliable!
    smart_wait.wait_for_write_complete(test_file)
    
    # Guaranteed the operation completed
    assert test_file.exists()
```

## Benefits

1. **Faster Tests** - Operations complete as quickly as possible, no wasted time
2. **More Reliable** - Wait for actual completion, not arbitrary delays
3. **Better Debugging** - See exactly what FUSE operations occurred
4. **Error Detection** - Immediately identify failed operations
5. **Performance Analysis** - Track operation counts and timing

## Advanced Usage

### Waiting for Multiple Operations

```python
# Wait for multiple operations of the same type
ops = trace_monitor.wait_for_operations(['create'] * 5, timeout=3.0)

# Wait for different operations
ops = trace_monitor.wait_for_operations(['create', 'write', 'release'], timeout=3.0)
```

### Custom Operation Matching

```python
def check_large_write(op):
    return op.operation == 'write' and op.details.get('size', 0) > 1024

op = trace_monitor.wait_for_operation('write', check_fn=check_large_write)
```

### Operation Analysis

```python
# Get all completed operations
all_ops = trace_monitor.completed_operations

# Count by type
from collections import Counter
op_counts = Counter(op.operation for op in all_ops)
print(f"Operation counts: {dict(op_counts)}")

# Find slow operations
slow_ops = [op for op in all_ops if op.duration_ms and op.duration_ms > 100]
```

## Environment Variables

- `FUSE_TRACE=1` - Enable trace monitoring for all tests
- `FUSE_TRACE_SUMMARY=1` - Print operation summary on unmount
- `RUST_LOG=trace` - Set Rust log level (trace provides most detail)

## Troubleshooting

### Trace monitoring not available

If trace monitoring isn't working:

1. Ensure the Rust binary has trace logging compiled in
2. Check that `RUST_LOG=trace` is set
3. Verify stderr is being captured from the FUSE process

### Operations not being detected

1. Check the log format hasn't changed in the Rust code
2. Ensure operations are using the `tracing` spans correctly
3. Look at raw logs with `trace_monitor.get_logs()`

### Performance impact

Trace monitoring has minimal overhead, but for performance-critical tests:

1. Disable trace monitoring: `enable_trace=False`
2. Use traditional fixtures: `mounted_fs` instead of `mounted_fs_with_trace`
3. Set `RUST_LOG=info` to reduce log volume

## Migration Guide

To migrate existing tests:

1. Replace `time.sleep()` calls with appropriate wait functions
2. Add `smart_wait` fixture to test parameters
3. Use `mounted_fs_with_trace` for tests that benefit from tracing
4. Remove arbitrary delays after file operations

Example migration:

```python
# Before
def test_old(mounted_fs):
    (mountpoint / "file.txt").write_text("data")
    time.sleep(0.5)  # Bad!
    
# After  
def test_new(mounted_fs, smart_wait):
    file = mountpoint / "file.txt"
    file.write_text("data")
    smart_wait.wait_for_file_visible(file)  # Good!
```

## Best Practices

1. **Always use smart waits** instead of `time.sleep()` for FUSE operations
2. **Clear operations** before test sections with `trace_monitor.clear_completed()`
3. **Check for failures** with `trace_monitor.get_failed_operations()`
4. **Use appropriate timeouts** - most operations complete in < 100ms
5. **Enable trace selectively** - not all tests need trace monitoring