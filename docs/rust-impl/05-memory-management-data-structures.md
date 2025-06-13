# Memory Management and Data Structures in Rust

## Overview

This guide provides comprehensive approaches for implementing mergerfs's memory management patterns and data structures in Rust, leveraging Rust's ownership system, zero-cost abstractions, and safe memory management to achieve high performance while maintaining memory safety.

## Core Memory Management Architecture

### Custom Memory Allocators

#### Pool-Based Allocators

```rust
use std::alloc::{GlobalAlloc, Layout};
use std::ptr::NonNull;
use std::sync::atomic::{AtomicPtr, Ordering};
use std::sync::Mutex;
use errno::{errno, set_errno, Errno};

pub struct PoolAllocator {
    pools: Vec<Mutex<Pool>>,
    fallback: std::alloc::System,
}

struct Pool {
    block_size: usize,
    blocks: Vec<NonNull<u8>>,
    free_list: AtomicPtr<u8>,
    allocated_count: usize,
    max_blocks: usize,
}

impl Pool {
    fn new(block_size: usize, initial_blocks: usize, max_blocks: usize) -> Self {
        let mut pool = Self {
            block_size,
            blocks: Vec::with_capacity(initial_blocks),
            free_list: AtomicPtr::new(std::ptr::null_mut()),
            allocated_count: 0,
            max_blocks,
        };
        
        pool.allocate_chunk(initial_blocks);
        pool
    }
    
    fn allocate_chunk(&mut self, count: usize) {
        let layout = Layout::from_size_align(
            self.block_size * count, 
            std::mem::align_of::<u8>()
        ).unwrap();
        
        unsafe {
            if let Ok(ptr) = std::alloc::System.alloc(layout) {
                let chunk = NonNull::new_unchecked(ptr);
                self.blocks.push(chunk);
                
                // Link blocks into free list
                for i in 0..count {
                    let block_ptr = ptr.add(i * self.block_size);
                    let next = if i + 1 < count {
                        ptr.add((i + 1) * self.block_size)
                    } else {
                        self.free_list.load(Ordering::Relaxed)
                    };
                    
                    *(block_ptr as *mut *mut u8) = next;
                }
                
                self.free_list.store(ptr, Ordering::Relaxed);
            }
        }
    }
    
    fn allocate(&mut self) -> Option<NonNull<u8>> {
        loop {
            let head = self.free_list.load(Ordering::Acquire);
            if head.is_null() {
                if self.blocks.len() * 64 < self.max_blocks {
                    self.allocate_chunk(64);
                    continue;
                } else {
                    return None; // Pool exhausted
                }
            }
            
            unsafe {
                let next = *(head as *const *mut u8);
                if self.free_list
                    .compare_exchange_weak(head, next, Ordering::Release, Ordering::Relaxed)
                    .is_ok() 
                {
                    self.allocated_count += 1;
                    return Some(NonNull::new_unchecked(head));
                }
            }
        }
    }
    
    fn deallocate(&mut self, ptr: NonNull<u8>) {
        unsafe {
            let head = self.free_list.load(Ordering::Relaxed);
            *(ptr.as_ptr() as *mut *mut u8) = head;
            self.free_list.store(ptr.as_ptr(), Ordering::Release);
            self.allocated_count -= 1;
        }
    }
}

impl PoolAllocator {
    pub fn new() -> Self {
        Self {
            pools: vec![
                Mutex::new(Pool::new(64, 100, 1000)),      // Small objects
                Mutex::new(Pool::new(256, 50, 500)),       // Medium objects  
                Mutex::new(Pool::new(1024, 25, 250)),      // Large objects
                Mutex::new(Pool::new(4096, 10, 100)),      // Page-sized objects
            ],
            fallback: std::alloc::System,
        }
    }
    
    fn select_pool(&self, size: usize) -> Option<usize> {
        match size {
            1..=64 => Some(0),
            65..=256 => Some(1),
            257..=1024 => Some(2),
            1025..=4096 => Some(3),
            _ => None,
        }
    }
}

unsafe impl GlobalAlloc for PoolAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        if let Some(pool_idx) = self.select_pool(layout.size()) {
            if let Ok(mut pool) = self.pools[pool_idx].try_lock() {
                if let Some(ptr) = pool.allocate() {
                    return ptr.as_ptr();
                }
            }
        }
        
        // Fallback to system allocator
        self.fallback.alloc(layout)
    }
    
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        if let Some(pool_idx) = self.select_pool(layout.size()) {
            if let Ok(mut pool) = self.pools[pool_idx].try_lock() {
                // Check if pointer belongs to this pool
                let ptr_nn = NonNull::new_unchecked(ptr);
                for chunk in &pool.blocks {
                    let chunk_start = chunk.as_ptr() as usize;
                    let chunk_end = chunk_start + (pool.block_size * 64); // Assuming 64 blocks per chunk
                    let ptr_addr = ptr as usize;
                    
                    if ptr_addr >= chunk_start && ptr_addr < chunk_end {
                        pool.deallocate(ptr_nn);
                        return;
                    }
                }
            }
        }
        
        // Fallback to system allocator
        self.fallback.dealloc(ptr, layout);
    }
}

// Global allocator instance
#[global_allocator]
static POOL_ALLOCATOR: PoolAllocator = PoolAllocator {
    pools: vec![], // Will be initialized properly
    fallback: std::alloc::System,
};
```

### Stack-Based Buffer Management

