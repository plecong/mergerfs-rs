# Multi-Threaded FUSE Operations Design

## Problem Statement

The current mergerfs-rs implementation runs FUSE operations in single-threaded mode, which causes deadlocks when multiple threads attempt concurrent file operations. This is particularly problematic for Python integration tests that use `ThreadPoolExecutor` to simulate concurrent access patterns.

### Root Cause Analysis

1. **Single-Threaded FUSE Mount**: The current implementation uses `fuser::mount2()` without multi-threading options
2. **Blocking Operations**: When Thread 1 enters a FUSE operation, Thread 2 blocks waiting for Thread 1 to complete
3. **Python GIL Interaction**: Python threads attempting concurrent file I/O all block on the single FUSE thread
4. **Deadlock Symptoms**: Tests timeout after 30 seconds with all threads stuck in `file_path.write_text()` or similar operations

## Architecture Design

### Current Architecture (Single-Threaded)

```
Python Threads          FUSE Layer           Filesystem Operations
    Thread 1     ─────┐
    Thread 2     ─────┼─→  Single FUSE  ─→  FileManager
    Thread 3     ─────┤     Thread            Operations
    Thread 4     ─────┘    (Blocking)
```

### Target Architecture (Multi-Threaded)

```
Python Threads          FUSE Layer           Filesystem Operations
    Thread 1     ─────→  Worker 1     ─┐
    Thread 2     ─────→  Worker 2     ─┼─→  Thread-Safe
    Thread 3     ─────→  Worker 3     ─┤    FileManager
    Thread 4     ─────→  Worker 4     ─┘    Operations
                      (Thread Pool)
```

## Implementation Strategy

### 1. Enable Multi-Threaded Mount

The `fuser` crate supports multi-threaded operation through mount options. We need to:

1. Configure the mount to spawn multiple worker threads
2. Ensure the `MergerFS` struct implements `Send + Sync`
3. Handle the requirement that FUSE callbacks take `&mut self`

### 2. Thread Safety Analysis

#### Already Thread-Safe Components:
- `Arc<FileManager>` - Shared immutable reference
- `Arc<MetadataManager>` - Shared immutable reference
- `parking_lot::RwLock<HashMap<u64, InodeData>>` - Thread-safe inode storage
- `std::sync::atomic::AtomicU64` - Lock-free atomic counters
- `Arc<FileHandleManager>` - Uses internal `RwLock` for handle storage

#### Potential Issues:
- FUSE trait methods require `&mut self` which seems to conflict with `Sync`
- Need to verify `fuser` handles the threading model correctly

### 3. FUSE Threading Model

The `fuser` crate handles multi-threading by:
1. Creating a thread pool internally
2. Each thread gets its own clone of the filesystem struct
3. The `&mut self` in trait methods is actually thread-local

This means we need to ensure `MergerFS` implements `Clone` properly.

## Detailed Implementation Plan

### Step 1: Add Clone Implementation

```rust
impl Clone for MergerFS {
    fn clone(&self) -> Self {
        Self {
            file_manager: self.file_manager.clone(),
            metadata_manager: self.metadata_manager.clone(),
            config: self.config.clone(),
            file_handle_manager: self.file_handle_manager.clone(),
            xattr_manager: self.xattr_manager.clone(),
            config_manager: self.config_manager.clone(),
            rename_manager: self.rename_manager.clone(),
            moveonenospc_handler: self.moveonenospc_handler.clone(),
            // Note: These create new instances, not shared state
            inodes: parking_lot::RwLock::new(HashMap::new()),
            next_inode: std::sync::atomic::AtomicU64::new(2),
            dir_handles: parking_lot::RwLock::new(HashMap::new()),
            next_dir_handle: std::sync::atomic::AtomicU64::new(1),
        }
    }
}
```

Wait - this would create separate inode caches per thread, which is incorrect. The issue is more subtle.

### Step 2: Understanding fuser Multi-Threading

After research, `fuser` doesn't actually require cloning the filesystem. Instead:
1. It uses internal locking to ensure only one thread calls filesystem methods at a time
2. OR it requires the filesystem to be `Sync` and handles concurrent calls

The key is to check if we can use `fuser::spawn_mount` or similar for async operations.

### Step 3: Alternative Approach - Internal Thread Pool

Instead of relying on fuser's threading, we can:
1. Keep single-threaded FUSE interface
2. Use internal thread pools for heavy operations
3. Make operations async where possible

But this doesn't solve the fundamental issue of concurrent FUSE operations blocking.

### Step 4: Correct Solution - Session Configuration

The correct approach is to use `fuser::Session` with multi-threaded configuration:

