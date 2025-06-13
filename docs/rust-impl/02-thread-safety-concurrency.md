# Thread Safety and Concurrency Patterns in Rust

## Overview

This guide provides comprehensive approaches for implementing the thread safety and concurrency patterns from mergerfs in Rust, leveraging Rust's ownership system, async/await, and safe concurrency primitives to achieve high performance while maintaining safety.

## Core Concurrency Architecture

### Configuration Access Patterns

#### RAII Configuration Guards

```rust
use std::sync::Arc;
use parking_lot::{RwLock, RwLockReadGuard, RwLockWriteGuard};

pub struct Config {
    // All configuration fields here
    pub branches: Arc<RwLock<Vec<Arc<Branch>>>>,
    pub function_policies: FunctionPolicies,
    pub cache_settings: CacheSettings,
    pub fuse_settings: FuseSettings,
    // ... other config fields
}

// RAII guards that automatically handle locking
pub struct ConfigReadGuard<'a> {
    _guard: RwLockReadGuard<'a, Config>,
}

impl<'a> ConfigReadGuard<'a> {
    pub fn new(config: &'a RwLock<Config>) -> Self {
        Self {
            _guard: config.read(),
        }
    }
    
    pub fn get(&self) -> &Config {
        &*self._guard
    }
}

pub struct ConfigWriteGuard<'a> {
    _guard: RwLockWriteGuard<'a, Config>,
}

impl<'a> ConfigWriteGuard<'a> {
    pub fn new(config: &'a RwLock<Config>) -> Self {
        Self {
            _guard: config.write(),
        }
    }
    
    pub fn get_mut(&mut self) -> &mut Config {
        &mut *self._guard
    }
}

// Global configuration with safe access
pub struct ConfigManager {
    config: Arc<RwLock<Config>>,
}

impl ConfigManager {
    pub fn new(config: Config) -> Self {
        Self {
            config: Arc::new(RwLock::new(config)),
        }
    }
    
    pub fn read(&self) -> ConfigReadGuard {
        ConfigReadGuard::new(&self.config)
    }
    
    pub fn write(&self) -> ConfigWriteGuard {
        ConfigWriteGuard::new(&self.config)
    }
    
    // Convenience method for common read operations
    pub fn with_config<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&Config) -> R,
    {
        let guard = self.read();
        f(guard.get())
    }
    
    // Convenience method for config updates
    pub fn update_config<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&mut Config) -> R,
    {
        let mut guard = self.write();
        f(guard.get_mut())
    }
}

// Global instance
use std::sync::OnceLock;
static CONFIG_MANAGER: OnceLock<ConfigManager> = OnceLock::new();

pub fn get_config_manager() -> &'static ConfigManager {
    CONFIG_MANAGER.get().expect("Config manager not initialized")
}

pub fn init_config_manager(config: Config) {
    CONFIG_MANAGER.set(ConfigManager::new(config))
        .expect("Config manager already initialized");
}
```

### Branch Management with Atomic Updates

#### Lock-Free Branch Access

```rust
use std::sync::Arc;
use parking_lot::RwLock;

#[derive(Clone)]
pub struct BranchCollection {
    branches: Arc<Vec<Arc<Branch>>>,
}

impl BranchCollection {
    pub fn new(branches: Vec<Arc<Branch>>) -> Self {
        Self {
            branches: Arc::new(branches),
        }
    }
    
    pub fn iter(&self) -> impl Iterator<Item = &Arc<Branch>> {
        self.branches.iter()
    }
    
    pub fn len(&self) -> usize {
        self.branches.len()
    }
    
    pub fn get(&self, index: usize) -> Option<&Arc<Branch>> {
        self.branches.get(index)
    }
    
    pub fn to_vec(&self) -> Vec<Arc<Branch>> {
        self.branches.iter().cloned().collect()
    }
}

pub struct BranchManager {
    current: Arc<RwLock<BranchCollection>>,
}

impl BranchManager {
    pub fn new(branches: Vec<Arc<Branch>>) -> Self {
        Self {
            current: Arc::new(RwLock::new(BranchCollection::new(branches))),
        }
    }
    
    // Lock-free read access - creates snapshot
    pub fn get_branches(&self) -> BranchCollection {
        self.current.read().clone()
    }
    
    // Atomic update with new branch collection
    pub fn update_branches(&self, new_branches: Vec<Arc<Branch>>) {
        let new_collection = BranchCollection::new(new_branches);
        *self.current.write() = new_collection;
    }
    
    // Add branch atomically
    pub fn add_branch(&self, branch: Arc<Branch>) {
        let mut guard = self.current.write();
        let mut new_branches = guard.to_vec();
        new_branches.push(branch);
        *guard = BranchCollection::new(new_branches);
    }
    
    // Remove branch atomically
    pub fn remove_branch(&self, path: &std::path::Path) {
        let mut guard = self.current.write();
        let new_branches: Vec<_> = guard.to_vec()
            .into_iter()
            .filter(|b| b.path != path)
            .collect();
        *guard = BranchCollection::new(new_branches);
    }
}
```