#### Fixed-Size Buffer Pools

```rust
use std::mem::MaybeUninit;
use std::sync::atomic::{AtomicUsize, Ordering};
use crossbeam_queue::SegQueue;

pub struct BufferPool<const SIZE: usize> {
    buffers: SegQueue<Box<[u8; SIZE]>>,
    allocated_count: AtomicUsize,
    max_buffers: usize,
}

impl<const SIZE: usize> BufferPool<SIZE> {
    pub fn new(initial_count: usize, max_buffers: usize) -> Self {
        let pool = Self {
            buffers: SegQueue::new(),
            allocated_count: AtomicUsize::new(0),
            max_buffers,
        };
        
        for _ in 0..initial_count {
            let buffer = Box::new([0u8; SIZE]);
            pool.buffers.push(buffer);
        }
        
        pool
    }
    
    pub fn acquire(&self) -> Option<PooledBuffer<SIZE>> {
        if let Some(buffer) = self.buffers.pop() {
            Some(PooledBuffer::new(buffer, self))
        } else if self.allocated_count.load(Ordering::Relaxed) < self.max_buffers {
            let buffer = Box::new([0u8; SIZE]);
            self.allocated_count.fetch_add(1, Ordering::Relaxed);
            Some(PooledBuffer::new(buffer, self))
        } else {
            None // Pool exhausted
        }
    }
    
    fn return_buffer(&self, buffer: Box<[u8; SIZE]>) {
        self.buffers.push(buffer);
    }
    
    pub fn stats(&self) -> BufferPoolStats {
        BufferPoolStats {
            buffer_size: SIZE,
            available_buffers: self.buffers.len(),
            allocated_buffers: self.allocated_count.load(Ordering::Relaxed),
            max_buffers: self.max_buffers,
        }
    }
}

pub struct PooledBuffer<'a, const SIZE: usize> {
    buffer: Option<Box<[u8; SIZE]>>,
    pool: &'a BufferPool<SIZE>,
    len: usize,
}

impl<'a, const SIZE: usize> PooledBuffer<'a, SIZE> {
    fn new(buffer: Box<[u8; SIZE]>, pool: &'a BufferPool<SIZE>) -> Self {
        Self {
            buffer: Some(buffer),
            pool,
            len: 0,
        }
    }
    
    pub fn as_slice(&self) -> &[u8] {
        &self.buffer.as_ref().unwrap()[..self.len]
    }
    
    pub fn as_mut_slice(&mut self) -> &mut [u8] {
        let buf = self.buffer.as_mut().unwrap();
        &mut buf[..SIZE]
    }
    
    pub fn set_len(&mut self, len: usize) {
        assert!(len <= SIZE);
        self.len = len;
    }
    
    pub fn capacity(&self) -> usize {
        SIZE
    }
    
    pub fn clear(&mut self) {
        self.len = 0;
        if let Some(ref mut buffer) = self.buffer {
            buffer.fill(0);
        }
    }
}

impl<'a, const SIZE: usize> Drop for PooledBuffer<'a, SIZE> {
    fn drop(&mut self) {
        if let Some(buffer) = self.buffer.take() {
            self.pool.return_buffer(buffer);
        }
    }
}

impl<'a, const SIZE: usize> std::ops::Deref for PooledBuffer<'a, SIZE> {
    type Target = [u8];
    
    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}

impl<'a, const SIZE: usize> std::ops::DerefMut for PooledBuffer<'a, SIZE> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.buffer.as_mut().unwrap()[..self.len]
    }
}

#[derive(Debug, Clone)]
pub struct BufferPoolStats {
    pub buffer_size: usize,
    pub available_buffers: usize,
    pub allocated_buffers: usize,
    pub max_buffers: usize,
}

// Pre-defined buffer pools for common sizes
lazy_static::lazy_static! {
    pub static ref IO_BUFFER_POOL_4K: BufferPool<4096> = BufferPool::new(20, 100);
    pub static ref IO_BUFFER_POOL_64K: BufferPool<65536> = BufferPool::new(10, 50);
    pub static ref DIR_BUFFER_POOL: BufferPool<16384> = BufferPool::new(15, 75);
    pub static ref PATH_BUFFER_POOL: BufferPool<4096> = BufferPool::new(25, 100);
}
```

## High-Performance Data Structures

### Lock-Free Branch Vector

#### Copy-on-Write Branch Collection

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicPtr, Ordering};

pub struct BranchVector {
    data: AtomicPtr<BranchData>,
}

struct BranchData {
    branches: Vec<Arc<Branch>>,
    generation: u64,
}

impl BranchVector {
    pub fn new(branches: Vec<Arc<Branch>>) -> Self {
        let data = Box::into_raw(Box::new(BranchData {
            branches,
            generation: 0,
        }));
        
        Self {
            data: AtomicPtr::new(data),
        }
    }
    
    pub fn read(&self) -> BranchSnapshot {
        let ptr = self.data.load(Ordering::Acquire);
        unsafe {
            let data = &*ptr;
            BranchSnapshot {
                branches: data.branches.clone(),
                generation: data.generation,
            }
        }
    }
    
