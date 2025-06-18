use crate::config::{ConfigRef, StatFSIgnore};
use crate::policy::AllActionPolicy;
use crate::policy::error::PolicyError;
use crate::file_ops::FileManager;
use crate::metadata_ops::MetadataManager;
use crate::file_handle::FileHandleManager;
use crate::xattr::{XattrManager, XattrFlags};
use crate::policy::{FirstFoundSearchPolicy, FirstFoundCreatePolicy};
use crate::config_manager::ConfigManager;
use crate::rename_ops::RenameManager;
use crate::moveonenospc::{MoveOnENOSPCHandler, is_out_of_space_error};
use fuser::{
    FileAttr, FileType, Filesystem, ReplyAttr, ReplyCreate, ReplyData, ReplyDirectory, ReplyEntry, 
    ReplyOpen, ReplyWrite, Request,
};
// Use standard errno constants compatible with MUSL
const ENOENT: i32 = 2;
const EIO: i32 = 5;
const EACCES: i32 = 13;
const ENOTDIR: i32 = 20;
const EINVAL: i32 = 22;
const EROFS: i32 = 30;
const ENOTEMPTY: i32 = 39;
const ENOSYS: i32 = 38;
const ERANGE: i32 = 34;
use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tracing::error;

const TTL: Duration = Duration::from_secs(1);
const CONTROL_FILE_INO: u64 = u64::MAX; // Special inode for /.mergerfs

#[derive(Debug)]
pub struct DirHandle {
    pub path: PathBuf,
    pub ino: u64,
}

pub struct MergerFS {
    pub file_manager: Arc<FileManager>,
    pub metadata_manager: Arc<MetadataManager>,
    pub config: ConfigRef,
    pub file_handle_manager: Arc<FileHandleManager>,
    pub xattr_manager: Arc<XattrManager>,
    pub config_manager: Arc<ConfigManager>,
    pub rename_manager: Arc<RenameManager>,
    pub moveonenospc_handler: Arc<MoveOnENOSPCHandler>,
    inodes: parking_lot::RwLock<HashMap<u64, InodeData>>,
    next_inode: std::sync::atomic::AtomicU64,
    dir_handles: parking_lot::RwLock<HashMap<u64, DirHandle>>,
    next_dir_handle: std::sync::atomic::AtomicU64,
    // Cache for path to inode lookups to reduce lock contention
    path_cache: parking_lot::RwLock<HashMap<String, u64>>,
    // Fast-path cache for root inode (always inode 1)
    root_inode_cache: InodeData,
}

#[derive(Debug, Clone)]
pub struct InodeData {
    pub path: String,
    pub attr: FileAttr,
    pub content_lock: Arc<parking_lot::RwLock<()>>, // Guards file content operations
}

impl MergerFS {
    pub fn new(file_manager: FileManager) -> Self {
        // Create metadata manager with same branches and AllActionPolicy for consistency
        let branches = file_manager.branches.clone();
        let action_policy = Box::new(AllActionPolicy);
        let metadata_manager = MetadataManager::new(branches.clone(), action_policy);
        
        // Create xattr manager with search and action policies
        let xattr_manager = XattrManager::new(
            branches.clone(),
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
        );
        
        let config = crate::config::create_config();
        
        // Create rename manager with appropriate policies
        let rename_manager = RenameManager::new(
            branches,
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config.clone(),
        );
        
        let config_manager = ConfigManager::new(config.clone());
        
        let mut inodes = HashMap::new();
        
        // Root directory inode (always 1)
        let root_attr = FileAttr {
            ino: 1,
            size: 0,
            blocks: 0,
            atime: UNIX_EPOCH,
            mtime: UNIX_EPOCH,
            ctime: UNIX_EPOCH,
            crtime: UNIX_EPOCH,
            kind: FileType::Directory,
            perm: 0o755,
            nlink: 2,
            uid: 1000,
            gid: 1000,
            rdev: 0,
            flags: 0,
            blksize: 512,
        };
        
        inodes.insert(1, InodeData {
            path: "/".to_string(),
            attr: root_attr,
            content_lock: Arc::new(parking_lot::RwLock::new(())),
        });
        
        let mut path_cache = HashMap::new();
        path_cache.insert("/".to_string(), 1);
        
        let moveonenospc_handler = MoveOnENOSPCHandler::new(config.clone());
        
        // Clone root inode data for fast-path cache
        let root_inode_cache = inodes.get(&1).unwrap().clone();
        
        MergerFS {
            file_manager: Arc::new(file_manager),
            metadata_manager: Arc::new(metadata_manager),
            config,
            file_handle_manager: Arc::new(FileHandleManager::new()),
            xattr_manager: Arc::new(xattr_manager),
            config_manager: Arc::new(config_manager),
            rename_manager: Arc::new(rename_manager),
            moveonenospc_handler: Arc::new(moveonenospc_handler),
            inodes: parking_lot::RwLock::new(inodes),
            next_inode: std::sync::atomic::AtomicU64::new(2), // Start at 2, 1 is root
            dir_handles: parking_lot::RwLock::new(HashMap::new()),
            next_dir_handle: std::sync::atomic::AtomicU64::new(1),
            path_cache: parking_lot::RwLock::new(path_cache),
            root_inode_cache,
        }
    }

    pub fn allocate_inode(&self) -> u64 {
        self.next_inode.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    }

    pub fn get_inode_data(&self, ino: u64) -> Option<InodeData> {
        // Fast path for root inode
        if ino == 1 {
            return Some(self.root_inode_cache.clone());
        }
        self.inodes.read().get(&ino).cloned()
    }
    
