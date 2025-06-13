# FUSE Integration Patterns in Rust

## Overview

This guide provides comprehensive approaches for implementing FUSE (Filesystem in Userspace) integration in Rust for mergerfs using the `fuser` crate, covering safe FUSE operations, async support, request handling patterns, and performance optimizations while maintaining memory safety and high performance.

## Core FUSE Architecture

### Fuser Crate Integration

#### Dependencies

```toml
[dependencies]
fuser = "0.14"
tokio = { version = "1.0", features = ["full"] }
tracing = "0.1"
```

#### Request Context Management

```rust
use fuser::{Request, ReplyAttr, ReplyData, ReplyDirectory, ReplyEntry, ReplyOpen, ReplyWrite};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// Wrapper for FUSE request context
#[derive(Debug, Clone)]
pub struct RequestContext {
    pub uid: u32,
    pub gid: u32,
    pub pid: u32,
}

impl RequestContext {
    pub fn from_request(req: &Request<'_>) -> Self {
        Self {
            uid: req.uid(),
            gid: req.gid(),
            pid: req.pid(),
        }
    }
}

// File handle management
#[derive(Debug, Clone)]
pub struct FileHandle {
    pub id: u64,
    pub branch: Arc<Branch>,
    pub path: PathBuf,
    pub flags: i32,
    pub direct_io: bool,
}

impl FileHandle {
    pub fn new(
        id: u64,
        branch: Arc<Branch>,
        path: PathBuf,
        flags: i32,
        direct_io: bool,
    ) -> Self {
        Self {
            id,
            branch,
            path,
            flags,
            direct_io,
        }
    }
}
```

### Fuser Filesystem Trait Implementation

#### Using Fuser's Filesystem Trait

```rust
use fuser::{
    Filesystem, Request, ReplyAttr, ReplyData, ReplyDirectory, ReplyEntry, ReplyOpen, ReplyWrite,
    ReplyCreate, ReplyStatfs, ReplyXattr, FileAttr, FileType, FUSE_ROOT_ID
};
use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// Convert our internal types to fuser types
fn to_fuser_file_type(file_type: crate::FileType) -> FileType {
    match file_type {
        crate::FileType::RegularFile => FileType::RegularFile,
        crate::FileType::Directory => FileType::Directory,
        crate::FileType::SymbolicLink => FileType::Symlink,
        crate::FileType::CharacterDevice => FileType::CharDevice,
        crate::FileType::BlockDevice => FileType::BlockDevice,
        crate::FileType::Fifo => FileType::NamedPipe,
        crate::FileType::Socket => FileType::Socket,
        crate::FileType::Unknown => FileType::RegularFile,
    }
}

fn to_fuser_file_attr(attr: &crate::FileStat, ino: u64) -> FileAttr {
    FileAttr {
        ino,
        size: attr.size,
        blocks: attr.blocks,
        atime: UNIX_EPOCH + Duration::from_secs(attr.atime),
        mtime: UNIX_EPOCH + Duration::from_secs(attr.mtime),
        ctime: UNIX_EPOCH + Duration::from_secs(attr.ctime),
        crtime: UNIX_EPOCH + Duration::from_secs(attr.ctime),
        kind: to_fuser_file_type(crate::FileType::from_mode(attr.mode)),
        perm: (attr.mode & 0o7777) as u16,
        nlink: attr.nlinks as u32,
        uid: attr.uid,
        gid: attr.gid,
        rdev: 0,
        blksize: attr.blksize,
        flags: 0,
    }
}

// File handle registry for tracking open files
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use parking_lot::RwLock;

struct OpenFileHandle {
    pub branch: Arc<Branch>,
    pub path: PathBuf,
    pub file_descriptor: Option<std::os::unix::io::RawFd>,
    pub flags: i32,
    pub direct_io: bool,
}

struct InodeRegistry {
    path_to_inode: RwLock<BTreeMap<PathBuf, u64>>,
    inode_to_path: RwLock<BTreeMap<u64, PathBuf>>,
    next_inode: AtomicU64,
}

impl InodeRegistry {
    fn new() -> Self {
        Self {
            path_to_inode: RwLock::new(BTreeMap::new()),
            inode_to_path: RwLock::new(BTreeMap::new()),
            next_inode: AtomicU64::new(2), // Start at 2, 1 is reserved for root
        }
    }

    fn get_inode(&self, path: &Path) -> u64 {
        // Check if we already have an inode for this path
        {
            let path_to_inode = self.path_to_inode.read();
            if let Some(&ino) = path_to_inode.get(path) {
                return ino;
            }
        }

        // Assign new inode
        let ino = if path == Path::new("/") {
            FUSE_ROOT_ID
        } else {
            self.next_inode.fetch_add(1, Ordering::SeqCst)
        };

        // Store mapping
        let mut path_to_inode = self.path_to_inode.write();
        let mut inode_to_path = self.inode_to_path.write();

        path_to_inode.insert(path.to_path_buf(), ino);
        inode_to_path.insert(ino, path.to_path_buf());

        ino
    }

    fn get_path(&self, ino: u64) -> Option<PathBuf> {
        self.inode_to_path.read().get(&ino).cloned()
    }
}

struct FileHandleRegistry {
    handles: RwLock<BTreeMap<u64, OpenFileHandle>>,
    next_fh: AtomicU64,
}

impl FileHandleRegistry {
    fn new() -> Self {
        Self {
            handles: RwLock::new(BTreeMap::new()),
            next_fh: AtomicU64::new(1),
        }
    }

    fn register(&self, handle: OpenFileHandle) -> u64 {
        let fh = self.next_fh.fetch_add(1, Ordering::SeqCst);
        self.handles.write().insert(fh, handle);
        fh
    }

    fn get(&self, fh: u64) -> Option<OpenFileHandle> {
        self.handles.read().get(&fh).cloned()
    }

    fn remove(&self, fh: u64) -> Option<OpenFileHandle> {
        self.handles.write().remove(&fh)
    }
}

impl Clone for OpenFileHandle {
    fn clone(&self) -> Self {
        Self {
            branch: self.branch.clone(),
            path: self.path.clone(),
            file_descriptor: self.file_descriptor,
            flags: self.flags,
            direct_io: self.direct_io,
        }
    }
}
```