### File Handle Management

#### Per-File Synchronization

```rust
use std::collections::HashMap;
use std::os::unix::io::RawFd;
use parking_lot::Mutex;
use std::sync::Arc;

#[derive(Debug)]
pub struct FileHandle {
    pub fd: RawFd,
    pub branch: Arc<Branch>,
    pub path: std::path::PathBuf,
    pub flags: i32,
    pub direct_io: bool,
    
    // Per-file mutex for thread safety
    mutex: Mutex<()>,
}

impl FileHandle {
    pub fn new(
        fd: RawFd,
        branch: Arc<Branch>,
        path: std::path::PathBuf,
        flags: i32,
        direct_io: bool,
    ) -> Self {
        Self {
            fd,
            branch,
            path,
            flags,
            direct_io,
            mutex: Mutex::new(()),
        }
    }
    
    // Acquire exclusive access to this file
    pub fn lock(&self) -> parking_lot::MutexGuard<()> {
        self.mutex.lock()
    }
    
    // Try to acquire non-blocking access
    pub fn try_lock(&self) -> Option<parking_lot::MutexGuard<()>> {
        self.mutex.try_lock()
    }
}

impl Drop for FileHandle {
    fn drop(&mut self) {
        // Ensure file is closed when handle is dropped
        unsafe {
            libc::close(self.fd);
        }
    }
}

// File handle registry for managing open files
pub struct FileHandleRegistry {
    handles: Arc<RwLock<HashMap<u64, Arc<FileHandle>>>>,
    next_id: Arc<parking_lot::Mutex<u64>>,
}

impl FileHandleRegistry {
    pub fn new() -> Self {
        Self {
            handles: Arc::new(RwLock::new(HashMap::new())),
            next_id: Arc::new(parking_lot::Mutex::new(1)),
        }
    }
    
    pub fn register(&self, handle: FileHandle) -> u64 {
        let id = {
            let mut next_id = self.next_id.lock();
            let id = *next_id;
            *next_id += 1;
            id
        };
        
        let handle = Arc::new(handle);
        self.handles.write().insert(id, handle);
        id
    }
    
    pub fn get(&self, id: u64) -> Option<Arc<FileHandle>> {
        self.handles.read().get(&id).cloned()
    }
    
    pub fn remove(&self, id: u64) -> Option<Arc<FileHandle>> {
        self.handles.write().remove(&id)
    }
    
    pub fn with_handle<F, R>(&self, id: u64, f: F) -> Option<R>
    where
        F: FnOnce(&FileHandle) -> R,
    {
        self.get(id).map(|handle| f(&handle))
    }
}
```

## Async/Await Integration

### Async FUSE Operations