    pub fn update_inode_size(&self, ino: u64, new_size: u64) {
        let mut inodes = self.inodes.write();
        if let Some(inode_data) = inodes.get_mut(&ino) {
            inode_data.attr.size = new_size;
            inode_data.attr.blocks = (new_size + 511) / 512;
            let now = SystemTime::now();
            inode_data.attr.mtime = now;
            inode_data.attr.ctime = now;
            tracing::debug!("Updated inode {} size to {}", ino, new_size);
        }
    }

    pub fn path_to_inode(&self, path: &str) -> Option<u64> {
        // Check cache first
        if let Some(&ino) = self.path_cache.read().get(path) {
            return Some(ino);
        }
        
        // If not in cache, search in inodes
        let found_inode = {
            let inodes = self.inodes.read();
            inodes.iter()
                .find(|(_, data)| data.path == path)
                .map(|(&ino, _)| ino)
        };
        
        // Update cache if found (no locks held during this)
        if let Some(ino) = found_inode {
            self.path_cache.write().insert(path.to_string(), ino);
        }
        
        found_inode
    }

    pub fn create_file_attr(&self, path: &Path) -> Option<FileAttr> {
        // Get metadata without following symlinks
        let metadata = self.file_manager.get_metadata(path)?;
        
        let now = SystemTime::now();
        
        // Determine file type based on metadata
        let file_type = if metadata.is_dir() {
            FileType::Directory
        } else if metadata.is_symlink() {
            FileType::Symlink
        } else {
            FileType::RegularFile
        };
        
        // Set permissions based on metadata
        #[cfg(unix)]
        let perm = {
            use std::os::unix::fs::MetadataExt;
            metadata.mode() as u16 & 0o777
        };
        #[cfg(not(unix))]
        let perm = if metadata.permissions().readonly() { 0o444 } else { 0o644 };
        
        let nlink = if metadata.is_dir() { 2 } else { 1 };
        let size = metadata.len();

        Some(FileAttr {
            ino: 0, // Will be set by caller
            size,
            blocks: (size + 511) / 512, // Round up to nearest block
            atime: metadata.accessed().unwrap_or(now),
            mtime: metadata.modified().unwrap_or(now),
            ctime: metadata.created().unwrap_or(now),
            crtime: metadata.created().unwrap_or(now),
            kind: file_type,
            perm,
            nlink,
            uid: 1000, // Default user ID for container compatibility
            gid: 1000, // Default group ID for container compatibility
            rdev: 0,
            flags: 0,
            blksize: 512,
        })
    }

    pub fn store_dir_handle(&self, fh: u64, path: PathBuf, ino: u64) {
        self.dir_handles.write().insert(fh, DirHandle { path, ino });
    }

    pub fn allocate_dir_handle(&self) -> u64 {
        self.next_dir_handle.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    }

    pub fn get_dir_handle(&self, fh: u64) -> Option<DirHandle> {
        self.dir_handles.read().get(&fh).cloned()
    }

    pub fn remove_dir_handle(&self, fh: u64) {
        self.dir_handles.write().remove(&fh);
    }
    
    fn insert_inode(&self, ino: u64, path: String, attr: FileAttr) {
        // Insert into inode map first
        self.inodes.write().insert(ino, InodeData { 
            path: path.clone(), 
            attr,
            content_lock: Arc::new(parking_lot::RwLock::new(())),
        });
        // Then update cache separately to avoid holding multiple locks
        self.path_cache.write().insert(path, ino);
    }
    
    fn remove_inode(&self, ino: u64) {
        // Get path first, then remove from both maps separately
        let path = {
            let mut inodes = self.inodes.write();
            inodes.remove(&ino).map(|data| data.path)
        };
        
        if let Some(path) = path {
            self.path_cache.write().remove(&path);
        }
    }
}

impl Clone for DirHandle {
    fn clone(&self) -> Self {
        DirHandle {
            path: self.path.clone(),
            ino: self.ino,
        }
    }
}

impl Filesystem for MergerFS {
    fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::lookup", parent, name = %name_str).entered();
        tracing::debug!("Starting lookup");

        let parent_data = match self.get_inode_data(parent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let child_path = if parent_data.path == "/" {
            format!("/{}", name_str)
        } else {
            format!("{}/{}", parent_data.path, name_str)
        };
        
        // Handle special control file
        if child_path == "/.mergerfs" {
            let attr = FileAttr {
                ino: CONTROL_FILE_INO,
                size: 0,
                blocks: 0,
                atime: SystemTime::now(),
                mtime: SystemTime::now(),
                ctime: SystemTime::now(),
                crtime: SystemTime::now(),
                kind: FileType::RegularFile,
                perm: 0o444, // Read-only for all
                nlink: 1,
                uid: 0, // Owned by root
                gid: 0,
                rdev: 0,
                flags: 0,
                blksize: 512,
            };
            reply.entry(&TTL, &attr, 0);
            return;
        }

        // Check if we already have this inode
        if let Some(ino) = self.path_to_inode(&child_path) {
            if let Some(data) = self.get_inode_data(ino) {
                reply.entry(&TTL, &data.attr, 0);
                return;
            }
        }

        // Try to create attributes for this path
        let path = Path::new(&child_path);
        
        // Try to create attributes (check if file/dir exists)
        if let Some(mut attr) = self.create_file_attr(path) {
            let ino = self.allocate_inode();
            attr.ino = ino;

            self.insert_inode(ino, child_path, attr);
            reply.entry(&TTL, &attr, 0);
        } else {
            reply.error(ENOENT);
        }
    }