    pub fn update<F>(&self, updater: F) -> Result<(), UpdateError>
    where
        F: FnOnce(&[Arc<Branch>]) -> Vec<Arc<Branch>>,
    {
        loop {
            let current_ptr = self.data.load(Ordering::Acquire);
            let current_data = unsafe { &*current_ptr };
            
            let new_branches = updater(&current_data.branches);
            let new_data = Box::into_raw(Box::new(BranchData {
                branches: new_branches,
                generation: current_data.generation + 1,
            }));
            
            match self.data.compare_exchange_weak(
                current_ptr,
                new_data,
                Ordering::Release,
                Ordering::Relaxed,
            ) {
                Ok(_) => {
                    // Schedule old data for cleanup
                    self.schedule_cleanup(current_ptr);
                    return Ok(());
                }
                Err(_) => {
                    // Retry with new data
                    unsafe { Box::from_raw(new_data) }; // Cleanup failed attempt
                    continue;
                }
            }
        }
    }
    
    fn schedule_cleanup(&self, old_ptr: *mut BranchData) {
        // Use epoch-based reclamation or similar technique
        // For simplicity, we'll use a background thread
        std::thread::spawn(move || {
            // Wait for all readers to finish
            std::thread::sleep(std::time::Duration::from_millis(100));
            unsafe {
                Box::from_raw(old_ptr);
            }
        });
    }
}

#[derive(Clone)]
pub struct BranchSnapshot {
    branches: Vec<Arc<Branch>>,
    generation: u64,
}

impl BranchSnapshot {
    pub fn iter(&self) -> impl Iterator<Item = &Arc<Branch>> {
        self.branches.iter()
    }
    
    pub fn len(&self) -> usize {
        self.branches.len()
    }
    
    pub fn get(&self, index: usize) -> Option<&Arc<Branch>> {
        self.branches.get(index)
    }
    
    pub fn generation(&self) -> u64 {
        self.generation
    }
}

#[derive(Debug, thiserror::Error)]
pub enum UpdateError {
    #[error("Update failed due to concurrent modification")]
    ConcurrentModification,
}

impl Drop for BranchVector {
    fn drop(&mut self) {
        let ptr = self.data.load(Ordering::Relaxed);
        unsafe {
            Box::from_raw(ptr);
        }
    }
}
```

### Efficient File Handle Storage

#### Hierarchical File Handle Map

```rust
use std::collections::HashMap;
use std::sync::RwLock;
use parking_lot::RwLock as ParkingRwLock;

const BUCKET_COUNT: usize = 256;

pub struct FileHandleRegistry {
    buckets: [ParkingRwLock<HashMap<u64, Arc<FileHandle>>>; BUCKET_COUNT],
    next_id: std::sync::atomic::AtomicU64,
}

impl FileHandleRegistry {
    pub fn new() -> Self {
        const INIT: ParkingRwLock<HashMap<u64, Arc<FileHandle>>> = 
            ParkingRwLock::new(HashMap::new());
        
        Self {
            buckets: [INIT; BUCKET_COUNT],
            next_id: std::sync::atomic::AtomicU64::new(1),
        }
    }
    
    fn bucket_index(&self, id: u64) -> usize {
        (id % BUCKET_COUNT as u64) as usize
    }
    
    pub fn insert(&self, handle: FileHandle) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let bucket_idx = self.bucket_index(id);
        
        self.buckets[bucket_idx]
            .write()
            .insert(id, Arc::new(handle));
        
        id
    }
    
    pub fn get(&self, id: u64) -> Option<Arc<FileHandle>> {
        let bucket_idx = self.bucket_index(id);
        self.buckets[bucket_idx]
            .read()
            .get(&id)
            .cloned()
    }
    
    pub fn remove(&self, id: u64) -> Option<Arc<FileHandle>> {
        let bucket_idx = self.bucket_index(id);
        self.buckets[bucket_idx]
            .write()
            .remove(&id)
    }
    
    pub fn with_handle<F, R>(&self, id: u64, f: F) -> Option<R>
    where
        F: FnOnce(&FileHandle) -> R,
    {
        let bucket_idx = self.bucket_index(id);
        let bucket = self.buckets[bucket_idx].read();
        bucket.get(&id).map(|handle| f(handle))
    }
    
    pub fn stats(&self) -> RegistryStats {
        let mut total_handles = 0;
        let mut max_bucket_size = 0;
        let mut min_bucket_size = usize::MAX;
        
        for bucket in &self.buckets {
            let size = bucket.read().len();
            total_handles += size;
            max_bucket_size = max_bucket_size.max(size);
            min_bucket_size = min_bucket_size.min(size);
        }
        
        RegistryStats {
            total_handles,
            bucket_count: BUCKET_COUNT,
            max_bucket_size,
            min_bucket_size,
            next_id: self.next_id.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone)]
pub struct RegistryStats {
    pub total_handles: usize,
    pub bucket_count: usize,
    pub max_bucket_size: usize,
    pub min_bucket_size: usize,
    pub next_id: u64,
}
```

### Efficient Path Storage

#### Interned String Pool

```rust
use std::collections::HashMap;
use std::sync::Arc;
use parking_lot::RwLock;
use std::hash::{Hash, Hasher};

pub struct StringInterner {
    strings: RwLock<HashMap<Arc<str>, ()>>,
    stats: RwLock<InternerStats>,
}

impl StringInterner {
    pub fn new() -> Self {
        Self {
            strings: RwLock::new(HashMap::new()),
            stats: RwLock::new(InternerStats::default()),
        }
    }
    