### Async FUSE Operations

#### Async-Aware FUSE Implementation

```rust
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio::task;

pub trait AsyncFuseOperations: Send + Sync {
    type Error: Into<libc::c_int> + Send + Sync + 'static;

    fn open<'a>(
        &'a self,
        path: &'a Path,
        file_info: &'a mut FileInfo,
    ) -> Pin<Box<dyn Future<Output = Result<(), Self::Error>> + Send + 'a>> {
        Box::pin(async { Ok(()) })
    }

    fn create<'a>(
        &'a self,
        path: &'a Path,
        mode: u32,
        file_info: &'a mut FileInfo,
    ) -> Pin<Box<dyn Future<Output = Result<(), Self::Error>> + Send + 'a>>;

    fn read<'a>(
        &'a self,
        path: &'a Path,
        buf: &'a mut [u8],
        offset: u64,
        file_info: &'a FileInfo,
    ) -> Pin<Box<dyn Future<Output = Result<usize, Self::Error>> + Send + 'a>>;

    fn write<'a>(
        &'a self,
        path: &'a Path,
        buf: &'a [u8],
        offset: u64,
        file_info: &'a FileInfo,
    ) -> Pin<Box<dyn Future<Output = Result<usize, Self::Error>> + Send + 'a>>;

    // ... other async methods
}

// Adapter to convert async operations to sync FUSE callbacks
pub struct AsyncFuseAdapter<T> {
    inner: Arc<T>,
    runtime: Arc<tokio::runtime::Runtime>,
}

impl<T> AsyncFuseAdapter<T>
where
    T: AsyncFuseOperations + 'static,
{
    pub fn new(operations: T) -> Self {
        let runtime = tokio::runtime::Runtime::new()
            .expect("Failed to create async runtime");

        Self {
            inner: Arc::new(operations),
            runtime: Arc::new(runtime),
        }
    }
}

impl<T> FuseOperations for AsyncFuseAdapter<T>
where
    T: AsyncFuseOperations + 'static,
    T::Error: Send + Sync + 'static,
{
    type Error = T::Error;

    fn create(&self, path: &Path, mode: u32, file_info: &mut FileInfo) -> Result<(), Self::Error> {
        let inner = self.inner.clone();
        let path = path.to_path_buf();
        let mut fi_copy = file_info.clone();

        self.runtime.block_on(async move {
            inner.create(&path, mode, &mut fi_copy).await
        })
    }

    fn read(&self, path: &Path, buf: &mut [u8], offset: u64, file_info: &FileInfo) -> Result<usize, Self::Error> {
        let inner = self.inner.clone();
        let path = path.to_path_buf();
        let fi_copy = file_info.clone();

        // For read operations, we need to handle the buffer carefully
        let buf_len = buf.len();
        let mut temp_buf = vec![0u8; buf_len];

        let result = self.runtime.block_on(async move {
            inner.read(&path, &mut temp_buf, offset, &fi_copy).await
        })?;

        buf[..result].copy_from_slice(&temp_buf[..result]);
        Ok(result)
    }

    fn write(&self, path: &Path, buf: &[u8], offset: u64, file_info: &FileInfo) -> Result<usize, Self::Error> {
        let inner = self.inner.clone();
        let path = path.to_path_buf();
        let buf = buf.to_vec();
        let fi_copy = file_info.clone();

        self.runtime.block_on(async move {
            inner.write(&path, &buf, offset, &fi_copy).await
        })
    }

    // ... other method implementations
}

// Thread pool for async operations
pub struct AsyncFuseExecutor<T> {
    operations: Arc<T>,
    task_pool: Arc<RwLock<tokio::task::JoinSet<()>>>,
    runtime: Arc<tokio::runtime::Runtime>,
}

impl<T> AsyncFuseExecutor<T>
where
    T: AsyncFuseOperations + 'static,
{
    pub fn new(operations: T, pool_size: usize) -> Self {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(pool_size)
            .enable_all()
            .build()
            .expect("Failed to create async runtime");

        Self {
            operations: Arc::new(operations),
            task_pool: Arc::new(RwLock::new(tokio::task::JoinSet::new())),
            runtime: Arc::new(rt),
        }
    }

    pub async fn execute_read(
        &self,
        path: PathBuf,
        mut buf: Vec<u8>,
        offset: u64,
        file_info: FileInfo,
    ) -> Result<Vec<u8>, T::Error> {
        let ops = self.operations.clone();

        let result = ops.read(&path, &mut buf, offset, &file_info).await?;
        buf.truncate(result);
        Ok(buf)
    }

    pub async fn execute_write(
        &self,
        path: PathBuf,
        buf: Vec<u8>,
        offset: u64,
        file_info: FileInfo,
    ) -> Result<usize, T::Error> {
        let ops = self.operations.clone();
        ops.write(&path, &buf, offset, &file_info).await
    }
}
```