```rust
use tokio::task;
use std::future::Future;
use std::pin::Pin;

pub type AsyncResult<T> = Pin<Box<dyn Future<Output = Result<T, std::io::Error>> + Send>>;

pub trait AsyncFileOperations {
    fn async_read(
        &self,
        handle_id: u64,
        offset: u64,
        size: usize,
    ) -> AsyncResult<Vec<u8>>;
    
    fn async_write(
        &self,
        handle_id: u64,
        offset: u64,
        data: Vec<u8>,
    ) -> AsyncResult<usize>;
    
    fn async_create(
        &self,
        path: &std::path::Path,
        mode: u32,
    ) -> AsyncResult<u64>; // Returns handle ID
}

pub struct AsyncFilesystem {
    config_manager: Arc<ConfigManager>,
    branch_manager: Arc<BranchManager>,
    file_registry: Arc<FileHandleRegistry>,
    policy_executor: Arc<PolicyExecutor>,
}

impl AsyncFilesystem {
    pub fn new(
        config: Config,
        branches: Vec<Arc<Branch>>,
    ) -> Self {
        let config_manager = Arc::new(ConfigManager::new(config));
        let branch_manager = Arc::new(BranchManager::new(branches));
        let file_registry = Arc::new(FileHandleRegistry::new());
        let policy_executor = Arc::new(PolicyExecutor::new(
            config_manager.clone(),
            branch_manager.clone(),
        ));
        
        Self {
            config_manager,
            branch_manager,
            file_registry,
            policy_executor,
        }
    }
}

impl AsyncFileOperations for AsyncFilesystem {
    fn async_read(
        &self,
        handle_id: u64,
        offset: u64,
        size: usize,
    ) -> AsyncResult<Vec<u8>> {
        let file_registry = self.file_registry.clone();
        
        Box::pin(async move {
            let handle = file_registry
                .get(handle_id)
                .ok_or_else(|| std::io::Error::from_raw_os_error(libc::EBADF))?;
            
            // Perform I/O operation in blocking thread pool
            let result = task::spawn_blocking(move || {
                let _lock = handle.lock(); // Acquire per-file lock
                
                let mut buffer = vec![0u8; size];
                let bytes_read = unsafe {
                    libc::pread(
                        handle.fd,
                        buffer.as_mut_ptr() as *mut libc::c_void,
                        size,
                        offset as libc::off_t,
                    )
                };
                
                if bytes_read < 0 {
                    Err(std::io::Error::last_os_error())
                } else {
                    buffer.truncate(bytes_read as usize);
                    Ok(buffer)
                }
            }).await;
            
            result.map_err(|_| std::io::Error::from_raw_os_error(libc::EIO))?
        })
    }
    
    fn async_write(
        &self,
        handle_id: u64,
        offset: u64,
        data: Vec<u8>,
    ) -> AsyncResult<usize> {
        let file_registry = self.file_registry.clone();
        
        Box::pin(async move {
            let handle = file_registry
                .get(handle_id)
                .ok_or_else(|| std::io::Error::from_raw_os_error(libc::EBADF))?;
            
            task::spawn_blocking(move || {
                let _lock = handle.lock(); // Acquire per-file lock
                
                let bytes_written = unsafe {
                    libc::pwrite(
                        handle.fd,
                        data.as_ptr() as *const libc::c_void,
                        data.len(),
                        offset as libc::off_t,
                    )
                };
                
                if bytes_written < 0 {
                    Err(std::io::Error::last_os_error())
                } else {
                    Ok(bytes_written as usize)
                }
            }).await
            .map_err(|_| std::io::Error::from_raw_os_error(libc::EIO))?
        })
    }
    
    fn async_create(
        &self,
        path: &std::path::Path,
        mode: u32,
    ) -> AsyncResult<u64> {
        let policy_executor = self.policy_executor.clone();
        let file_registry = self.file_registry.clone();
        let path = path.to_path_buf();
        
        Box::pin(async move {
            // Execute policy to select branches
            let branches = policy_executor
                .select_create_branches(&path)
                .await
                .map_err(|e| std::io::Error::from_raw_os_error(e.errno()))?;
            
            // Create file on selected branch
            let branch = branches.into_iter().next()
                .ok_or_else(|| std::io::Error::from_raw_os_error(libc::ENOENT))?;
            
            let full_path = branch.path.join(&path);
            
            let (fd, branch_ref) = task::spawn_blocking(move || {
                let fd = unsafe {
                    let path_cstr = std::ffi::CString::new(
                        full_path.to_string_lossy().as_ref()
                    )?;
                    
                    libc::open(
                        path_cstr.as_ptr(),
                        libc::O_CREAT | libc::O_WRONLY | libc::O_TRUNC,
                        mode,
                    )
                };
                
                if fd < 0 {
                    Err(std::io::Error::last_os_error())
                } else {
                    Ok((fd, branch))
                }
            }).await
            .map_err(|_| std::io::Error::from_raw_os_error(libc::EIO))??;
            
            // Register file handle
            let handle = FileHandle::new(fd, branch_ref, path, libc::O_WRONLY, false);
            let handle_id = file_registry.register(handle);
            
            Ok(handle_id)
        })
    }
}
```