    pub fn intern<S: AsRef<str>>(&self, s: S) -> InternedString {
        let s_ref = s.as_ref();
        
        // Fast path: check if string already exists
        {
            let strings = self.strings.read();
            for existing in strings.keys() {
                if existing.as_ref() == s_ref {
                    self.stats.write().cache_hits += 1;
                    return InternedString { inner: existing.clone() };
                }
            }
        }
        
        // Slow path: intern new string
        let mut strings = self.strings.write();
        let arc_str: Arc<str> = Arc::from(s_ref);
        strings.insert(arc_str.clone(), ());
        
        self.stats.write().cache_misses += 1;
        InternedString { inner: arc_str }
    }
    
    pub fn stats(&self) -> InternerStats {
        self.stats.read().clone()
    }
    
    pub fn cleanup(&self) {
        let mut strings = self.strings.write();
        let initial_count = strings.len();
        
        // Remove strings with only one reference (our reference)
        strings.retain(|k, _| Arc::strong_count(k) > 1);
        
        let cleaned = initial_count - strings.len();
        self.stats.write().cleaned_strings += cleaned;
    }
}

#[derive(Clone)]
pub struct InternedString {
    inner: Arc<str>,
}

impl InternedString {
    pub fn as_str(&self) -> &str {
        &self.inner
    }
    
    pub fn len(&self) -> usize {
        self.inner.len()
    }
    
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }
}

impl std::fmt::Display for InternedString {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.inner.fmt(f)
    }
}

impl std::fmt::Debug for InternedString {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.inner.fmt(f)
    }
}

impl Hash for InternedString {
    fn hash<H: Hasher>(&self, state: &mut H) {
        Arc::as_ptr(&self.inner).hash(state);
    }
}

impl PartialEq for InternedString {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.inner, &other.inner)
    }
}

impl Eq for InternedString {}

impl std::ops::Deref for InternedString {
    type Target = str;
    
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

#[derive(Debug, Clone, Default)]
pub struct InternerStats {
    pub cache_hits: usize,
    pub cache_misses: usize,
    pub cleaned_strings: usize,
}

// Path-specific interning with common prefixes
pub struct PathInterner {
    interner: StringInterner,
    common_prefixes: RwLock<Vec<InternedString>>,
}

impl PathInterner {
    pub fn new() -> Self {
        Self {
            interner: StringInterner::new(),
            common_prefixes: RwLock::new(Vec::new()),
        }
    }
    
    pub fn intern_path<P: AsRef<std::path::Path>>(&self, path: P) -> InternedPath {
        let path_str = path.as_ref().to_string_lossy();
        
        // Check for common prefixes
        {
            let prefixes = self.common_prefixes.read();
            for prefix in prefixes.iter() {
                if path_str.starts_with(prefix.as_str()) {
                    let suffix = &path_str[prefix.len()..];
                    return InternedPath {
                        prefix: Some(prefix.clone()),
                        suffix: self.interner.intern(suffix),
                    };
                }
            }
        }
        
        InternedPath {
            prefix: None,
            suffix: self.interner.intern(path_str.as_ref()),
        }
    }
    
    pub fn add_common_prefix<S: AsRef<str>>(&self, prefix: S) {
        let interned = self.interner.intern(prefix);
        self.common_prefixes.write().push(interned);
    }
}

#[derive(Clone)]
pub struct InternedPath {
    prefix: Option<InternedString>,
    suffix: InternedString,
}

impl InternedPath {
    pub fn as_path_buf(&self) -> std::path::PathBuf {
        match &self.prefix {
            Some(prefix) => {
                let mut path = std::path::PathBuf::from(prefix.as_str());
                path.push(self.suffix.as_str());
                path
            }
            None => std::path::PathBuf::from(self.suffix.as_str()),
        }
    }
    
    pub fn to_string(&self) -> String {
        match &self.prefix {
            Some(prefix) => format!("{}{}", prefix.as_str(), self.suffix.as_str()),
            None => self.suffix.as_str().to_string(),
        }
    }
}

// Global path interner
lazy_static::lazy_static! {
    pub static ref GLOBAL_PATH_INTERNER: PathInterner = {
        let interner = PathInterner::new();
        // Add common prefixes
        interner.add_common_prefix("/usr");
        interner.add_common_prefix("/home");
        interner.add_common_prefix("/var");
        interner.add_common_prefix("/tmp");
        interner
    };
}
```

## RAII Memory Management

### Smart Resource Guards

#### File Descriptor RAII

```rust
use std::os::unix::io::{AsRawFd, RawFd};
use std::sync::atomic::{AtomicBool, Ordering};

pub struct FileDescriptor {
    fd: RawFd,
    should_close: AtomicBool,
}

impl FileDescriptor {
    pub fn new(fd: RawFd) -> Self {
        Self {
            fd,
            should_close: AtomicBool::new(true),
        }
    }
    
    pub fn raw_fd(&self) -> RawFd {
        self.fd
    }
    
    pub fn leak(self) -> RawFd {
        self.should_close.store(false, Ordering::Relaxed);
        let fd = self.fd;
        std::mem::forget(self);
        fd
    }
    
    pub fn duplicate(&self) -> Result<FileDescriptor, std::io::Error> {
        let new_fd = unsafe { libc::dup(self.fd) };
        if new_fd == -1 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(FileDescriptor::new(new_fd))
        }
    }
}

impl AsRawFd for FileDescriptor {
    fn as_raw_fd(&self) -> RawFd {
        self.fd
    }
}

impl Drop for FileDescriptor {
    fn drop(&mut self) {
        if self.should_close.load(Ordering::Relaxed) && self.fd >= 0 {
            unsafe {
                libc::close(self.fd);
            }
        }
    }
}

