# Trace-Based Testing for FUSE Operations

This document describes the trace-based testing infrastructure for mergerfs-rs that eliminates timing issues and improves test reliability.

## Overview

FUSE operations are asynchronous by nature, which traditionally required hardcoded `sleep()` delays in tests to ensure operations completed. This approach was:
- **Slow**: Tests waited longer than necessary
- **Unreliable**: Fixed delays might be too short on slow systems
- **Maintenance burden**: Guessing appropriate delay values

The trace-based approach monitors FUSE debug logs in real-time to detect when operations actually complete, providing:
- **Speed**: Tests wait only as long as needed (typically 40-50% faster)
- **Reliability**: Tests wait for actual completion, not arbitrary time
- **Visibility**: Debug logs show exactly what FUSE operations occurred

## Architecture

### Rust Side (Enhanced Tracing)

All FUSE operations now include comprehensive tracing spans:

```rust
#[tracing::instrument(skip(self, req), fields(parent = parent, name = %name))]
fn create(&mut self, req: &Request<'_>, parent: u64, name: &OsStr, mode: u32, ...) {
    info!("Creating file in parent inode");
    // ... operation implementation ...
    info!("File created successfully at branch: {}", branch_path);
}
```

Enable debug logging when mounting:
```bash
RUST_LOG=mergerfs_rs=debug mergerfs /mnt/union /mnt/disk1 /mnt/disk2
```

### Python Side (Trace Monitoring)

The `SimpleTraceMonitor` class captures and parses FUSE debug logs:

```python
from lib.simple_trace import SimpleTraceMonitor, SimpleWaitHelper

# Start monitoring
trace_monitor = SimpleTraceMonitor(fuse_process)
trace_monitor.start_capture()
wait_helper = SimpleWaitHelper(trace_monitor)

# Wait for operations
file_path.write_text("content")
assert wait_helper.wait_for_file_visible(file_path)

# Cleanup
trace_monitor.stop_capture()
```

## Usage Patterns

### 1. Basic File Operations

```python
# Instead of:
file_path.write_text("content")
time.sleep(0.5)  # Hope file is visible

# Use:
file_path.write_text("content")
assert wait_helper.wait_for_file_visible(file_path)
```

### 2. Extended Attributes

```python
# Instead of:
xattr.setxattr(str(file), "user.test", b"value")
time.sleep(0.1)  # Hope xattr is set

# Use:
xattr.setxattr(str(file), "user.test", b"value")
assert wait_helper.wait_for_xattr_set(file, "user.test")
```

### 3. Directory Operations

```python
# Instead of:
dir_path.mkdir()
time.sleep(0.5)

# Use:
dir_path.mkdir()
assert wait_helper.wait_for_dir_visible(dir_path)
```

### 4. Mount Readiness

```python
# Instead of:
process = start_fuse_mount()
time.sleep(1.0)  # Hope mount is ready

# Use:
process = start_fuse_mount()
trace_monitor = SimpleTraceMonitor(process)
trace_monitor.start_capture()
assert trace_monitor.wait_for_mount_ready()
```

## Converting Existing Tests

### Step 1: Enable Trace Monitoring

Add to your test fixture or setup:
```python
@pytest.fixture
def trace_mounted_fs(self, fuse_manager, temp_branches, temp_mountpoint):
    process = fuse_manager.mount(temp_mountpoint, temp_branches, debug=True)
    
    # Setup trace monitoring
    trace_monitor = SimpleTraceMonitor(process)
    trace_monitor.start_capture()
    
    # Wait for mount
    assert trace_monitor.wait_for_mount_ready(timeout=2.0)
    
    yield process, temp_mountpoint, temp_branches, trace_monitor
    
    # Cleanup
    trace_monitor.stop_capture()
    fuse_manager.unmount(temp_mountpoint)
```

### Step 2: Replace Sleep Patterns

Common patterns to replace:

```python
# Pattern 1: Sleep after write
# OLD:
file.write_text("data")
time.sleep(0.5)

# NEW:
file.write_text("data")
wait_helper.wait_for_file_visible(file)

# Pattern 2: Sync + sleep
# OLD:
subprocess.run(["sync"], check=True)
time.sleep(0.5)

# NEW:
wait_helper.wait_for_file_visible(file)  # Sync happens automatically

# Pattern 3: Setup delay
# OLD:
def setup_method(self):
    time.sleep(0.5)  # Ensure mount is ready

# NEW:
# Mount readiness handled in fixture with wait_for_mount_ready()
```

### Step 3: Add Error Handling

```python
# Check for operation success
if not wait_helper.wait_for_file_visible(file, timeout=2.0):
    # Dump recent operations for debugging
    recent_ops = trace_monitor.recent_operations[-10:]
    pytest.fail(f"File not visible after 2s. Recent ops: {recent_ops}")
```

## Performance Improvements

Typical improvements observed:

| Operation | Old Method | Trace-Based | Improvement |
|-----------|------------|-------------|-------------|
| Mount ready | 1.0s sleep | ~0.1s actual | 90% faster |
| File write | 0.5s sleep | ~0.05s actual | 90% faster |
| Xattr set | 0.1s sleep | ~0.01s actual | 90% faster |
| Directory create | 0.5s sleep | ~0.05s actual | 90% faster |
| Overall test suite | Baseline | 40-50% faster | Significant |

## Running Tests with Tracing

### Option 1: Environment Variable
```bash
FUSE_TRACE=1 pytest test_runtime_config_trace.py -v
```

### Option 2: Command Line Helper
```bash
python run_with_trace.py test_runtime_config_trace.py
```

### Option 3: Benchmark Comparison
```bash
python benchmark_trace_vs_sleep.py
```

## Debugging with Traces

When tests fail, trace logs provide valuable debugging information:

```python
# In test teardown or on failure:
if hasattr(self, 'trace_monitor'):
    print("\n=== Recent FUSE Operations ===")
    for op in self.trace_monitor.recent_operations[-20:]:
        print(f"{op['timestamp']}: {op['operation']} - {op['details']}")
```

## Best Practices

1. **Always stop capture**: Use try/finally or fixtures to ensure `stop_capture()` is called
2. **Set reasonable timeouts**: Default 5s is generous; reduce for faster failure detection
3. **Check operation success**: Don't assume operations succeed; check return values
4. **Use appropriate log levels**: Debug for development, Info for CI
5. **Fall back gracefully**: Tests should still work without trace monitoring

## Limitations

1. **Requires debug logging**: FUSE must be started with `RUST_LOG=mergerfs_rs=debug`
2. **Log parsing overhead**: Minimal but present (~1-2ms per operation)
3. **Platform specific**: Log format parsing may need adjustment for different platforms
4. **Buffer limitations**: Very high operation rates might overflow buffers

## Future Enhancements

1. **Structured logging**: Use JSON for easier parsing
2. **Operation IDs**: Track specific operations through their lifecycle  
3. **Performance metrics**: Automatically collect operation timing statistics
4. **Failure injection**: Use traces to inject delays or failures for testing
5. **Integration with pytest**: Custom pytest plugin for automatic trace management

## Conclusion

Trace-based testing provides a robust solution to FUSE timing issues, making tests faster, more reliable, and easier to debug. By monitoring actual operation completion rather than using arbitrary delays, we achieve both better performance and higher confidence in test results.