## Memory Management Patterns

### Safe Memory Pools

```rust
use std::sync::atomic::{AtomicUsize, Ordering};
use crossbeam_queue::SegQueue;

pub struct MemoryPool<T> {
    pool: SegQueue<Box<T>>,
    max_size: usize,
    current_size: AtomicUsize,
    create_fn: Box<dyn Fn() -> T + Send + Sync>,
}

impl<T> MemoryPool<T>
where
    T: Send + 'static,
{
    pub fn new<F>(max_size: usize, create_fn: F) -> Self
    where
        F: Fn() -> T + Send + Sync + 'static,
    {
        Self {
            pool: SegQueue::new(),
            max_size,
            current_size: AtomicUsize::new(0),
            create_fn: Box::new(create_fn),
        }
    }
    
    pub fn get(&self) -> PooledItem<T> {
        if let Some(item) = self.pool.pop() {
            PooledItem::new(item, self)
        } else {
            let item = Box::new((self.create_fn)());
            self.current_size.fetch_add(1, Ordering::Relaxed);
            PooledItem::new(item, self)
        }
    }
    
    fn return_item(&self, item: Box<T>) {
        if self.current_size.load(Ordering::Relaxed) <= self.max_size {
            self.pool.push(item);
        } else {
            self.current_size.fetch_sub(1, Ordering::Relaxed);
        }
    }
    
    pub fn stats(&self) -> PoolStats {
        PoolStats {
            pool_size: self.pool.len(),
            total_allocated: self.current_size.load(Ordering::Relaxed),
            max_size: self.max_size,
        }
    }
}

pub struct PooledItem<'a, T> {
    item: Option<Box<T>>,
    pool: &'a MemoryPool<T>,
}

impl<'a, T> PooledItem<'a, T> {
    fn new(item: Box<T>, pool: &'a MemoryPool<T>) -> Self {
        Self {
            item: Some(item),
            pool,
        }
    }
}

impl<'a, T> std::ops::Deref for PooledItem<'a, T> {
    type Target = T;
    
    fn deref(&self) -> &Self::Target {
        self.item.as_ref().unwrap()
    }
}

impl<'a, T> std::ops::DerefMut for PooledItem<'a, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.item.as_mut().unwrap()
    }
}

impl<'a, T> Drop for PooledItem<'a, T> {
    fn drop(&mut self) {
        if let Some(item) = self.item.take() {
            self.pool.return_item(item);
        }
    }
}

#[derive(Debug)]
pub struct PoolStats {
    pub pool_size: usize,
    pub total_allocated: usize,
    pub max_size: usize,
}

// Global memory pools for common buffer types
lazy_static::lazy_static! {
    pub static ref DIRECTORY_BUFFER_POOL: MemoryPool<Vec<u8>> =
        MemoryPool::new(10, || Vec::with_capacity(128 * 1024));
    
    pub static ref IO_BUFFER_POOL: MemoryPool<Vec<u8>> =
        MemoryPool::new(20, || Vec::with_capacity(64 * 1024));
    
    pub static ref PATH_BUFFER_POOL: MemoryPool<String> =
        MemoryPool::new(50, || String::with_capacity(4096));
}
```

## Cache Management with TTL

### Thread-Safe Caching