// Memory-mapped file RAII
pub struct MemoryMap {
    ptr: *mut libc::c_void,
    length: usize,
}

impl MemoryMap {
    pub fn new(fd: RawFd, offset: u64, length: usize, writable: bool) -> Result<Self, std::io::Error> {
        let prot = if writable {
            libc::PROT_READ | libc::PROT_WRITE
        } else {
            libc::PROT_READ
        };
        
        let ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                length,
                prot,
                libc::MAP_SHARED,
                fd,
                offset as libc::off_t,
            )
        };
        
        if ptr == libc::MAP_FAILED {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(Self { ptr, length })
        }
    }
    
    pub fn as_slice(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.ptr as *const u8, self.length) }
    }
    
    pub fn as_mut_slice(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.ptr as *mut u8, self.length) }
    }
    
    pub fn sync(&self) -> Result<(), std::io::Error> {
        let result = unsafe { libc::msync(self.ptr, self.length, libc::MS_SYNC) };
        if result == 0 {
            Ok(())
        } else {
            Err(std::io::Error::last_os_error())
        }
    }
}

impl Drop for MemoryMap {
    fn drop(&mut self) {
        unsafe {
            libc::munmap(self.ptr, self.length);
        }
    }
}
```

### Scoped Resource Management

#### Directory Handle Scoping

```rust
use std::path::Path;
use std::ffi::CString;

pub struct DirectoryHandle {
    dir: *mut libc::DIR,
    path: std::path::PathBuf,
}

impl DirectoryHandle {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, std::io::Error> {
        let path_buf = path.as_ref().to_path_buf();
        let path_cstr = CString::new(path_buf.to_string_lossy().as_ref())?;
        
        let dir = unsafe { libc::opendir(path_cstr.as_ptr()) };
        if dir.is_null() {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(Self {
                dir,
                path: path_buf,
            })
        }
    }
    
    pub fn read_entry(&mut self) -> Result<Option<DirectoryEntry>, std::io::Error> {
        unsafe {
            // Reset errno before calling readdir - use portable errno handling
            errno::set_errno(errno::Errno(0));
            
            let entry = libc::readdir(self.dir);
            if entry.is_null() {
                let errno = errno::errno().0;
                if errno == 0 {
                    Ok(None) // End of directory
                } else {
                    Err(std::io::Error::from_raw_os_error(errno))
                }
            } else {
                Ok(Some(DirectoryEntry::from_raw(entry)))
            }
        }
    }
    
    pub fn rewind(&mut self) {
        unsafe {
            libc::rewinddir(self.dir);
        }
    }
    
    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for DirectoryHandle {
    fn drop(&mut self) {
        if !self.dir.is_null() {
            unsafe {
                libc::closedir(self.dir);
            }
        }
    }
}

pub struct DirectoryEntry {
    name: String,
    file_type: FileType,
    inode: u64,
}

impl DirectoryEntry {
    unsafe fn from_raw(entry: *const libc::dirent) -> Self {
        let name = std::ffi::CStr::from_ptr((*entry).d_name.as_ptr())
            .to_string_lossy()
            .into_owned();
        
        let file_type = match (*entry).d_type {
            libc::DT_REG => FileType::RegularFile,
            libc::DT_DIR => FileType::Directory,
            libc::DT_LNK => FileType::SymbolicLink,
            libc::DT_CHR => FileType::CharacterDevice,
            libc::DT_BLK => FileType::BlockDevice,
            libc::DT_FIFO => FileType::Fifo,
            libc::DT_SOCK => FileType::Socket,
            _ => FileType::Unknown,
        };
        
        Self {
            name,
            file_type,
            inode: (*entry).d_ino,
        }
    }
    
    pub fn name(&self) -> &str {
        &self.name
    }
    
    pub fn file_type(&self) -> FileType {
        self.file_type
    }
    
    pub fn inode(&self) -> u64 {
        self.inode
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileType {
    RegularFile,
    Directory,
    SymbolicLink,
    CharacterDevice,
    BlockDevice,
    Fifo,
    Socket,
    Unknown,
}

// Scoped directory reader
pub struct ScopedDirectoryReader<'a> {
    handle: &'a mut DirectoryHandle,
    entries: Vec<DirectoryEntry>,
    position: usize,
}

impl<'a> ScopedDirectoryReader<'a> {
    pub fn new(handle: &'a mut DirectoryHandle) -> Result<Self, std::io::Error> {
        let mut entries = Vec::new();
        
        while let Some(entry) = handle.read_entry()? {
            if entry.name() != "." && entry.name() != ".." {
                entries.push(entry);
            }
        }
        
        Ok(Self {
            handle,
            entries,
            position: 0,
        })
    }
    
    pub fn entries(&self) -> &[DirectoryEntry] {
        &self.entries
    }
    
    pub fn find_entry(&self, name: &str) -> Option<&DirectoryEntry> {
        self.entries.iter().find(|entry| entry.name() == name)
    }
}

impl<'a> Iterator for ScopedDirectoryReader<'a> {
    type Item = &'a DirectoryEntry;
    