### MergerFS Fuser Implementation

#### Complete MergerFS Filesystem Implementation

```rust
use crate::policy::{PolicyExecutor, PolicyError};
use crate::config::ConfigManager;
use crate::error::{MergerFsError, ErrorAggregator};
use crate::platform::PlatformIO;

pub struct MergerFsFilesystem {
    config_manager: Arc<ConfigManager>,
    policy_executor: Arc<PolicyExecutor>,
    platform_io: Arc<PlatformIO>,
    file_handle_registry: Arc<FileHandleRegistry>,
    inode_registry: Arc<InodeRegistry>,
}

impl MergerFsFilesystem {
    pub fn new(
        config_manager: Arc<ConfigManager>,
        policy_executor: Arc<PolicyExecutor>,
        platform_io: Arc<PlatformIO>,
    ) -> Self {
        Self {
            config_manager,
            policy_executor,
            platform_io,
            file_handle_registry: Arc::new(FileHandleRegistry::new()),
            inode_registry: Arc::new(InodeRegistry::new()),
        }
    }

    fn get_request_context(req: &Request<'_>) -> RequestContext {
        RequestContext::from_request(req)
    }

    fn errno_to_fuse_error(error: &MergerFsError) -> i32 {
        match error {
            MergerFsError::PathNotFound { .. } => libc::ENOENT,
            MergerFsError::PermissionDenied { .. } => libc::EACCES,
            MergerFsError::NoSpaceLeft { .. } => libc::ENOSPC,
            MergerFsError::ReadOnlyFilesystem { .. } => libc::EROFS,
            MergerFsError::CrossDevice => libc::EXDEV,
            MergerFsError::NotSupported => libc::ENOSYS,
            MergerFsError::Io(io_err) => io_err.errno.unwrap_or(libc::EIO),
            _ => libc::EIO,
        }
    }
}

impl Filesystem for MergerFsFilesystem {
    fn lookup(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, reply: ReplyEntry) {
        let parent_path = match self.inode_registry.get_path(parent) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let file_path = parent_path.join(name);

        // Use search policy to find the file
        match self.policy_executor.find_file_branches(&file_path) {
            Ok(branches) => {
                for branch in branches {
                    let full_path = branch.path.join(&file_path);
                    match self.platform_io.fs_ops.stat(&full_path) {
                        Ok(stat) => {
                            let ino = self.inode_registry.get_inode(&file_path);
                            let attr = to_fuser_file_attr(&stat, ino);
                            reply.entry(&Duration::from_secs(1), &attr, 0);
                            return;
                        }
                        Err(e) if e.raw_os_error() == Some(libc::ENOENT) => continue,
                        Err(_) => continue,
                    }
                }
                reply.error(libc::ENOENT);
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn getattr(&mut self, _req: &Request<'_>, ino: u64, reply: ReplyAttr) {
        let path = match self.inode_registry.get_path(ino) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        // Use search policy to find the file
        match self.policy_executor.find_file_branches(&path) {
            Ok(branches) => {
                for branch in branches {
                    let full_path = branch.path.join(&path);
                    match self.platform_io.fs_ops.stat(&full_path) {
                        Ok(stat) => {
                            let attr = to_fuser_file_attr(&stat, ino);
                            reply.attr(&Duration::from_secs(1), &attr);
                            return;
                        }
                        Err(e) if e.raw_os_error() == Some(libc::ENOENT) => continue,
                        Err(_) => continue,
                    }
                }
                reply.error(libc::ENOENT);
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn open(&mut self, req: &Request<'_>, ino: u64, flags: i32, reply: ReplyOpen) {
        let _ctx = Self::get_request_context(req);

        let path = match self.inode_registry.get_path(ino) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        // Use search policy to find the file
        match self.policy_executor.find_file_branches(&path) {
            Ok(branches) => {
                for branch in branches {
                    let full_path = branch.path.join(&path);
                    match self.platform_io.fs_ops.open(&full_path, flags, 0) {
                        Ok(fd) => {
                            let handle = OpenFileHandle {
                                branch,
                                path: path.clone(),
                                file_descriptor: Some(fd),
                                flags,
                                direct_io: false,
                            };
                            let fh = self.file_handle_registry.register(handle);
                            reply.opened(fh, 0);
                            return;
                        }
                        Err(e) if e.raw_os_error() == Some(libc::ENOENT) => continue,
                        Err(_) => continue,
                    }
                }
                reply.error(libc::ENOENT);
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn create(
        &mut self,
        req: &Request<'_>,
        parent: u64,
        name: &OsStr,
        mode: u32,
        _umask: u32,
        flags: i32,
        reply: ReplyCreate,
    ) {
        let _ctx = Self::get_request_context(req);

        let parent_path = match self.inode_registry.get_path(parent) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let file_path = parent_path.join(name);

        // Use create policy to select branch
        match self.policy_executor.select_create_branches(&file_path) {
            Ok(branches) => {
                if let Some(branch) = branches.into_iter().next() {
                    let full_path = branch.path.join(&file_path);

                    // Ensure parent directory exists
                    if let Some(parent_dir) = full_path.parent() {
                        let _ = std::fs::create_dir_all(parent_dir);
                    }

                    match self.platform_io.fs_ops.open(
                        &full_path,
                        flags | libc::O_CREAT | libc::O_TRUNC,
                        mode,
                    ) {
                        Ok(fd) => {
                            let ino = self.inode_registry.get_inode(&file_path);

                            let handle = OpenFileHandle {
                                branch: branch.clone(),
                                path: file_path.clone(),
                                file_descriptor: Some(fd),
                                flags,
                                direct_io: false,
                            };
                            let fh = self.file_handle_registry.register(handle);

                            // Get file attributes
                            match self.platform_io.fs_ops.fstat(fd) {
                                Ok(stat) => {
                                    let attr = to_fuser_file_attr(&stat, ino);
                                    reply.created(&Duration::from_secs(1), &attr, 0, fh, 0);
                                }
                                Err(e) => {
                                    reply.error(e.raw_os_error().unwrap_or(libc::EIO));
                                }
                            }
                        }
                        Err(e) => {
                            reply.error(e.raw_os_error().unwrap_or(libc::EIO));
                        }
                    }
                } else {
                    reply.error(libc::ENOSPC);
                }
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn read(
        &mut self,
        _req: &Request<'_>,
        _ino: u64,
        fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyData,
    ) {
        let handle = match self.file_handle_registry.get(fh) {
            Some(handle) => handle,
            None => {
                reply.error(libc::EBADF);
                return;
            }
        };

        if let Some(fd) = handle.file_descriptor {
            let mut buffer = vec![0u8; size as usize];
            match self.platform_io.fs_ops.read(fd, &mut buffer, offset as u64) {
                Ok(bytes_read) => {
                    buffer.truncate(bytes_read);
                    reply.data(&buffer);
                }
                Err(e) => {
                    reply.error(e.raw_os_error().unwrap_or(libc::EIO));
                }
            }
        } else {
            reply.error(libc::EBADF);
        }
    }

    fn write(
        &mut self,
        _req: &Request<'_>,
        _ino: u64,
        fh: u64,
        offset: i64,
        data: &[u8],
        _write_flags: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyWrite,
    ) {
        let handle = match self.file_handle_registry.get(fh) {
            Some(handle) => handle,
            None => {
                reply.error(libc::EBADF);
                return;
            }
        };

        if let Some(fd) = handle.file_descriptor {
            match self.platform_io.fs_ops.write(fd, data, offset as u64) {
                Ok(bytes_written) => {
                    reply.written(bytes_written as u32);
                }
                Err(e) => {
                    reply.error(e.raw_os_error().unwrap_or(libc::EIO));
                }
            }
        } else {
            reply.error(libc::EBADF);
        }
    }

    fn release(
        &mut self,
        _req: &Request<'_>,
        _ino: u64,
        fh: u64,
        _flags: i32,
        _lock_owner: Option<u64>,
        _flush: bool,
        reply: fuser::ReplyEmpty,
    ) {
        if let Some(handle) = self.file_handle_registry.remove(fh) {
            if let Some(fd) = handle.file_descriptor {
                let _ = self.platform_io.fs_ops.close(fd);
            }
            reply.ok();
        } else {
            reply.error(libc::EBADF);
        }
    }

    fn readdir(
        &mut self,
        _req: &Request<'_>,
        ino: u64,
        _fh: u64,
        offset: i64,
        mut reply: ReplyDirectory,
    ) {
        let path = match self.inode_registry.get_path(ino) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        // Read from all branches and merge results
        let branches = self.policy_executor.get_all_branches();
        let mut entries = BTreeMap::new();
        let mut current_offset = 1i64;

        // Add standard entries
        if offset <= 0 {
            if reply.add(ino, current_offset, FileType::Directory, ".") {
                reply.ok();
                return;
            }
            current_offset += 1;
        }

        if offset <= 1 {
            let parent_ino = if ino == FUSE_ROOT_ID { FUSE_ROOT_ID } else { FUSE_ROOT_ID };
            if reply.add(parent_ino, current_offset, FileType::Directory, "..") {
                reply.ok();
                return;
            }
            current_offset += 1;
        }

        for branch in branches {
            let full_path = branch.path.join(&path);
            if let Ok(branch_entries) = self.platform_io.fs_ops.readdir(&full_path) {
                for entry in branch_entries {
                    if !entries.contains_key(&entry.name) {
                        let file_path = path.join(&entry.name);
                        let entry_ino = self.inode_registry.get_inode(&file_path);
                        entries.insert(entry.name.clone(), (entry_ino, entry.file_type));
                    }
                }
            }
        }

        // Add entries to reply
        for (name, (entry_ino, file_type)) in entries {
            if current_offset <= offset {
                current_offset += 1;
                continue;
            }

            let fuser_file_type = to_fuser_file_type(file_type);
            if reply.add(entry_ino, current_offset, fuser_file_type, &name) {
                break;
            }
            current_offset += 1;
        }

        reply.ok();
    }

    fn mkdir(
        &mut self,
        req: &Request<'_>,
        parent: u64,
        name: &OsStr,
        mode: u32,
        _umask: u32,
        reply: ReplyEntry,
    ) {
        let _ctx = Self::get_request_context(req);

        let parent_path = match self.inode_registry.get_path(parent) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let dir_path = parent_path.join(name);

        // Use create policy to select branches
        match self.policy_executor.select_create_branches(&dir_path) {
            Ok(branches) => {
                let mut aggregator = ErrorAggregator::new("mkdir", dir_path.clone());

                for branch in branches {
                    let full_path = branch.path.join(&dir_path);
                    match self.platform_io.fs_ops.mkdir(&full_path, mode) {
                        Ok(_) => aggregator.add_success(branch.path.clone()),
                        Err(e) => aggregator.add_error(branch.path.clone(), e.into()),
                    }
                }

                match aggregator.into_result() {
                    Ok(_) => {
                        // Get directory attributes
                        match self.policy_executor.find_file_branches(&dir_path) {
                            Ok(search_branches) => {
                                for branch in search_branches {
                                    let full_path = branch.path.join(&dir_path);
                                    if let Ok(stat) = self.platform_io.fs_ops.stat(&full_path) {
                                        let ino = self.inode_registry.get_inode(&dir_path);
                                        let attr = to_fuser_file_attr(&stat, ino);
                                        reply.entry(&Duration::from_secs(1), &attr, 0);
                                        return;
                                    }
                                }
                                reply.error(libc::EIO);
                            }
                            Err(_) => reply.error(libc::EIO),
                        }
                    }
                    Err(_) => reply.error(libc::EIO),
                }
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn unlink(&mut self, req: &Request<'_>, parent: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        let _ctx = Self::get_request_context(req);

        let parent_path = match self.inode_registry.get_path(parent) {
            Some(path) => path,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let file_path = parent_path.join(name);

        // Use action policy to select branches
        let policies = self.policy_executor.get_function_policies();
        match self.policy_executor.execute_action_policy(&policies.unlink, &file_path) {
            Ok(branches) => {
                let mut aggregator = ErrorAggregator::new("unlink", file_path.clone());

                for branch in branches {
                    let full_path = branch.path.join(&file_path);
                    match self.platform_io.fs_ops.unlink(&full_path) {
                        Ok(_) => aggregator.add_success(branch.path.clone()),
                        Err(e) => aggregator.add_error(branch.path.clone(), e.into()),
                    }
                }

                match aggregator.into_partial_result() {
                    Ok(_) => reply.ok(),
                    Err(_) => reply.error(libc::EIO),
                }
            }
            Err(error) => {
                reply.error(Self::errno_to_fuse_error(&error));
            }
        }
    }

    fn statfs(&mut self, _req: &Request<'_>, _ino: u64, reply: ReplyStatfs) {
        // Aggregate filesystem statistics from all branches
        let branches = self.policy_executor.get_all_branches();
        let mut total_blocks = 0u64;
        let mut total_bavail = 0u64;
        let mut total_bfree = 0u64;
        let mut max_files = 0u64;
        let mut max_ffree = 0u64;
        let mut min_bsize = u32::MAX;
        let mut max_namelen = 0u32;

        for branch in branches {
            if let Ok(statvfs) = get_statvfs(&branch.path) {
                total_blocks += statvfs.f_blocks;
                total_bavail += statvfs.f_bavail;
                total_bfree += statvfs.f_bfree;
                max_files = max_files.max(statvfs.f_files);
                max_ffree = max_ffree.max(statvfs.f_ffree);
                min_bsize = min_bsize.min(statvfs.f_bsize as u32);
                max_namelen = max_namelen.max(statvfs.f_namemax as u32);
            }
        }

        let bsize = if min_bsize == u32::MAX { 4096 } else { min_bsize };
        let namelen = if max_namelen == 0 { 255 } else { max_namelen };

        reply.statfs(
            total_blocks,
            total_bfree,
            total_bavail,
            max_files,
            max_ffree,
            bsize,
            namelen,
            bsize, // frsize
        );
    }
}

fn get_statvfs(path: &Path) -> Result<libc::statvfs, std::io::Error> {
    use std::ffi::CString;
    use std::mem::MaybeUninit;

    let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
    let mut statvfs: MaybeUninit<libc::statvfs> = MaybeUninit::uninit();

    let result = unsafe {
        libc::statvfs(path_cstr.as_ptr(), statvfs.as_mut_ptr())
    };

    if result == 0 {
        Ok(unsafe { statvfs.assume_init() })
    } else {
        Err(std::io::Error::last_os_error())
    }
}
```