```rust
use std::collections::HashMap;
use std::hash::Hash;
use std::time::{Duration, Instant};
use parking_lot::RwLock;

#[derive(Debug, Clone)]
struct CacheEntry<V> {
    value: V,
    expires_at: Instant,
}

impl<V> CacheEntry<V> {
    fn new(value: V, ttl: Duration) -> Self {
        Self {
            value,
            expires_at: Instant::now() + ttl,
        }
    }
    
    fn is_expired(&self) -> bool {
        Instant::now() > self.expires_at
    }
}

pub struct TtlCache<K, V> {
    data: RwLock<HashMap<K, CacheEntry<V>>>,
    default_ttl: Duration,
}

impl<K, V> TtlCache<K, V>
where
    K: Eq + Hash + Clone,
    V: Clone,
{
    pub fn new(default_ttl: Duration) -> Self {
        Self {
            data: RwLock::new(HashMap::new()),
            default_ttl,
        }
    }
    
    pub fn get(&self, key: &K) -> Option<V> {
        let data = self.data.read();
        data.get(key).and_then(|entry| {
            if entry.is_expired() {
                None
            } else {
                Some(entry.value.clone())
            }
        })
    }
    
    pub fn insert(&self, key: K, value: V) {
        self.insert_with_ttl(key, value, self.default_ttl);
    }
    
    pub fn insert_with_ttl(&self, key: K, value: V, ttl: Duration) {
        let entry = CacheEntry::new(value, ttl);
        self.data.write().insert(key, entry);
    }
    
    pub fn remove(&self, key: &K) -> Option<V> {
        self.data.write().remove(key).map(|entry| entry.value)
    }
    
    pub fn cleanup_expired(&self) {
        let mut data = self.data.write();
        data.retain(|_, entry| !entry.is_expired());
    }
    
    pub fn clear(&self) {
        self.data.write().clear();
    }
    
    pub fn len(&self) -> usize {
        self.data.read().len()
    }
    
    pub fn is_empty(&self) -> bool {
        self.data.read().is_empty()
    }
}

// Specific cache types for filesystem operations
pub type StatvfsCache = TtlCache<std::path::PathBuf, libc::statvfs>;
pub type ReadonlyCache = TtlCache<std::path::PathBuf, bool>;
pub type AttrCache = TtlCache<std::path::PathBuf, libc::stat>;

// Global cache instances
lazy_static::lazy_static! {
    pub static ref STATVFS_CACHE: StatvfsCache = 
        TtlCache::new(Duration::from_secs(1));
    
    pub static ref READONLY_CACHE: ReadonlyCache = 
        TtlCache::new(Duration::from_secs(5));
    
    pub static ref ATTR_CACHE: AttrCache = 
        TtlCache::new(Duration::from_secs(1));
}

// Background cleanup task
pub async fn start_cache_cleanup_task() {
    let mut interval = tokio::time::interval(Duration::from_secs(30));
    
    loop {
        interval.tick().await;
        
        tokio::task::spawn_blocking(|| {
            STATVFS_CACHE.cleanup_expired();
            READONLY_CACHE.cleanup_expired();
            ATTR_CACHE.cleanup_expired();
        }).await.ok();
    }
}
```

## Deadlock Prevention

### Ordered Locking

```rust
use std::cmp::Ordering;
use std::sync::atomic::{AtomicUsize, Ordering as AtomicOrdering};
use parking_lot::Mutex;

static NEXT_LOCK_ID: AtomicUsize = AtomicUsize::new(1);

#[derive(Debug)]
pub struct OrderedMutex<T> {
    mutex: Mutex<T>,
    id: usize,
}

impl<T> OrderedMutex<T> {
    pub fn new(data: T) -> Self {
        Self {
            mutex: Mutex::new(data),
            id: NEXT_LOCK_ID.fetch_add(1, AtomicOrdering::Relaxed),
        }
    }
    
    pub fn id(&self) -> usize {
        self.id
    }
    
    pub fn lock(&self) -> parking_lot::MutexGuard<T> {
        self.mutex.lock()
    }
}

impl<T> PartialEq for OrderedMutex<T> {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl<T> Eq for OrderedMutex<T> {}

impl<T> PartialOrd for OrderedMutex<T> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl<T> Ord for OrderedMutex<T> {
    fn cmp(&self, other: &Self) -> Ordering {
        self.id.cmp(&other.id)
    }
}

pub struct MultiLock<'a, T> {
    mutexes: Vec<&'a OrderedMutex<T>>,
}

impl<'a, T> MultiLock<'a, T> {
    pub fn new() -> Self {
        Self {
            mutexes: Vec::new(),
        }
    }
    
    pub fn add(&mut self, mutex: &'a OrderedMutex<T>) {
        self.mutexes.push(mutex);
    }
    
    pub fn lock_all(mut self) -> Vec<parking_lot::MutexGuard<'a, T>> {
        // Sort by ID to prevent deadlocks
        self.mutexes.sort_by_key(|m| m.id());
        
        self.mutexes
            .into_iter()
            .map(|m| m.lock())
            .collect()
    }
}

// Example usage for file operations that might need multiple locks
pub fn atomic_rename_operation(
    src_handle: &OrderedMutex<FileHandle>,
    dst_handle: &OrderedMutex<FileHandle>,
) -> Result<(), std::io::Error> {
    let mut multi_lock = MultiLock::new();
    multi_lock.add(src_handle);
    multi_lock.add(dst_handle);
    
    let _guards = multi_lock.lock_all();
    
    // Perform atomic rename operation while holding both locks
    // ...
    
    Ok(())
}
```