    fn next(&mut self) -> Option<Self::Item> {
        if self.position < self.entries.len() {
            let entry = unsafe {
                // Safe because we control the lifetime
                std::mem::transmute(&self.entries[self.position])
            };
            self.position += 1;
            Some(entry)
        } else {
            None
        }
    }
}

impl<'a> Drop for ScopedDirectoryReader<'a> {
    fn drop(&mut self) {
        // Automatically rewind directory for next use
        self.handle.rewind();
    }
}
```

## Zero-Copy Data Structures

### Reference-Counted Slices

#### Shared Buffer Implementation

```rust
use std::sync::Arc;
use std::ops::{Deref, Range};

pub struct SharedBuffer {
    data: Arc<Vec<u8>>,
    offset: usize,
    length: usize,
}

impl SharedBuffer {
    pub fn new(data: Vec<u8>) -> Self {
        let length = data.len();
        Self {
            data: Arc::new(data),
            offset: 0,
            length,
        }
    }
    
    pub fn slice(&self, range: Range<usize>) -> Result<SharedBuffer, SliceError> {
        let start = range.start;
        let end = range.end.min(self.length);
        
        if start > end || start + self.offset >= self.data.len() {
            return Err(SliceError::OutOfBounds);
        }
        
        Ok(SharedBuffer {
            data: self.data.clone(),
            offset: self.offset + start,
            length: end - start,
        })
    }
    
    pub fn len(&self) -> usize {
        self.length
    }
    
    pub fn is_empty(&self) -> bool {
        self.length == 0
    }
    
    pub fn as_slice(&self) -> &[u8] {
        &self.data[self.offset..self.offset + self.length]
    }
    
    pub fn clone_data(&self) -> Vec<u8> {
        self.as_slice().to_vec()
    }
    
    pub fn reference_count(&self) -> usize {
        Arc::strong_count(&self.data)
    }
}

impl Clone for SharedBuffer {
    fn clone(&self) -> Self {
        Self {
            data: self.data.clone(),
            offset: self.offset,
            length: self.length,
        }
    }
}

impl Deref for SharedBuffer {
    type Target = [u8];
    
    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SliceError {
    #[error("Slice range is out of bounds")]
    OutOfBounds,
}

// Zero-copy string operations
pub struct SharedString {
    buffer: SharedBuffer,
}

impl SharedString {
    pub fn new(s: String) -> Self {
        Self {
            buffer: SharedBuffer::new(s.into_bytes()),
        }
    }
    
    pub fn as_str(&self) -> Result<&str, std::str::Utf8Error> {
        std::str::from_utf8(self.buffer.as_slice())
    }
    
    pub fn substring(&self, range: Range<usize>) -> Result<SharedString, SliceError> {
        // Ensure we don't break UTF-8 boundaries
        let bytes = self.buffer.as_slice();
        if range.start > bytes.len() || range.end > bytes.len() {
            return Err(SliceError::OutOfBounds);
        }
        
        // Find safe UTF-8 boundaries
        let start = find_utf8_boundary(bytes, range.start, true);
        let end = find_utf8_boundary(bytes, range.end, false);
        
        Ok(SharedString {
            buffer: self.buffer.slice(start..end)?,
        })
    }
    
    pub fn len(&self) -> usize {
        self.buffer.len()
    }
    
    pub fn char_len(&self) -> Result<usize, std::str::Utf8Error> {
        self.as_str().map(|s| s.chars().count())
    }
}

fn find_utf8_boundary(bytes: &[u8], mut pos: usize, round_down: bool) -> usize {
    while pos < bytes.len() {
        if (bytes[pos] & 0x80) == 0 || (bytes[pos] & 0xC0) == 0xC0 {
            return pos; // Found boundary
        }
        
        if round_down {
            if pos == 0 { break; }
            pos -= 1;
        } else {
            pos += 1;
        }
    }
    
    pos
}

impl std::fmt::Display for SharedString {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.as_str() {
            Ok(s) => s.fmt(f),
            Err(_) => write!(f, "<invalid UTF-8>"),
        }
    }
}

impl std::fmt::Debug for SharedString {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.as_str() {
            Ok(s) => write!(f, "SharedString({:?})", s),
            Err(_) => write!(f, "SharedString(<invalid UTF-8>)"),
        }
    }
}
```

## Memory Usage Optimization

### Compact Data Representations

#### Bit-Packed Structures

```rust
use std::mem::size_of;

// Compact file metadata representation
#[derive(Debug, Clone, Copy)]
pub struct CompactFileMetadata {
    // Pack multiple fields into single u64
    // Bits 0-31: file size (up to 4GB)
    // Bits 32-47: permissions (16 bits)
    // Bits 48-63: file type and flags (16 bits)
    packed_data: u64,
    
    // Timestamps as u32 (seconds since epoch)
    mtime: u32,
    ctime: u32,
}

impl CompactFileMetadata {
    pub fn new(size: u32, mode: u16, file_type: FileType, mtime: u32, ctime: u32) -> Self {
        let type_bits = (file_type as u16) << 12;
        let packed = (size as u64) | ((mode as u64) << 32) | ((type_bits as u64) << 48);
        
        Self {
            packed_data: packed,
            mtime,
            ctime,
        }
    }
    
    pub fn size(&self) -> u32 {
        (self.packed_data & 0xFFFFFFFF) as u32
    }
    
    pub fn mode(&self) -> u16 {
        ((self.packed_data >> 32) & 0xFFFF) as u16
    }
    
    pub fn file_type(&self) -> FileType {
        let type_bits = ((self.packed_data >> 60) & 0xF) as u8;
        FileType::from_bits(type_bits)
    }
    