    fn getattr(&mut self, _req: &Request, ino: u64, reply: ReplyAttr) {
        let _span = tracing::info_span!("fuse::getattr", ino).entered();
        tracing::info!("Starting getattr");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            let attr = FileAttr {
                ino: CONTROL_FILE_INO,
                size: 0,
                blocks: 0,
                atime: SystemTime::now(),
                mtime: SystemTime::now(),
                ctime: SystemTime::now(),
                crtime: SystemTime::now(),
                kind: FileType::RegularFile,
                perm: 0o444,
                nlink: 1,
                uid: 0,
                gid: 0,
                rdev: 0,
                flags: 0,
                blksize: 512,
            };
            reply.attr(&TTL, &attr);
            return;
        }

        match self.get_inode_data(ino) {
            Some(data) => {
                tracing::info!("Returning attr for inode {}: size={}, path={}", ino, data.attr.size, data.path);
                reply.attr(&TTL, &data.attr)
            },
            None => reply.error(ENOENT),
        }
    }

    fn open(&mut self, _req: &Request, ino: u64, flags: i32, reply: ReplyOpen) {
        let _span = tracing::info_span!("fuse::open", ino, flags).entered();
        tracing::debug!("Starting open");

        match self.get_inode_data(ino) {
            Some(data) => {
                if data.attr.kind == FileType::RegularFile {
                    let path = Path::new(&data.path);
                    
                    // Find which branch has the file using search policy
                    let branch_idx = match self.file_manager.find_first_branch(path) {
                        Ok(branch) => {
                            // Find the index of this branch
                            self.file_manager.branches.iter().position(|b| Arc::ptr_eq(b, &branch))
                        }
                        Err(_) => None, // File doesn't exist in any branch
                    };
                    
                    // Create file handle
                    let fh = self.file_handle_manager.create_handle(ino, PathBuf::from(&data.path), flags, branch_idx);
                    
                    reply.opened(fh, flags as u32);
                } else {
                    // Not a regular file
                    reply.error(EINVAL);
                }
            }
            None => reply.error(ENOENT),
        }
    }

    fn release(
        &mut self, 
        _req: &Request, 
        _ino: u64, 
        fh: u64, 
        _flags: i32, 
        _lock_owner: Option<u64>, 
        _flush: bool, 
        reply: fuser::ReplyEmpty
    ) {
        let _span = tracing::debug_span!("fuse::release", _ino, fh).entered();
        self.file_handle_manager.remove_handle(fh);
        reply.ok();
    }

    fn read(
        &mut self,
        _req: &Request,
        ino: u64,
        fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyData,
    ) {
        let _span = tracing::info_span!("fuse::read", ino, fh, offset, size).entered();
        tracing::info!("Starting read operation");

        // Get the content lock for this inode
        let content_lock = match self.get_inode_data(ino) {
            Some(data) => data.content_lock.clone(),
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        // Acquire read lock to ensure no concurrent truncate/write
        let _content_guard = content_lock.read();

        // Get the path from file handle or inode
        let path_info = self.file_handle_manager.get_handle(fh)
            .map(|h| (h.path, h.branch_idx))
            .or_else(|| {
                self.get_inode_data(ino).map(|data| (PathBuf::from(&data.path), None))
            });

        let (path_buf, _branch_idx) = match path_info {
            Some(info) => info,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = path_buf.as_path();
        
        // Find the file and read from it
        tracing::info!("Looking for file at path: {:?}", path);
        match self.file_manager.find_first_branch(path) {
            Ok(branch) => {
                let full_path = branch.full_path(path);
                tracing::info!("Found file at branch path: {:?}", full_path);
                use std::fs::File;
                use std::io::{Read, Seek, SeekFrom};
                
                match File::open(&full_path) {
                    Ok(mut file) => {
                        // Seek to the requested offset
                        if offset > 0 {
                            if let Err(e) = file.seek(SeekFrom::Start(offset as u64)) {
                                error!("Failed to seek: {:?}", e);
                                reply.error(EIO);
                                return;
                            }
                        }
                        
                        // Read the requested amount of data
                        let mut buffer = vec![0u8; size as usize];
                        match file.read(&mut buffer) {
                            Ok(n) => {
                                tracing::info!("Read {} bytes from file (requested {})", n, size);
                                buffer.truncate(n);
                                reply.data(&buffer);
                            }
                            Err(e) => {
                                error!("Read failed: {:?}", e);
                                reply.error(EIO);
                            }
                        }
                    }
                    Err(e) => {
                        error!("Failed to open file for reading: {:?}", e);
                        reply.error(EIO);
                    }
                }
            }
            Err(e) => {
                error!("Read failed for {:?}: {:?}", path, e);
                reply.error(EIO);
            }
        }
    }

    fn opendir(&mut self, _req: &Request, ino: u64, flags: i32, reply: ReplyOpen) {
        let _span = tracing::debug_span!("fuse::opendir", ino, flags).entered();
        tracing::debug!("Starting opendir");

        // Check if it's a directory
        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        if data.attr.kind != FileType::Directory {
            reply.error(ENOTDIR);
            return;
        }

        // Store directory handle
        let fh = self.allocate_dir_handle();
        self.store_dir_handle(fh, PathBuf::from(&data.path), ino);

        reply.opened(fh, flags as u32);
    }

    fn releasedir(&mut self, _req: &Request, _ino: u64, fh: u64, _flags: i32, reply: fuser::ReplyEmpty) {
        let _span = tracing::debug_span!("fuse::releasedir", _ino, fh).entered();
        self.remove_dir_handle(fh);
        reply.ok();
    }

    fn readdir(&mut self, _req: &Request, ino: u64, fh: u64, offset: i64, mut reply: ReplyDirectory) {
        let _span = tracing::debug_span!("fuse::readdir", ino, fh, offset).entered();
        tracing::debug!("Starting readdir");

        // Get directory path and verify it's a directory without holding locks
        let dir_path = {
            // Get the directory path from the handle or inode
            let path = if fh > 0 {
                match self.get_dir_handle(fh) {
                    Some(handle) => handle.path.to_string_lossy().to_string(),
                    None => {
                        reply.error(EINVAL);
                        return;
                    }
                }
            } else {
                // No handle provided, use inode lookup
                match self.get_inode_data(ino) {
                    Some(data) => data.path.clone(),
                    None => {
                        reply.error(ENOENT);
                        return;
                    }
                }
            };

            // Verify it's a directory
            let data = match self.get_inode_data(ino) {
                Some(data) => data,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };

            if data.attr.kind != FileType::Directory {
                reply.error(ENOTDIR);
                return;
            }
            
            data.path
        };

        // Start with standard entries
        let mut entries = vec![
            (1, FileType::Directory, ".".to_string()),
            (1, FileType::Directory, "..".to_string()),
        ];

        // Add control file to root directory listing
        if dir_path == "/" {
            entries.push((CONTROL_FILE_INO, FileType::RegularFile, ".mergerfs".to_string()));
        }
        
        // Get union directory listing (no locks held during I/O)
        let path = Path::new(&dir_path);
        match self.file_manager.list_directory(path) {
            Ok(dir_entries) => {
                for entry_name in dir_entries {
                    // Create a path for this entry to check if it's a directory
                    let entry_path = if dir_path == "/" {
                        format!("/{}", entry_name)
                    } else {
                        format!("{}/{}", dir_path, entry_name)
                    };
                    
                    // Determine if it's a file or directory by checking any branch
                    let mut file_type = FileType::RegularFile;
                    for branch in &self.file_manager.branches {
                        let full_path = branch.full_path(Path::new(&entry_path));
                        if full_path.exists() {
                            if full_path.is_dir() {
                                file_type = FileType::Directory;
                            }
                            break; // Found it in one branch, that's enough
                        }
                    }
                    
                    // Use a dummy inode for now - in a real implementation we'd
                    // need to track these properly
                    let dummy_ino = 2; // Not ideal, but works for basic functionality
                    entries.push((dummy_ino, file_type, entry_name));
                }
            }
            Err(e) => {
                error!("Failed to list directory contents: {:?}", e);
                // Fall back to just . and .. entries
            }
        }

        // Return entries starting from the requested offset
        for (i, (ino, file_type, name)) in entries.into_iter().enumerate().skip(offset as usize) {
            if reply.add(ino, (i + 1) as i64, file_type, &name) {
                break;
            }
        }
        reply.ok();
    }

    fn create(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        mode: u32,
        umask: u32,
        flags: i32,
        reply: ReplyCreate,
    ) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::create", parent, name = %name_str, mode = %format!("{:o}", mode), umask = %format!("{:o}", umask), flags = %format!("0x{:x}", flags)).entered();
        tracing::debug!("Starting create operation");

        // Get parent path without holding lock during file creation
        let file_path = {
            let parent_data = match self.get_inode_data(parent) {
                Some(data) => data,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };
            
            let name_str = match name.to_str() {
                Some(s) => s,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };
            
            let parent_path = parent_data.path.clone();
            if parent_path == "/" {
                format!("/{}", name_str)
            } else {
                format!("{}/{}", parent_path, name_str)
            }
        };

        // Create empty file using file manager (no locks held)
        let path = Path::new(&file_path);
        tracing::debug!("Creating file at path: {:?}", file_path);
        
        match self.file_manager.create_file(path, &[]) {
            Ok(_) => {
                tracing::info!("File created successfully at {:?}", file_path);
                // Create file attributes (no locks held during I/O)
                if let Some(mut attr) = self.create_file_attr(path) {
                    let ino = self.allocate_inode();
                    attr.ino = ino;

                    // Insert inode with minimal lock time
                    self.insert_inode(ino, file_path.clone(), attr);
                    
                    // Create a file handle for the newly created file
                    // Find which branch the file was created on
                    let branch_idx = self.file_manager.branches.iter().position(|branch| {
                        branch.full_path(path).exists()
                    });
                    
                    let fh = self.file_handle_manager.create_handle(
                        ino,
                        PathBuf::from(&file_path),
                        flags,
                        branch_idx
                    );
                    
                    tracing::debug!("Created file handle {} for new file {:?}", fh, file_path);
                    
                    // Return the file handle in the reply
                    reply.created(&TTL, &attr, 0, fh, flags as u32);
                } else {
                    reply.error(EIO);
                }
            }
            Err(e) => {
                error!("Failed to create file at {:?}: {:?}", file_path, e);
                let errno = e.errno();
                tracing::debug!("Returning errno {} for create failure", errno);
                reply.error(errno);
            }
        }
    }

    fn write(
        &mut self,
        _req: &Request,
        ino: u64,
        fh: u64,
        offset: i64,
        data: &[u8],
        write_flags: u32,
        flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyWrite,
    ) {
        let _span = tracing::info_span!("fuse::write", ino, fh, offset, len = data.len(), write_flags = %format!("0x{:x}", write_flags), flags = %format!("0x{:x}", flags)).entered();
        tracing::debug!("Starting write operation");

        // Get the content lock for this inode
        let content_lock = match self.get_inode_data(ino) {
            Some(data) => data.content_lock.clone(),
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        // Acquire write lock to ensure exclusive access during write
        let _content_guard = content_lock.write();

        // Get file path and branch info without holding locks during I/O
        let (path_buf, branch_idx) = {
            // Try to get file handle first
            if let Some(handle) = self.file_handle_manager.get_handle(fh) {
                tracing::debug!("Using file handle {} for path {:?}, branch {:?}", fh, handle.path, handle.branch_idx);
                (handle.path.clone(), handle.branch_idx)
            } else {
                tracing::debug!("No file handle found for fh {}, falling back to inode lookup", fh);
                // Fallback to using inode data
                let inode_data = match self.get_inode_data(ino) {
                    Some(data) => data,
                    None => {
                        reply.error(ENOENT);
                        return;
                    }
                };
                (PathBuf::from(&inode_data.path), None)
            }
        };
        
        let path = path_buf.as_path();
        
        // If we have a file handle with a specific branch, write to that branch
        tracing::debug!("Writing to path {:?} with branch_idx {:?}", path, branch_idx);
        let result = if let Some(branch_idx) = branch_idx {
                if branch_idx < self.file_manager.branches.len() {
                    let branch = &self.file_manager.branches[branch_idx];
                    if branch.allows_create() {
                        let full_path = branch.full_path(path);
                        
                        // Write directly to the specific branch
                        use std::fs::OpenOptions;
                        use std::io::{Seek, SeekFrom, Write};
                        
                        match OpenOptions::new()
                            .write(true)
                            .open(&full_path) {
                            Ok(mut file) => {
                                // Seek to the requested offset
                                if let Err(e) = file.seek(SeekFrom::Start(offset as u64)) {
                                    tracing::error!("Failed to seek: {:?}", e);
                                    Err(PolicyError::IoError(std::io::Error::new(
                                        std::io::ErrorKind::Other,
                                        format!("Seek failed: {}", e)
                                    )))
                                } else {
                                    // Write the data
                                    match file.write_all(data) {
                                        Ok(_) => {
                                            tracing::debug!("Successfully wrote {} bytes to branch {}", data.len(), branch_idx);
                                            Ok(data.len())
                                        }
                                        Err(e) => {
                                            tracing::error!("Write failed: {:?}", e);
                                            if is_out_of_space_error(&e) {
                                                tracing::info!("Detected out of space error on branch {}", branch_idx);
                                                Err(PolicyError::NoSpace)
                                            } else {
                                                Err(PolicyError::IoError(e))
                                            }
                                        }
                                    }
                                }
                            }
                            Err(e) => {
                                tracing::error!("Failed to open file for writing on branch {}: {:?}", branch_idx, e);
                                Err(PolicyError::IoError(e))
                            }
                        }
                    } else {
                        tracing::error!("Branch {} does not allow writes", branch_idx);
                        Err(PolicyError::ReadOnlyFilesystem)
                    }
                } else {
                    tracing::error!("Invalid branch index: {}", branch_idx);
                    Err(PolicyError::PathNotFound)
                }
        } else {
            // No specific branch, find existing file to write to
            tracing::debug!("Finding existing file for write (no specific branch)");
            match self.file_manager.find_first_branch(path) {
                Ok(branch) => {
                    let full_path = branch.full_path(path);
                    use std::fs::OpenOptions;
                    use std::io::{Seek, SeekFrom, Write};
                    
                    match OpenOptions::new()
                        .write(true)
                        .open(&full_path) {
                        Ok(mut file) => {
                            if let Err(e) = file.seek(SeekFrom::Start(offset as u64)) {
                                Err(PolicyError::IoError(std::io::Error::new(
                                    std::io::ErrorKind::Other,
                                    format!("Seek failed: {}", e)
                                )))
                            } else {
                                match file.write_all(data) {
                                    Ok(_) => Ok(data.len()),
                                    Err(e) => Err(PolicyError::IoError(e))
                                }
                            }
                        }
                        Err(e) => Err(PolicyError::IoError(e))
                    }
                }
                Err(e) => Err(e)
            }
        };
        
        match result {
            Ok(written) => {
                tracing::info!("Successfully wrote {} bytes", written);
                
                // Update inode size after successful write
                // The new size should be at least offset + written bytes
                let new_size = (offset as u64) + (written as u64);
                
                // Get current size to see if we need to extend
                if let Some(current_data) = self.get_inode_data(ino) {
                    let updated_size = std::cmp::max(current_data.attr.size, new_size);
                    self.update_inode_size(ino, updated_size);
                }
                
                reply.written(written as u32);
            }
            Err(e) => {
                // Handle moveonenospc if enabled
                if matches!(&e, PolicyError::NoSpace) && self.config.read().moveonenospc.enabled {
                    tracing::info!("ENOSPC detected, attempting moveonenospc");
                    
                    // Attempt to move file to branch with more space
                    // We need to pass the current branch index and branches
                    let current_branch_idx = if let Some(idx) = branch_idx {
                        idx
                    } else {
                        // Find which branch has the file
                        self.file_manager.branches.iter().position(|branch| {
                            branch.full_path(path).exists()
                        }).unwrap_or(0)
                    };
                    
                    match self.moveonenospc_handler.move_file_on_enospc(
                        path,
                        current_branch_idx,
                        &self.file_manager.branches,
                        self.file_manager.create_policy.as_ref(),
                        None, // No file descriptor available here
                    ) {
                        Ok(move_result) => {
                            let new_branch_idx = move_result.new_branch_idx;
                            tracing::info!("Successfully moved file to branch {}, retrying write", new_branch_idx);
                            
                            // File handle will already point to the new location after move
                            
                            // Retry write on new branch
                            let retry_result = if new_branch_idx < self.file_manager.branches.len() {
                                let branch = &self.file_manager.branches[new_branch_idx];
                                let full_path = branch.full_path(path);
                                
                                use std::fs::OpenOptions;
                                use std::io::{Seek, SeekFrom, Write};
                                
                                match OpenOptions::new()
                                    .write(true)
                                    .open(&full_path) {
                                    Ok(mut file) => {
                                        if let Err(e) = file.seek(SeekFrom::Start(offset as u64)) {
                                            Err(PolicyError::IoError(std::io::Error::new(
                                                std::io::ErrorKind::Other,
                                                format!("Seek failed: {}", e)
                                            )))
                                        } else {
                                            match file.write_all(data) {
                                                Ok(_) => Ok(data.len()),
                                                Err(e) => Err(PolicyError::IoError(e))
                                            }
                                        }
                                    }
                                    Err(e) => Err(PolicyError::IoError(e))
                                }
                            } else {
                                Err(PolicyError::PathNotFound)
                            };
                            
                            match retry_result {
                                Ok(written) => {
                                    tracing::info!("Successfully wrote {} bytes after moveonenospc", written);
                                    
                                    // Update inode size after successful write
                                    let new_size = (offset as u64) + (written as u64);
                                    if let Some(current_data) = self.get_inode_data(ino) {
                                        let updated_size = std::cmp::max(current_data.attr.size, new_size);
                                        self.update_inode_size(ino, updated_size);
                                    }
                                    
                                    reply.written(written as u32);
                                }
                                Err(retry_e) => {
                                    error!("Write failed after moveonenospc: {:?}", retry_e);
                                    let errno = retry_e.errno();
                                    reply.error(errno);
                                }
                            }
                        }
                        Err(move_e) => {
                            error!("moveonenospc failed: {:?}", move_e);
                            // Return original error
                            let errno = e.errno();
                            reply.error(errno);
                        }
                    }
                } else {
                    error!("Write failed for {:?}: {:?}", path, e);
                    let errno = e.errno();
                    tracing::debug!("Returning errno {} for write failure", errno);
                    reply.error(errno);
                }
            }
        }
    }

    fn unlink(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::unlink", parent, name = %name_str).entered();
        tracing::debug!("Starting unlink operation");

        let parent_data = match self.get_inode_data(parent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let file_path = if parent_data.path == "/" {
            format!("/{}", name_str)
        } else {
            format!("{}/{}", parent_data.path, name_str)
        };

        let path = Path::new(&file_path);
        tracing::debug!("Unlinking file at path: {:?}", file_path);
        match self.file_manager.remove_file(path) {
            Ok(_) => {
                tracing::info!("File unlinked successfully: {:?}", file_path);
                // Remove from inode cache if present
                if let Some(ino) = self.path_to_inode(&file_path) {
                    self.remove_inode(ino);
                }
                reply.ok();
            }
            Err(e) => {
                error!("Failed to unlink file at {:?}: {:?}", file_path, e);
                reply.error(EIO);
            }
        }
    }

    fn mkdir(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        mode: u32,
        umask: u32,
        reply: ReplyEntry,
    ) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::mkdir", parent, name = %name_str, mode = %format!("{:o}", mode), umask = %format!("{:o}", umask)).entered();
        tracing::debug!("Starting mkdir operation");

        // Get parent path without holding lock during directory creation
        let dir_path = {
            let parent_data = match self.get_inode_data(parent) {
                Some(data) => data,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };
            
            let name_str = match name.to_str() {
                Some(s) => s,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };
            
            let parent_path = parent_data.path.clone();
            if parent_path == "/" {
                format!("/{}", name_str)
            } else {
                format!("{}/{}", parent_path, name_str)
            }
        };

        // Create directory using file manager (no locks held)
        let path = Path::new(&dir_path);
        tracing::debug!("Creating directory at path: {:?}", dir_path);
        
        match self.file_manager.create_directory(path) {
            Ok(_) => {
                tracing::info!("Directory created successfully at {:?}", dir_path);
                // Create directory attributes (no locks held during I/O)
                if let Some(mut attr) = self.create_file_attr(path) {
                    let ino = self.allocate_inode();
                    attr.ino = ino;

                    // Insert inode with minimal lock time
                    self.insert_inode(ino, dir_path, attr);
                    reply.entry(&TTL, &attr, 0);
                } else {
                    reply.error(EIO);
                }
            }
            Err(e) => {
                error!("Failed to create directory at {:?}: {:?}", dir_path, e);
                tracing::debug!("Directory creation error details: {:?}", e);
                reply.error(EIO);
            }
        }
    }

    fn rmdir(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::rmdir", parent, name = %name_str).entered();
        tracing::debug!("Starting rmdir operation");

        let parent_data = match self.get_inode_data(parent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let dir_path = if parent_data.path == "/" {
            format!("/{}", name_str)
        } else {
            format!("{}/{}", parent_data.path, name_str)
        };

        let path = Path::new(&dir_path);
        tracing::debug!("Removing directory at path: {:?}", dir_path);
        match self.file_manager.remove_directory(path) {
            Ok(_) => {
                tracing::info!("Directory removed successfully: {:?}", dir_path);
                // Remove from inode cache if present
                if let Some(ino) = self.path_to_inode(&dir_path) {
                    self.remove_inode(ino);
                }
                reply.ok();
            }
            Err(e) => {
                error!("Failed to remove directory at {:?}: {:?}", dir_path, e);
                let errno = if e.to_string().contains("not empty") {
                    ENOTEMPTY
                } else {
                    EIO
                };
                reply.error(errno);
            }
        }
    }

    fn setattr(&mut self, _req: &Request, ino: u64, mode: Option<u32>, uid: Option<u32>, gid: Option<u32>, size: Option<u64>, atime: Option<fuser::TimeOrNow>, mtime: Option<fuser::TimeOrNow>, _ctime: Option<SystemTime>, _fh: Option<u64>, _crtime: Option<SystemTime>, _chgtime: Option<SystemTime>, _bkuptime: Option<SystemTime>, _flags: Option<u32>, reply: ReplyAttr) {
        let _span = tracing::info_span!("fuse::setattr", ino).entered();
        tracing::debug!("Starting setattr operation");

        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&data.path);
        
        // Get content lock if we're changing size (truncating)
        let _content_guard = if size.is_some() {
            Some(data.content_lock.write())
        } else {
            None
        };
        
        // Handle mode changes
        if let Some(mode) = mode {
            if let Err(e) = self.metadata_manager.chmod(path, mode) {
                error!("chmod failed for {:?}: {:?}", data.path, e);
                reply.error(EIO);
                return;
            }
        }
        
        // Handle ownership changes
        if uid.is_some() || gid.is_some() {
            // Use existing values if not specified
            let current_attr = &data.attr;
            let new_uid = uid.unwrap_or(current_attr.uid);
            let new_gid = gid.unwrap_or(current_attr.gid);
            
            if let Err(e) = self.metadata_manager.chown(path, new_uid, new_gid) {
                error!("chown failed for {:?}: {:?}", data.path, e);
                reply.error(EIO);
                return;
            }
        }
        
        // Handle size changes (truncate) - lock is held if size.is_some()
        if let Some(size) = size {
            if let Err(e) = self.file_manager.truncate_file(path, size) {
                error!("truncate failed for {:?}: {:?}", data.path, e);
                reply.error(EIO);
                return;
            }
        }
        
        // Handle time changes
        if let (Some(atime_val), Some(mtime_val)) = (atime, mtime) {
            let atime_sys = match atime_val {
                fuser::TimeOrNow::SpecificTime(time) => time,
                fuser::TimeOrNow::Now => SystemTime::now(),
            };
            let mtime_sys = match mtime_val {
                fuser::TimeOrNow::SpecificTime(time) => time,
                fuser::TimeOrNow::Now => SystemTime::now(),
            };
            if let Err(e) = self.metadata_manager.utimens(path, atime_sys, mtime_sys) {
                error!("utimens failed for {:?}: {:?}", data.path, e);
                reply.error(EIO);
                return;
            }
        }
        
        // Update cached attributes
        if let Some(mut new_attr) = self.create_file_attr(path) {
            new_attr.ino = ino;
            let path_str = data.path.clone();
            self.insert_inode(ino, path_str, new_attr);
            reply.attr(&TTL, &new_attr);
        } else {
            reply.error(EIO);
        }
    }


    fn rename(&mut self, _req: &Request, parent: u64, name: &OsStr, newparent: u64, newname: &OsStr, flags: u32, reply: fuser::ReplyEmpty) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let newname_str = newname.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::rename", parent, name = %name_str, newparent, newname = %newname_str, flags).entered();
        tracing::debug!("Starting rename operation");

        // Get parent directory paths
        let parent_data = match self.get_inode_data(parent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let newparent_data = match self.get_inode_data(newparent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        let newname_str = match newname.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        // Build full paths
        let old_path = if parent_data.path == "/" {
            format!("/{}", name_str)
        } else {
            format!("{}/{}", parent_data.path, name_str)
        };

        let new_path = if newparent_data.path == "/" {
            format!("/{}", newname_str)
        } else {
            format!("{}/{}", newparent_data.path, newname_str)
        };

        tracing::debug!("Renaming {:?} to {:?}", old_path, new_path);

        // Use rename manager to handle the rename
        match self.rename_manager.rename(Path::new(&old_path), Path::new(&new_path)) {
            Ok(_) => {
                tracing::info!("Rename successful: {:?} -> {:?}", old_path, new_path);
                // Update inode cache if the old path was cached
                if let Some(ino) = self.path_to_inode(&old_path) {
                    // Get the old inode data
                    if let Some(mut inode_data) = self.get_inode_data(ino) {
                        // Remove old entry
                        self.remove_inode(ino);
                        // Update path and reinsert
                        inode_data.path = new_path;
                        self.insert_inode(ino, inode_data.path, inode_data.attr);
                    }
                }
                reply.ok();
            }
            Err(e) => {
                error!("Rename failed: {:?}", e);
                reply.error(EIO);
            }
        }
    }

    fn statfs(&mut self, _req: &Request, _ino: u64, reply: fuser::ReplyStatfs) {
        let _span = tracing::debug_span!("fuse::statfs", _ino).entered();
        tracing::debug!("Starting statfs operation");

        let config = self.config.read();
        let ignore = config.statfs_ignore;
        
        // Get aggregate stats from all branches
        let mut total_blocks: u64 = 0;
        let mut total_bavail: u64 = 0;
        let mut total_bfree: u64 = 0;
        let mut total_files: u64 = 0;
        let mut total_ffree: u64 = 0;
        let mut min_frsize: u32 = u32::MAX;
        let mut min_bsize: u32 = u32::MAX;
        let mut min_namelen: u32 = u32::MAX;
        
        for branch in &self.file_manager.branches {
            // Skip branches based on ignore setting
            match ignore {
                StatFSIgnore::ReadOnly if !branch.allows_create() => continue,
                StatFSIgnore::NoCreate if !branch.allows_create() => continue,
                _ => {}
            }
            
            // Get statfs info from the branch
            let full_path = branch.path.as_path();
            if let Ok(statvfs) = nix::sys::statvfs::statvfs(full_path) {
                total_blocks += statvfs.blocks();
                total_bavail += statvfs.blocks_available();
                total_bfree += statvfs.blocks_free();
                total_files += statvfs.files();
                total_ffree += statvfs.files_free();
                
                min_frsize = min_frsize.min(statvfs.fragment_size() as u32);
                min_bsize = min_bsize.min(statvfs.block_size() as u32);
                min_namelen = min_namelen.min(statvfs.name_max() as u32);
            }
        }
        
        // Use minimum values if we didn't find any valid stats
        if min_frsize == u32::MAX { min_frsize = 512; }
        if min_bsize == u32::MAX { min_bsize = 4096; }
        if min_namelen == u32::MAX { min_namelen = 255; }
        
        reply.statfs(
            total_blocks,
            total_bfree,
            total_bavail,
            total_files,
            total_ffree,
            min_bsize,
            min_namelen,
            min_frsize,
        );
    }


    fn getxattr(&mut self, _req: &Request, ino: u64, name: &OsStr, size: u32, reply: fuser::ReplyXattr) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::getxattr", ino, name = %name_str, size).entered();
        tracing::debug!("Starting getxattr operation");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            reply.error(ENOTSUP);
            return;
        }

        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        let path = Path::new(&data.path);
        match self.xattr_manager.get_xattr(path, name_str) {
            Ok(value) => {
                if size == 0 {
                    // Caller wants to know the size
                    reply.size(value.len() as u32);
                } else if size < value.len() as u32 {
                    // Buffer too small
                    reply.error(ERANGE);
                } else {
                    // Return the value
                    reply.data(&value);
                }
            }
            Err(e) => {
                let errno = e.errno();
                reply.error(errno);
            }
        }
    }

    fn setxattr(&mut self, _req: &Request, ino: u64, name: &OsStr, value: &[u8], flags: i32, _position: u32, reply: fuser::ReplyEmpty) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::setxattr", ino, name = %name_str, value_len = value.len(), flags).entered();
        tracing::debug!("Starting setxattr operation");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            reply.error(ENOTSUP);
            return;
        }

        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        // Convert FUSE flags to XattrFlags
        let xattr_flags = if flags & 1 != 0 {
            XattrFlags::Create
        } else if flags & 2 != 0 {
            XattrFlags::Replace
        } else {
            XattrFlags::None
        };

        let path = Path::new(&data.path);
        match self.xattr_manager.set_xattr(path, name_str, value, xattr_flags) {
            Ok(_) => {
                tracing::info!("setxattr successful for {:?}", data.path);
                reply.ok();
            }
            Err(e) => {
                error!("setxattr failed for {:?}: {:?}", data.path, e);
                let errno = e.errno();
                reply.error(errno);
            }
        }
    }

    fn listxattr(&mut self, _req: &Request, ino: u64, size: u32, reply: fuser::ReplyXattr) {
        let _span = tracing::info_span!("fuse::listxattr", ino, size).entered();
        tracing::debug!("Starting listxattr operation");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            if size == 0 {
                reply.size(0);
            } else {
                reply.data(&[]);
            }
            return;
        }

        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&data.path);
        match self.xattr_manager.list_xattr(path) {
            Ok(names) => {
                // Calculate total size needed (each name + null terminator)
                let total_size: usize = names.iter().map(|n| n.len() + 1).sum();
                
                if size == 0 {
                    // Caller wants to know the size
                    reply.size(total_size as u32);
                } else if (size as usize) < total_size {
                    // Buffer too small
                    reply.error(ERANGE);
                } else {
                    // Build the response buffer
                    let mut buffer = Vec::with_capacity(total_size);
                    for name in names {
                        buffer.extend_from_slice(name.as_bytes());
                        buffer.push(0); // null terminator
                    }
                    reply.data(&buffer);
                }
            }
            Err(e) => {
                error!("listxattr failed for {:?}: {:?}", data.path, e);
                let errno = e.errno();
                reply.error(errno);
            }
        }
    }

    fn removexattr(&mut self, _req: &Request, ino: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        let name_str = name.to_str().unwrap_or("<invalid>");
        let _span = tracing::info_span!("fuse::removexattr", ino, name = %name_str).entered();
        tracing::debug!("Starting removexattr operation");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            reply.error(ENOTSUP);
            return;
        }

        let data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        let path = Path::new(&data.path);
        match self.xattr_manager.remove_xattr(path, name_str) {
            Ok(_) => {
                tracing::info!("removexattr successful for {:?}", data.path);
                reply.ok();
            }
            Err(e) => {
                error!("removexattr failed for {:?}: {:?}", data.path, e);
                let errno = e.errno();
                reply.error(errno);
            }
        }
    }

    fn access(&mut self, _req: &Request, ino: u64, mask: i32, reply: fuser::ReplyEmpty) {
        let _span = tracing::debug_span!("fuse::access", ino, mask = %format!("0x{:x}", mask)).entered();
        tracing::debug!("Starting access check");

        // Handle special control file
        if ino == CONTROL_FILE_INO {
            // Control file is readable for all
            if mask & 2 != 0 || mask & 4 != 0 {
                // Write or execute requested
                reply.error(EACCES);
            } else {
                reply.ok();
            }
            return;
        }

        let _data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        // For now, always allow access
        // TODO: Implement proper access control with actual uid/gid
        reply.ok()
    }
}

// Define errno constants for xattr operations
const ENODATA: i32 = 61;
const ENOTSUP: i32 = 95;