## User Context Management

### Thread-Local Context

```rust
use std::cell::RefCell;

thread_local! {
    static USER_CONTEXT: RefCell<Option<UserContext>> = RefCell::new(None);
}

#[derive(Debug, Clone, Copy)]
pub struct UserContext {
    pub uid: libc::uid_t,
    pub gid: libc::gid_t,
    pub pid: libc::pid_t,
}

impl UserContext {
    pub fn new(uid: libc::uid_t, gid: libc::gid_t, pid: libc::pid_t) -> Self {
        Self { uid, gid, pid }
    }
    
    pub fn current() -> Option<Self> {
        USER_CONTEXT.with(|ctx| *ctx.borrow())
    }
    
    pub fn set_current(ctx: Self) {
        USER_CONTEXT.with(|current| *current.borrow_mut() = Some(ctx));
    }
    
    pub fn clear_current() {
        USER_CONTEXT.with(|current| *current.borrow_mut() = None);
    }
}

// RAII guard for user context
pub struct UserContextGuard {
    previous: Option<UserContext>,
}

impl UserContextGuard {
    pub fn new(ctx: UserContext) -> Self {
        let previous = UserContext::current();
        UserContext::set_current(ctx);
        
        Self { previous }
    }
}

impl Drop for UserContextGuard {
    fn drop(&mut self) {
        match self.previous {
            Some(ctx) => UserContext::set_current(ctx),
            None => UserContext::clear_current(),
        }
    }
}

// Async-compatible user context using task-local storage
use tokio::task_local;

task_local! {
    static ASYNC_USER_CONTEXT: UserContext;
}

pub async fn with_user_context<F, R>(ctx: UserContext, f: F) -> R
where
    F: std::future::Future<Output = R>,
{
    ASYNC_USER_CONTEXT.scope(ctx, f).await
}

pub fn get_current_user_context() -> Option<UserContext> {
    ASYNC_USER_CONTEXT.try_with(|ctx| *ctx).ok()
}
```

## Performance Monitoring

### Concurrent Metrics Collection