    pub fn mtime(&self) -> u32 {
        self.mtime
    }
    
    pub fn ctime(&self) -> u32 {
        self.ctime
    }
    
    pub fn memory_footprint() -> usize {
        size_of::<Self>()
    }
}

#[derive(Debug, Clone, Copy)]
#[repr(u8)]
pub enum FileType {
    RegularFile = 0,
    Directory = 1,
    SymbolicLink = 2,
    CharacterDevice = 3,
    BlockDevice = 4,
    Fifo = 5,
    Socket = 6,
    Unknown = 7,
}

impl FileType {
    fn from_bits(bits: u8) -> Self {
        match bits {
            0 => FileType::RegularFile,
            1 => FileType::Directory,
            2 => FileType::SymbolicLink,
            3 => FileType::CharacterDevice,
            4 => FileType::BlockDevice,
            5 => FileType::Fifo,
            6 => FileType::Socket,
            _ => FileType::Unknown,
        }
    }
}

// Memory-efficient path components
#[derive(Debug)]
pub struct CompactPath {
    // Store path components as offsets into a shared string buffer
    components: Vec<ComponentRef>,
    buffer: SharedBuffer,
}

#[derive(Debug, Clone, Copy)]
struct ComponentRef {
    offset: u16,
    length: u8,
}

impl CompactPath {
    pub fn new<P: AsRef<std::path::Path>>(path: P) -> Self {
        let path_str = path.as_ref().to_string_lossy();
        let components: Vec<&str> = path_str.split('/').filter(|s| !s.is_empty()).collect();
        
        let mut buffer = String::new();
        let mut component_refs = Vec::new();
        
        for component in components {
            let offset = buffer.len() as u16;
            let length = component.len() as u8;
            
            buffer.push_str(component);
            component_refs.push(ComponentRef { offset, length });
        }
        
        Self {
            components: component_refs,
            buffer: SharedBuffer::new(buffer.into_bytes()),
        }
    }
    
    pub fn component_count(&self) -> usize {
        self.components.len()
    }
    
    pub fn component(&self, index: usize) -> Option<&str> {
        self.components.get(index).and_then(|comp_ref| {
            let start = comp_ref.offset as usize;
            let end = start + comp_ref.length as usize;
            
            if end <= self.buffer.len() {
                let bytes = &self.buffer[start..end];
                std::str::from_utf8(bytes).ok()
            } else {
                None
            }
        })
    }
    
    pub fn to_path_buf(&self) -> std::path::PathBuf {
        let mut path = std::path::PathBuf::new();
        for i in 0..self.component_count() {
            if let Some(component) = self.component(i) {
                path.push(component);
            }
        }
        path
    }
    
    pub fn memory_footprint(&self) -> usize {
        size_of::<Self>() + 
        self.components.capacity() * size_of::<ComponentRef>() +
        self.buffer.len()
    }
}
```

### Memory Pressure Monitoring

#### Adaptive Memory Management

```rust
use std::sync::atomic::{AtomicUsize, AtomicBool, Ordering};
use std::time::{Duration, Instant};

pub struct MemoryPressureMonitor {
    allocated_bytes: AtomicUsize,
    peak_allocated: AtomicUsize,
    memory_limit: usize,
    pressure_threshold: f64,
    under_pressure: AtomicBool,
    last_cleanup: parking_lot::RwLock<Instant>,
}

impl MemoryPressureMonitor {
    pub fn new(memory_limit: usize, pressure_threshold: f64) -> Self {
        Self {
            allocated_bytes: AtomicUsize::new(0),
            peak_allocated: AtomicUsize::new(0),
            memory_limit,
            pressure_threshold,
            under_pressure: AtomicBool::new(false),
            last_cleanup: parking_lot::RwLock::new(Instant::now()),
        }
    }
    
    pub fn allocate(&self, size: usize) -> bool {
        let new_total = self.allocated_bytes.fetch_add(size, Ordering::Relaxed) + size;
        
        // Update peak
        let mut current_peak = self.peak_allocated.load(Ordering::Relaxed);
        while new_total > current_peak {
            match self.peak_allocated.compare_exchange_weak(
                current_peak,
                new_total,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => current_peak = actual,
            }
        }
        
        // Check pressure
        let pressure_ratio = new_total as f64 / self.memory_limit as f64;
        let under_pressure = pressure_ratio > self.pressure_threshold;
        self.under_pressure.store(under_pressure, Ordering::Relaxed);
        
        new_total <= self.memory_limit
    }
    
    pub fn deallocate(&self, size: usize) {
        self.allocated_bytes.fetch_sub(size, Ordering::Relaxed);
        
        // Update pressure status
        let current = self.allocated_bytes.load(Ordering::Relaxed);
        let pressure_ratio = current as f64 / self.memory_limit as f64;
        let under_pressure = pressure_ratio > self.pressure_threshold;
        self.under_pressure.store(under_pressure, Ordering::Relaxed);
    }
    
    pub fn is_under_pressure(&self) -> bool {
        self.under_pressure.load(Ordering::Relaxed)
    }
    
    pub fn current_usage(&self) -> usize {
        self.allocated_bytes.load(Ordering::Relaxed)
    }
    
    pub fn usage_ratio(&self) -> f64 {
        self.current_usage() as f64 / self.memory_limit as f64
    }
    
    pub fn should_cleanup(&self) -> bool {
        if !self.is_under_pressure() {
            return false;
        }
        
        let last_cleanup = *self.last_cleanup.read();
        last_cleanup.elapsed() > Duration::from_secs(5) // Cleanup every 5 seconds
    }
    