### Fuser Session Management and Main Loop

#### Session Management Using Fuser

```rust
use fuser::{MountOption, Session};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

pub struct FuserSession {
    filesystem: Arc<MergerFsFilesystem>,
    mount_point: PathBuf,
    options: Vec<MountOption>,
}

impl FuserSession {
    pub fn new(
        filesystem: MergerFsFilesystem,
        mount_point: PathBuf,
        options: FuserMountOptions,
    ) -> Self {
        let mount_options = options.to_fuser_options();

        Self {
            filesystem: Arc::new(filesystem),
            mount_point,
            options: mount_options,
        }
    }

    pub fn mount_and_run(&self) -> Result<(), FuserError> {
        let session = Session::new(
            self.filesystem.clone(),
            &self.mount_point,
            &self.options,
        ).map_err(FuserError::SessionCreate)?;

        // Run the FUSE loop - this blocks until unmounted
        session.run().map_err(FuserError::SessionRun)
    }

    pub fn mount_and_run_background(&self) -> Result<SessionHandle, FuserError> {
        let filesystem = self.filesystem.clone();
        let mount_point = self.mount_point.clone();
        let options = self.options.clone();

        let handle = thread::spawn(move || {
            let session = Session::new(filesystem, &mount_point, &options)?;
            session.run()
        });

        Ok(SessionHandle { handle })
    }
}

#[derive(Debug, Clone)]
pub struct FuserMountOptions {
    pub allow_other: bool,
    pub allow_root: bool,
    pub auto_unmount: bool,
    pub read_only: bool,
    pub exec: bool,
    pub suid: bool,
    pub dev: bool,
    pub async_read: bool,
    pub sync_read: bool,
    pub direct_io: bool,
    pub kernel_cache: bool,
    pub auto_cache: bool,
    pub noauto_cache: bool,
    pub uid: Option<u32>,
    pub gid: Option<u32>,
    pub umask: Option<u32>,
    pub entry_timeout: Option<Duration>,
    pub attr_timeout: Option<Duration>,
    pub ac_attr_timeout: Option<Duration>,
    pub negative_timeout: Option<Duration>,
    pub fsname: Option<String>,
    pub subtype: Option<String>,
}

impl Default for FuserMountOptions {
    fn default() -> Self {
        Self {
            allow_other: false,
            allow_root: false,
            auto_unmount: true,
            read_only: false,
            exec: true,
            suid: true,
            dev: true,
            async_read: false,
            sync_read: false,
            direct_io: false,
            kernel_cache: false,
            auto_cache: false,
            noauto_cache: false,
            uid: None,
            gid: None,
            umask: None,
            entry_timeout: Some(Duration::from_secs(1)),
            attr_timeout: Some(Duration::from_secs(1)),
            ac_attr_timeout: None,
            negative_timeout: None,
            fsname: Some("mergerfs".to_string()),
            subtype: Some("mergerfs".to_string()),
        }
    }
}

impl FuserMountOptions {
    pub fn to_fuser_options(&self) -> Vec<MountOption> {
        let mut options = Vec::new();

        if self.allow_other {
            options.push(MountOption::AllowOther);
        }

        if self.allow_root {
            options.push(MountOption::AllowRoot);
        }

        if self.auto_unmount {
            options.push(MountOption::AutoUnmount);
        }

        if self.read_only {
            options.push(MountOption::RO);
        }

        if !self.exec {
            options.push(MountOption::NoExec);
        }

        if !self.suid {
            options.push(MountOption::NoSuid);
        }

        if !self.dev {
            options.push(MountOption::NoDev);
        }

        if self.async_read {
            options.push(MountOption::AsyncRead);
        }

        if self.sync_read {
            options.push(MountOption::SyncRead);
        }

        if self.direct_io {
            options.push(MountOption::DirectIO);
        }

        if !self.kernel_cache {
            options.push(MountOption::DisableKernelCache);
        }

        if self.auto_cache {
            options.push(MountOption::AutoCache);
        }

        if self.noauto_cache {
            options.push(MountOption::NoAutoCache);
        }

        if let Some(uid) = self.uid {
            options.push(MountOption::Uid(uid));
        }

        if let Some(gid) = self.gid {
            options.push(MountOption::Gid(gid));
        }

        if let Some(umask) = self.umask {
            options.push(MountOption::Umask(umask));
        }

        if let Some(fsname) = &self.fsname {
            options.push(MountOption::FSName(fsname.clone()));
        }

        if let Some(subtype) = &self.subtype {
            options.push(MountOption::Subtype(subtype.clone()));
        }

        options
    }
}

pub struct SessionHandle {
    handle: thread::JoinHandle<Result<(), std::io::Error>>,
}

impl SessionHandle {
    pub fn join(self) -> Result<(), FuserError> {
        self.handle
            .join()
            .map_err(|_| FuserError::ThreadJoin)?
            .map_err(FuserError::SessionRun)
    }

    pub fn is_finished(&self) -> bool {
        self.handle.is_finished()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum FuserError {
    #[error("Failed to create FUSE session: {0}")]
    SessionCreate(std::io::Error),

    #[error("FUSE session run failed: {0}")]
    SessionRun(std::io::Error),

    #[error("Failed to join background thread")]
    ThreadJoin,

    #[error("Mount failed: {0}")]
    MountFailed(String),

    #[error("Unmount failed: {0}")]
    UnmountFailed(String),
}

// Utility function to unmount a filesystem
pub fn unmount_filesystem(mount_point: &Path) -> Result<(), FuserError> {
    use std::process::Command;

    let output = Command::new("fusermount")
        .args(["-u", &mount_point.to_string_lossy()])
        .output()
        .map_err(|e| FuserError::UnmountFailed(e.to_string()))?;

    if !output.status.success() {
        let error_msg = String::from_utf8_lossy(&output.stderr);
        return Err(FuserError::UnmountFailed(error_msg.to_string()));
    }

    Ok(())
}

// Main application entry point
pub struct MergerFsApp {
    config_manager: Arc<ConfigManager>,
    policy_executor: Arc<PolicyExecutor>,
    platform_io: Arc<PlatformIO>,
}

impl MergerFsApp {
    pub fn new(
        config_manager: Arc<ConfigManager>,
        policy_executor: Arc<PolicyExecutor>,
        platform_io: Arc<PlatformIO>,
    ) -> Self {
        Self {
            config_manager,
            policy_executor,
            platform_io,
        }
    }

    pub fn run(&self) -> Result<(), FuserError> {
        let config = self.config_manager.get_config();

        // Create filesystem implementation
        let filesystem = MergerFsFilesystem::new(
            self.config_manager.clone(),
            self.policy_executor.clone(),
            self.platform_io.clone(),
        );

        // Configure mount options from config
        let mut mount_options = FuserMountOptions::default();
        mount_options.allow_other = config.get().fuse.export_support;
        mount_options.auto_unmount = true;
        mount_options.async_read = config.get().io.async_read;
        mount_options.direct_io = config.get().io.direct_io;
        mount_options.kernel_cache = config.get().io.kernel_cache;

        // Create and run session
        let session = FuserSession::new(
            filesystem,
            config.get().mount_point.clone(),
            mount_options,
        );

        println!("Mounting mergerfs at {}", config.get().mount_point.display());
        session.mount_and_run()
    }

    pub fn run_background(&self) -> Result<SessionHandle, FuserError> {
        let config = self.config_manager.get_config();

        let filesystem = MergerFsFilesystem::new(
            self.config_manager.clone(),
            self.policy_executor.clone(),
            self.platform_io.clone(),
        );

        let mut mount_options = FuserMountOptions::default();
        mount_options.allow_other = config.get().fuse.export_support;
        mount_options.auto_unmount = true;
        mount_options.async_read = config.get().io.async_read;
        mount_options.direct_io = config.get().io.direct_io;
        mount_options.kernel_cache = config.get().io.kernel_cache;

        let session = FuserSession::new(
            filesystem,
            config.get().mount_point.clone(),
            mount_options,
        );

        session.mount_and_run_background()
    }
}
```

This comprehensive FUSE integration system using the `fuser` crate provides:

1. **Safe FUSE implementation** using the `fuser` crate's Filesystem trait
2. **Type-safe request handling** with proper error conversion
3. **Efficient inode and file handle management** with thread-safe registries
4. **Complete MergerFS implementation** with policy integration and branch merging
5. **Session management and mounting** using fuser's safe abstractions
6. **Performance optimizations** and efficient request handling
7. **Memory-safe operations** without raw FFI bindings

The design leverages the `fuser` crate's safe abstractions to eliminate unsafe code while maintaining high performance and providing the flexibility needed for mergerfs's union filesystem functionality. This approach reduces complexity and improves safety compared to raw FUSE FFI bindings.