```rust
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct OperationMetrics {
    total_operations: AtomicU64,
    successful_operations: AtomicU64,
    failed_operations: AtomicU64,
    total_duration_nanos: AtomicU64,
    max_duration_nanos: AtomicU64,
}

impl OperationMetrics {
    pub fn new() -> Self {
        Self {
            total_operations: AtomicU64::new(0),
            successful_operations: AtomicU64::new(0),
            failed_operations: AtomicU64::new(0),
            total_duration_nanos: AtomicU64::new(0),
            max_duration_nanos: AtomicU64::new(0),
        }
    }
    
    pub fn record_success(&self, duration: Duration) {
        self.total_operations.fetch_add(1, Ordering::Relaxed);
        self.successful_operations.fetch_add(1, Ordering::Relaxed);
        
        let duration_nanos = duration.as_nanos() as u64;
        self.total_duration_nanos.fetch_add(duration_nanos, Ordering::Relaxed);
        
        // Update max duration
        let mut current_max = self.max_duration_nanos.load(Ordering::Relaxed);
        while duration_nanos > current_max {
            match self.max_duration_nanos.compare_exchange_weak(
                current_max,
                duration_nanos,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(new_max) => current_max = new_max,
            }
        }
    }
    
    pub fn record_failure(&self, duration: Duration) {
        self.total_operations.fetch_add(1, Ordering::Relaxed);
        self.failed_operations.fetch_add(1, Ordering::Relaxed);
        
        let duration_nanos = duration.as_nanos() as u64;
        self.total_duration_nanos.fetch_add(duration_nanos, Ordering::Relaxed);
    }
    
    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            total_operations: self.total_operations.load(Ordering::Relaxed),
            successful_operations: self.successful_operations.load(Ordering::Relaxed),
            failed_operations: self.failed_operations.load(Ordering::Relaxed),
            total_duration: Duration::from_nanos(
                self.total_duration_nanos.load(Ordering::Relaxed)
            ),
            max_duration: Duration::from_nanos(
                self.max_duration_nanos.load(Ordering::Relaxed)
            ),
        }
    }
}

#[derive(Debug, Clone)]
pub struct MetricsSnapshot {
    pub total_operations: u64,
    pub successful_operations: u64,
    pub failed_operations: u64,
    pub total_duration: Duration,
    pub max_duration: Duration,
}

impl MetricsSnapshot {
    pub fn success_rate(&self) -> f64 {
        if self.total_operations == 0 {
            0.0
        } else {
            self.successful_operations as f64 / self.total_operations as f64
        }
    }
    
    pub fn average_duration(&self) -> Duration {
        if self.total_operations == 0 {
            Duration::ZERO
        } else {
            self.total_duration / self.total_operations as u32
        }
    }
}

// RAII timer for automatic metrics collection
pub struct OperationTimer<'a> {
    metrics: &'a OperationMetrics,
    start_time: Instant,
}

impl<'a> OperationTimer<'a> {
    pub fn new(metrics: &'a OperationMetrics) -> Self {
        Self {
            metrics,
            start_time: Instant::now(),
        }
    }
    
    pub fn finish_success(self) {
        let duration = self.start_time.elapsed();
        self.metrics.record_success(duration);
        std::mem::forget(self); // Prevent Drop from running
    }
    
    pub fn finish_failure(self) {
        let duration = self.start_time.elapsed();
        self.metrics.record_failure(duration);
        std::mem::forget(self); // Prevent Drop from running
    }
}

impl<'a> Drop for OperationTimer<'a> {
    fn drop(&mut self) {
        // Default to failure if not explicitly finished
        let duration = self.start_time.elapsed();
        self.metrics.record_failure(duration);
    }
}

// Global metrics for different operation types
lazy_static::lazy_static! {
    pub static ref READ_METRICS: OperationMetrics = OperationMetrics::new();
    pub static ref WRITE_METRICS: OperationMetrics = OperationMetrics::new();
    pub static ref CREATE_METRICS: OperationMetrics = OperationMetrics::new();
    pub static ref DELETE_METRICS: OperationMetrics = OperationMetrics::new();
}
```

## Testing Concurrency

### Stress Testing Framework

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::task::JoinSet;

pub struct ConcurrencyTestHarness {
    config_manager: Arc<ConfigManager>,
    branch_manager: Arc<BranchManager>,
    file_registry: Arc<FileHandleRegistry>,
}

impl ConcurrencyTestHarness {
    pub fn new() -> Self {
        // Set up test configuration
        let config = Config::default();
        let branches = vec![
            Arc::new(Branch::new(
                "/tmp/test_branch_1".into(),
                BranchMode::ReadWrite,
                0,
            )),
            Arc::new(Branch::new(
                "/tmp/test_branch_2".into(),
                BranchMode::ReadWrite,
                0,
            )),
        ];
        
        Self {
            config_manager: Arc::new(ConfigManager::new(config)),
            branch_manager: Arc::new(BranchManager::new(branches)),
            file_registry: Arc::new(FileHandleRegistry::new()),
        }
    }
    