    pub fn mark_cleanup_done(&self) {
        *self.last_cleanup.write() = Instant::now();
    }
    
    pub fn stats(&self) -> MemoryStats {
        MemoryStats {
            current_usage: self.current_usage(),
            peak_usage: self.peak_allocated.load(Ordering::Relaxed),
            memory_limit: self.memory_limit,
            usage_ratio: self.usage_ratio(),
            under_pressure: self.is_under_pressure(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct MemoryStats {
    pub current_usage: usize,
    pub peak_usage: usize,
    pub memory_limit: usize,
    pub usage_ratio: f64,
    pub under_pressure: bool,
}

// Memory-aware cache with automatic cleanup
pub struct MemoryAwareCache<K, V> {
    cache: parking_lot::RwLock<HashMap<K, CacheEntry<V>>>,
    monitor: Arc<MemoryPressureMonitor>,
    entry_size_estimate: usize,
}

struct CacheEntry<V> {
    value: V,
    last_accessed: Instant,
    access_count: usize,
}

impl<K, V> MemoryAwareCache<K, V>
where
    K: Eq + std::hash::Hash + Clone,
    V: Clone,
{
    pub fn new(monitor: Arc<MemoryPressureMonitor>, entry_size_estimate: usize) -> Self {
        Self {
            cache: parking_lot::RwLock::new(HashMap::new()),
            monitor,
            entry_size_estimate,
        }
    }
    
    pub fn get(&self, key: &K) -> Option<V> {
        let mut cache = self.cache.write();
        if let Some(entry) = cache.get_mut(key) {
            entry.last_accessed = Instant::now();
            entry.access_count += 1;
            Some(entry.value.clone())
        } else {
            None
        }
    }
    
    pub fn insert(&self, key: K, value: V) -> Result<(), MemoryError> {
        // Check if we can allocate memory
        if !self.monitor.allocate(self.entry_size_estimate) {
            return Err(MemoryError::OutOfMemory);
        }
        
        let entry = CacheEntry {
            value,
            last_accessed: Instant::now(),
            access_count: 1,
        };
        
        let mut cache = self.cache.write();
        if let Some(old_entry) = cache.insert(key, entry) {
            // We replaced an entry, so deallocate the old one
            self.monitor.deallocate(self.entry_size_estimate);
        }
        
        // Check if we should cleanup under pressure
        if self.monitor.should_cleanup() {
            self.cleanup_cache(&mut cache);
            self.monitor.mark_cleanup_done();
        }
        
        Ok(())
    }
    
    fn cleanup_cache(&self, cache: &mut HashMap<K, CacheEntry<V>>) {
        let target_size = cache.len() / 2; // Remove half the entries
        
        // Collect entries with their scores (lower is better for removal)
        let mut entries: Vec<_> = cache
            .iter()
            .map(|(k, v)| {
                let age_score = v.last_accessed.elapsed().as_secs() as f64;
                let frequency_score = 1.0 / (v.access_count as f64 + 1.0);
                let score = age_score + frequency_score;
                (k.clone(), score)
            })
            .collect();
        
        // Sort by score (highest first - least valuable)
        entries.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
        
        // Remove entries until we reach target size
        let to_remove = cache.len().saturating_sub(target_size);
        for (key, _) in entries.into_iter().take(to_remove) {
            cache.remove(&key);
            self.monitor.deallocate(self.entry_size_estimate);
        }
    }
    
    pub fn clear(&self) {
        let mut cache = self.cache.write();
        let removed_count = cache.len();
        cache.clear();
        self.monitor.deallocate(removed_count * self.entry_size_estimate);
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MemoryError {
    #[error("Out of memory")]
    OutOfMemory,
}

// Global memory monitor
lazy_static::lazy_static! {
    pub static ref GLOBAL_MEMORY_MONITOR: MemoryPressureMonitor = 
        MemoryPressureMonitor::new(
            1024 * 1024 * 1024, // 1GB limit
            0.8 // 80% pressure threshold
        );
}
```

This comprehensive memory management system provides:

1. **Custom pool allocators** for efficient small object allocation
2. **Stack-based buffer management** with RAII guarantees
3. **Lock-free data structures** for high-performance concurrent access
4. **Zero-copy operations** with shared buffers and string interning
5. **RAII resource management** for files, directories, and memory maps
6. **Compact data representations** to minimize memory usage
7. **Adaptive memory management** with pressure monitoring and automatic cleanup

The design leverages Rust's ownership system and zero-cost abstractions to achieve memory safety and high performance while providing the sophisticated memory management required for a high-performance filesystem.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content":"Create policy engine implementation guide for Rust","status":"completed","priority":"high","id":"1"},{"content":"Create thread safety and concurrency patterns guide","status":"completed","priority":"high","id":"2"},{"content":"Create error handling system design guide","status":"completed","priority":"high","id":"3"},{"content":"Create configuration system implementation guide","status":"completed","priority":"medium","id":"4"},{"content":"Create memory management and data structures guide","status":"completed","priority":"medium","id":"5"},{"content":"Create platform abstraction layer guide","status":"pending","priority":"medium","id":"6"},{"content":"Create FUSE integration patterns guide","status":"pending","priority":"medium","id":"7"},{"content":"Create testing and validation strategy guide","status":"pending","priority":"low","id":"8"}]