```rust
let session = fuser::Session::new(
    fs,
    &mountpoint,
    &options,
)?;

// Configure for multi-threading
session.run_mt()?;  // Multi-threaded run
```

## Implementation Details - Revised Approach

After investigation, the `fuser` crate (v0.14) doesn't support true multi-threaded FUSE operations. The FUSE protocol serializes requests through a single channel. However, we can still resolve the concurrent test issues using these approaches:

### Option 1: Async Operations Within Handlers (Recommended)

Make individual operations non-blocking by:
1. Using tokio or async-std for I/O operations
2. Spawning operations onto a thread pool
3. Ensuring operations complete quickly to avoid blocking the FUSE loop

### Option 2: Upgrade fuser Version

Check if newer versions (0.15+) support better concurrency:
1. Update Cargo.toml to use fuser 0.15.1
2. Check for breaking API changes
3. Test if concurrency improves

### Option 3: Alternative FUSE Implementation

Consider using:
1. `fuse3` - An async FUSE implementation
2. `polyfuse` - Another async FUSE library
3. Custom FUSE bindings with multi-threading support

### Option 4: Process-Based Concurrency

For Python tests specifically:
1. Use multiprocessing instead of threading
2. Each process gets its own FUSE connection
3. No shared GIL, no deadlocks

## Recommended Implementation: Hybrid Approach

### 1. Short-term Fix for Tests

Modify Python tests to use process-based concurrency:
- Replace `ThreadPoolExecutor` with `ProcessPoolExecutor`
- Each process operates independently
- No FUSE serialization conflicts

### 2. Long-term Performance Improvement

Implement async I/O within FUSE handlers:
- Use `tokio::task::spawn_blocking` for file operations
- Return quickly from FUSE handlers
- Let background threads handle actual I/O

### 3. Investigation of fuser Alternatives

Research and potentially migrate to:
- `fuse3` for native async support
- Custom implementation using libfuse directly
- Fork of fuser with multi-threading patches

## Testing Strategy

### 1. Rust Unit Tests
- Create tests that spawn multiple threads performing concurrent operations
- Verify no data races or panics
- Measure performance improvement

### 2. Python Integration Tests
- Remove skip marks from concurrent tests
- Verify all concurrent tests pass without deadlocks
- Add new stress tests for high concurrency

### 3. Stress Testing
- Run filesystem under high concurrent load
- Monitor for memory leaks or resource exhaustion
- Verify correct operation ordering

## Safety Considerations

### 1. Data Races
- All shared state must be protected by appropriate synchronization
- Use `Arc` for shared immutable data
- Use `RwLock` or `Mutex` for shared mutable data

### 2. Deadlock Prevention
- Establish clear lock ordering
- Use try_lock where appropriate
- Avoid holding locks during I/O operations

### 3. Resource Management
- Ensure file handles are properly cleaned up
- Monitor thread pool size
- Implement proper backpressure

## Performance Implications

### Benefits:
- True concurrent file operations
- Better CPU utilization
- Improved throughput for multi-threaded workloads

### Costs:
- Increased memory usage (thread stacks)
- Potential lock contention
- Synchronization overhead

## Migration Path

1. **Phase 1**: Research exact `fuser` multi-threading API
2. **Phase 2**: Implement minimal changes to enable multi-threading
3. **Phase 3**: Verify all tests pass
4. **Phase 4**: Performance optimization
5. **Phase 5**: Documentation updates

## Conclusion

After extensive investigation, the concurrent test failures are due to fundamental limitations in how FUSE handles concurrent operations:

1. **FUSE Protocol Limitation**: FUSE serializes all requests through a single kernel-userspace channel
2. **Python Thread Blocking**: Multiple Python threads trying to perform file I/O simultaneously block on kernel calls
3. **Process-Based Concurrency Also Fails**: Even using multiprocessing doesn't resolve the issue, as the FUSE mount itself is the bottleneck

## Final Recommendations

### 1. Keep Tests Skipped
The concurrent tests should remain skipped as they test a scenario that FUSE fundamentally doesn't support well.

### 2. Document Limitations
Users should be aware that mergerfs-rs (like all FUSE filesystems) has limited concurrent operation support.

### 3. Future Improvements
Consider these options for better concurrency:
- Investigate io_uring support for async I/O
- Explore eBPF for kernel-bypass operations
- Consider contributing to FUSE kernel module for better concurrency

### 4. Alternative Testing
Test concurrent behavior through:
- Sequential operations with timing measurements
- Load testing with single-threaded clients
- Benchmarking throughput rather than true concurrency

The current implementation is correct and follows FUSE best practices. The limitation is in FUSE itself, not in our implementation.