    pub async fn stress_test_concurrent_reads(&self, duration: Duration) -> TestResults {
        let stop_flag = Arc::new(AtomicBool::new(false));
        let mut tasks = JoinSet::new();
        
        // Spawn multiple reader tasks
        for i in 0..10 {
            let config_manager = self.config_manager.clone();
            let stop_flag = stop_flag.clone();
            let file_path = format!("/test_file_{}", i);
            
            tasks.spawn(async move {
                let mut operations = 0u64;
                let mut errors = 0u64;
                
                while !stop_flag.load(Ordering::Relaxed) {
                    let result = config_manager.with_config(|config| {
                        // Simulate reading configuration
                        config.function_policies.clone()
                    });
                    
                    operations += 1;
                    
                    if result.create.name() == "invalid" {
                        errors += 1;
                    }
                    
                    tokio::task::yield_now().await;
                }
                
                (operations, errors)
            });
        }
        
        // Run for specified duration
        tokio::time::sleep(duration).await;
        stop_flag.store(true, Ordering::Relaxed);
        
        // Collect results
        let mut total_operations = 0u64;
        let mut total_errors = 0u64;
        
        while let Some(result) = tasks.join_next().await {
            match result {
                Ok((ops, errs)) => {
                    total_operations += ops;
                    total_errors += errs;
                }
                Err(_) => total_errors += 1,
            }
        }
        
        TestResults {
            total_operations,
            total_errors,
            duration,
        }
    }
    
    pub async fn test_concurrent_config_updates(&self) -> Result<(), Box<dyn std::error::Error>> {
        let mut tasks = JoinSet::new();
        
        // Spawn reader tasks
        for _ in 0..8 {
            let config_manager = self.config_manager.clone();
            tasks.spawn(async move {
                for _ in 0..1000 {
                    let _policies = config_manager.with_config(|config| {
                        config.function_policies.clone()
                    });
                    tokio::task::yield_now().await;
                }
            });
        }
        
        // Spawn writer task
        let config_manager = self.config_manager.clone();
        tasks.spawn(async move {
            for i in 0..100 {
                let new_policies = if i % 2 == 0 {
                    FunctionPolicies::default()
                } else {
                    let mut policies = FunctionPolicies::default();
                    policies.create = CreatePolicyRef::new("mfs");
                    policies
                };
                
                config_manager.update_config(|config| {
                    config.function_policies = new_policies;
                });
                
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        });
        
        // Wait for all tasks to complete
        while let Some(result) = tasks.join_next().await {
            result?;
        }
        
        Ok(())
    }
}

#[derive(Debug)]
pub struct TestResults {
    pub total_operations: u64,
    pub total_errors: u64,
    pub duration: Duration,
}

impl TestResults {
    pub fn operations_per_second(&self) -> f64 {
        self.total_operations as f64 / self.duration.as_secs_f64()
    }
    
    pub fn error_rate(&self) -> f64 {
        if self.total_operations == 0 {
            0.0
        } else {
            self.total_errors as f64 / self.total_operations as f64
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[tokio::test]
    async fn test_concurrent_config_access() {
        let harness = ConcurrencyTestHarness::new();
        let results = harness
            .stress_test_concurrent_reads(Duration::from_secs(1))
            .await;
        
        assert!(results.total_operations > 0);
        assert_eq!(results.total_errors, 0);
        assert!(results.operations_per_second() > 1000.0);
    }
    
    #[tokio::test]
    async fn test_config_update_consistency() {
        let harness = ConcurrencyTestHarness::new();
        harness.test_concurrent_config_updates().await.unwrap();
    }
}
```

This comprehensive approach to thread safety and concurrency in Rust provides:

1. **RAII-based locking** that prevents lock leaks
2. **Lock-free data structures** where possible using atomic operations
3. **Async/await integration** for scalable I/O operations
4. **Memory pools** for efficient buffer management
5. **Deadlock prevention** through ordered locking
6. **Thread-local storage** for user context management
7. **Performance monitoring** with atomic metrics
8. **Comprehensive testing** framework for concurrency validation

The patterns leverage Rust's ownership system and type safety to prevent common concurrency bugs while maintaining high performance.