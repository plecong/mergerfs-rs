use crate::config::{ConfigRef, StatFSIgnore};
use crate::policy::{AllActionPolicy, PolicyError};
use crate::file_ops::FileManager;
use crate::metadata_ops::MetadataManager;
use crate::file_handle::FileHandleManager;
use crate::xattr::{XattrManager, XattrError, XattrFlags};
use crate::policy::{FirstFoundSearchPolicy};
use crate::config_manager::{ConfigManager, ConfigError};
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
use tracing::{debug, error, info, warn};

const TTL: Duration = Duration::from_secs(1);
const CONTROL_FILE_INO: u64 = u64::MAX; // Special inode for /.mergerfs

pub struct MergerFS {
    pub file_manager: Arc<FileManager>,
    pub metadata_manager: Arc<MetadataManager>,
    pub config: ConfigRef,
    pub file_handle_manager: Arc<FileHandleManager>,
    pub xattr_manager: Arc<XattrManager>,
    pub config_manager: Arc<ConfigManager>,
    inodes: parking_lot::RwLock<HashMap<u64, InodeData>>,
    next_inode: std::sync::atomic::AtomicU64,
}

#[derive(Debug, Clone)]
pub struct InodeData {
    pub path: String,
    pub attr: FileAttr,
}

impl MergerFS {
    pub fn new(file_manager: FileManager) -> Self {
        // Create metadata manager with same branches and AllActionPolicy for consistency
        let branches = file_manager.branches.clone();
        let action_policy = Box::new(AllActionPolicy);
        let metadata_manager = MetadataManager::new(branches.clone(), action_policy);
        
        // Create xattr manager with search and action policies
        let xattr_manager = XattrManager::new(
            branches,
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
        );
        
        let config = crate::config::create_config();
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
            uid: 1000, // Default user ID for Alpine/containers
            gid: 1000, // Default group ID for Alpine/containers
            rdev: 0,
            flags: 0,
            blksize: 512,
        };
        
        inodes.insert(1, InodeData {
            path: "/".to_string(),
            attr: root_attr,
        });
        
        Self {
            file_manager: Arc::new(file_manager),
            metadata_manager: Arc::new(metadata_manager),
            config,
            file_handle_manager: Arc::new(FileHandleManager::new()),
            xattr_manager: Arc::new(xattr_manager),
            config_manager: Arc::new(config_manager),
            inodes: parking_lot::RwLock::new(inodes),
            next_inode: std::sync::atomic::AtomicU64::new(2),
        }
    }

    pub fn allocate_inode(&self) -> u64 {
        self.next_inode.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    }

    pub fn get_inode_data(&self, ino: u64) -> Option<InodeData> {
        self.inodes.read().get(&ino).cloned()
    }

    pub fn path_to_inode(&self, path: &str) -> Option<u64> {
        let inodes = self.inodes.read();
        for (&ino, data) in inodes.iter() {
            if data.path == path {
                return Some(ino);
            }
        }
        None
    }

    pub fn create_file_attr(&self, path: &Path, is_dir: bool) -> Option<FileAttr> {
        // Check if file exists in any branch
        if !is_dir && !self.file_manager.file_exists(path) {
            return None;
        }

        let now = SystemTime::now();
        let file_type = if is_dir { FileType::Directory } else { FileType::RegularFile };
        let perm = if is_dir { 0o755 } else { 0o644 };
        let nlink = if is_dir { 2 } else { 1 };

        // Try to get actual file size for regular files
        let size = if !is_dir {
            self.file_manager.read_file(path)
                .map(|content| content.len() as u64)
                .unwrap_or(0)
        } else {
            0
        };

        Some(FileAttr {
            ino: 0, // Will be set by caller
            size,
            blocks: (size + 511) / 512,
            atime: now,
            mtime: now,
            ctime: now,
            crtime: now,
            kind: file_type,
            perm,
            nlink,
            uid: 1000, // Default user ID for Alpine/containers
            gid: 1000, // Default group ID for Alpine/containers
            rdev: 0,
            flags: 0,
            blksize: 512,
        })
    }
}

impl Filesystem for MergerFS {
    fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
        info!("lookup: parent={}, name={:?}", parent, name);

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

        // Try to create attributes for this path (check if file exists)
        let path = Path::new(&child_path);
        if let Some(mut attr) = self.create_file_attr(path, false) {
            let ino = self.allocate_inode();
            attr.ino = ino;

            let inode_data = InodeData {
                path: child_path,
                attr,
            };

            self.inodes.write().insert(ino, inode_data.clone());
            reply.entry(&TTL, &attr, 0);
        } else {
            reply.error(ENOENT);
        }
    }

    fn getattr(&mut self, _req: &Request, ino: u64, reply: ReplyAttr) {
        debug!("getattr: ino={}", ino);

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
            Some(data) => reply.attr(&TTL, &data.attr),
            None => reply.error(ENOENT),
        }
    }

    fn open(&mut self, _req: &Request, ino: u64, flags: i32, reply: ReplyOpen) {
        info!("open: ino={}, flags={}", ino, flags);

        match self.get_inode_data(ino) {
            Some(data) => {
                if data.attr.kind == FileType::RegularFile {
                    let path = Path::new(&data.path);
                    
                    // Find which branch has the file
                    let mut branch_idx = None;
                    for (idx, branch) in self.file_manager.branches.iter().enumerate() {
                        if branch.full_path(path).exists() {
                            branch_idx = Some(idx);
                            break;
                        }
                    }
                    
                    // Create file handle
                    let fh = self.file_handle_manager.create_handle(
                        ino,
                        PathBuf::from(&data.path),
                        flags,
                        branch_idx
                    );
                    
                    // TODO: Check if O_DIRECT is requested and set appropriate flags
                    let open_flags = 0;
                    
                    reply.opened(fh, open_flags);
                } else {
                    reply.error(ENOTDIR);
                }
            }
            None => reply.error(ENOENT),
        }
    }

    fn read(
        &mut self,
        _req: &Request,
        ino: u64,
        fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock: Option<u64>,
        reply: ReplyData,
    ) {
        debug!("read: ino={}, fh={}, offset={}, size={}", ino, fh, offset, size);

        // Get the file handle
        let handle = match self.file_handle_manager.get_handle(fh) {
            Some(h) => h,
            None => {
                // Fallback to reading without handle for compatibility
                let data = match self.get_inode_data(ino) {
                    Some(data) => data,
                    None => {
                        reply.error(ENOENT);
                        return;
                    }
                };
                
                let path = Path::new(&data.path);
                match self.file_manager.read_file(path) {
                    Ok(content) => {
                        let start = offset as usize;
                        let end = std::cmp::min(start + size as usize, content.len());
                        
                        if start >= content.len() {
                            reply.data(&[]);
                        } else {
                            reply.data(&content[start..end]);
                        }
                    }
                    Err(e) => {
                        error!("Failed to read file {}: {:?}", data.path, e);
                        reply.error(ENOENT);
                    }
                }
                return;
            }
        };

        // Use the file handle's path
        let path = Path::new(&handle.path);
        
        // If we know which branch, read from that specific branch
        let content = if let Some(branch_idx) = handle.branch_idx {
            if branch_idx < self.file_manager.branches.len() {
                let branch = &self.file_manager.branches[branch_idx];
                let full_path = branch.full_path(path);
                match std::fs::read(&full_path) {
                    Ok(data) => data,
                    Err(e) => {
                        error!("Failed to read file from branch {}: {:?}", branch_idx, e);
                        reply.error(ENOENT);
                        return;
                    }
                }
            } else {
                // Fallback to normal read
                match self.file_manager.read_file(path) {
                    Ok(data) => data,
                    Err(e) => {
                        error!("Failed to read file: {:?}", e);
                        reply.error(ENOENT);
                        return;
                    }
                }
            }
        } else {
            // Fallback to normal read
            match self.file_manager.read_file(path) {
                Ok(data) => data,
                Err(e) => {
                    error!("Failed to read file: {:?}", e);
                    reply.error(ENOENT);
                    return;
                }
            }
        };

        let start = offset as usize;
        let end = std::cmp::min(start + size as usize, content.len());
        
        if start >= content.len() {
            reply.data(&[]);
        } else {
            reply.data(&content[start..end]);
        }
    }

    fn readdir(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        offset: i64,
        mut reply: ReplyDirectory,
    ) {
        debug!("readdir: ino={}, offset={}", ino, offset);

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

        // Start with standard entries
        let mut entries = vec![
            (1, FileType::Directory, ".".to_string()),
            (1, FileType::Directory, "..".to_string()),
        ];

        // Add control file to root directory listing
        if data.path == "/" {
            entries.push((CONTROL_FILE_INO, FileType::RegularFile, ".mergerfs".to_string()));
        }
        
        // Get union directory listing
        let path = Path::new(&data.path);
        match self.file_manager.list_directory(path) {
            Ok(dir_entries) => {
                for entry_name in dir_entries {
                    // Create a path for this entry to check if it's a directory
                    let entry_path = if data.path == "/" {
                        format!("/{}", entry_name)
                    } else {
                        format!("{}/{}", data.path, entry_name)
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
        _mode: u32,
        _umask: u32,
        _flags: i32,
        reply: ReplyCreate,
    ) {
        info!("create: parent={}, name={:?}", parent, name);

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

        // Create empty file using file manager
        let path = Path::new(&file_path);
        match self.file_manager.create_file(path, &[]) {
            Ok(_) => {
                // Create file attributes
                if let Some(mut attr) = self.create_file_attr(path, false) {
                    let ino = self.allocate_inode();
                    attr.ino = ino;

                    let inode_data = InodeData {
                        path: file_path,
                        attr,
                    };

                    self.inodes.write().insert(ino, inode_data);
                    reply.created(&TTL, &attr, 0, 0, 0);
                } else {
                    reply.error(EIO);
                }
            }
            Err(e) => {
                error!("Failed to create file: {:?}", e);
                let errno = e.errno();
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
        _write_flags: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyWrite,
    ) {
        info!("write: ino={}, fh={}, offset={}, len={}", ino, fh, offset, data.len());

        // Try to get file handle first
        let handle = self.file_handle_manager.get_handle(fh);
        
        // Get the path - either from handle or inode
        let (path_buf, branch_idx) = if let Some(h) = &handle {
            (h.path.clone(), h.branch_idx)
        } else {
            // Fallback to using inode data
            let inode_data = match self.get_inode_data(ino) {
                Some(data) => data,
                None => {
                    reply.error(ENOENT);
                    return;
                }
            };
            (PathBuf::from(&inode_data.path), None)
        };
        
        let path = path_buf.as_path();
        
        // If we have a file handle with a specific branch, write to that branch
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
                                match file.seek(SeekFrom::Start(offset as u64)) {
                                    Ok(_) => {
                                        match file.write_all(data) {
                                            Ok(_) => {
                                                let _ = file.sync_all();
                                                Ok(())
                                            }
                                            Err(e) => Err(PolicyError::IoError(e))
                                        }
                                    }
                                    Err(e) => Err(PolicyError::IoError(e))
                                }
                            }
                            Err(e) => Err(PolicyError::IoError(e))
                        }
                    } else {
                        Err(PolicyError::from_errno(EROFS))
                    }
                } else {
                    // Fallback to normal write
                    self.file_manager.write_to_file(path, offset as u64, data)
                        .map(|_| ())
                }
        } else {
            // No specific branch, use normal write
            self.file_manager.write_to_file(path, offset as u64, data)
                .map(|_| ())
        };

        match result {
            Ok(_) => {
                // Update file size in inode
                let mut inodes = self.inodes.write();
                if let Some(inode_data) = inodes.get_mut(&ino) {
                    // Calculate new size
                    let new_size = if offset == 0 && data.len() > 0 {
                        data.len() as u64
                    } else {
                        let end_pos = (offset as u64) + (data.len() as u64);
                        std::cmp::max(inode_data.attr.size, end_pos)
                    };
                    
                    inode_data.attr.size = new_size;
                    inode_data.attr.blocks = (new_size + 511) / 512;
                    inode_data.attr.mtime = SystemTime::now();
                }
                reply.written(data.len() as u32);
            }
            Err(e) => {
                error!("Failed to write file: {:?}", e);
                reply.error(EIO);
            }
        }
    }

    fn mkdir(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        _mode: u32,
        _umask: u32,
        reply: ReplyEntry,
    ) {
        info!("mkdir: parent={}, name={:?}", parent, name);

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

        // Create directory using file manager
        let path = Path::new(&dir_path);
        match self.file_manager.create_directory(path) {
            Ok(_) => {
                // Create directory attributes
                if let Some(mut attr) = self.create_file_attr(path, true) {
                    let ino = self.allocate_inode();
                    attr.ino = ino;

                    let inode_data = InodeData {
                        path: dir_path,
                        attr,
                    };

                    self.inodes.write().insert(ino, inode_data);
                    reply.entry(&TTL, &attr, 0);
                } else {
                    reply.error(EIO);
                }
            }
            Err(e) => {
                error!("Failed to create directory: {:?}", e);
                reply.error(EIO);
            }
        }
    }

    fn rmdir(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        info!("rmdir: parent={}, name={:?}", parent, name);

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
        match self.file_manager.remove_directory(path) {
            Ok(_) => {
                // Remove from inode cache if it exists
                let mut inodes = self.inodes.write();
                let mut inode_to_remove = None;
                for (&ino, data) in inodes.iter() {
                    if data.path == dir_path {
                        inode_to_remove = Some(ino);
                        break;
                    }
                }
                if let Some(ino) = inode_to_remove {
                    inodes.remove(&ino);
                }
                reply.ok();
            }
            Err(e) => {
                error!("Failed to remove directory: {:?}", e);
                // Map common errors to appropriate errno values
                let errno = match e {
                    PolicyError::NoBranchesAvailable => ENOENT,
                    PolicyError::IoError(io_err) => {
                        match io_err.kind() {
                            std::io::ErrorKind::DirectoryNotEmpty => ENOTEMPTY,
                            std::io::ErrorKind::PermissionDenied => EACCES,
                            _ => EIO,
                        }
                    }
                    _ => EIO,
                };
                reply.error(errno);
            }
        }
    }

    fn unlink(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        info!("unlink: parent={}, name={:?}", parent, name);

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
        match self.file_manager.remove_file(path) {
            Ok(_) => {
                // Remove from inode cache if it exists
                let mut inodes = self.inodes.write();
                let mut inode_to_remove = None;
                for (&ino, data) in inodes.iter() {
                    if data.path == file_path {
                        inode_to_remove = Some(ino);
                        break;
                    }
                }
                if let Some(ino) = inode_to_remove {
                    inodes.remove(&ino);
                }
                reply.ok();
            }
            Err(e) => {
                error!("Failed to remove file: {:?}", e);
                let errno = match e {
                    PolicyError::NoBranchesAvailable => ENOENT,
                    PolicyError::IoError(_) => EIO,
                    _ => EIO,
                };
                reply.error(errno);
            }
        }
    }

    fn setattr(
        &mut self,
        _req: &Request,
        ino: u64,
        mode: Option<u32>,
        uid: Option<u32>,
        gid: Option<u32>,
        size: Option<u64>,
        atime: Option<fuser::TimeOrNow>,
        mtime: Option<fuser::TimeOrNow>,
        _ctime: Option<SystemTime>,
        _fh: Option<u64>,
        _crtime: Option<SystemTime>,
        _chgtime: Option<SystemTime>,
        _bkuptime: Option<SystemTime>,
        _flags: Option<u32>,
        reply: ReplyAttr,
    ) {
        info!("setattr: ino={}, mode={:?}, uid={:?}, gid={:?}, size={:?}", ino, mode, uid, gid, size);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        let mut had_success = false;

        // Handle truncate
        if let Some(new_size) = size {
            info!("Truncating file {} to size {}", inode_data.path, new_size);
            
            match self.file_manager.truncate_file(path, new_size) {
                Ok(_) => {
                    had_success = true;
                    // Update size in inode
                    let mut inodes = self.inodes.write();
                    if let Some(cached_data) = inodes.get_mut(&ino) {
                        cached_data.attr.size = new_size;
                        cached_data.attr.blocks = (new_size + 511) / 512;
                    }
                }
                Err(e) => {
                    error!("Failed to truncate file: {:?}", e);
                }
            }
        }

        // Handle chmod
        if let Some(new_mode) = mode {
            match self.metadata_manager.chmod(path, new_mode) {
                Ok(_) => {
                    had_success = true;
                    debug!("chmod successful for {}", inode_data.path);
                }
                Err(e) => {
                    error!("chmod failed for {}: {:?}", inode_data.path, e);
                }
            }
        }

        // Handle chown
        if let (Some(new_uid), Some(new_gid)) = (uid, gid) {
            match self.metadata_manager.chown(path, new_uid, new_gid) {
                Ok(_) => {
                    had_success = true;
                    debug!("chown successful for {}", inode_data.path);
                }
                Err(e) => {
                    error!("chown failed for {}: {:?}", inode_data.path, e);
                }
            }
        }

        // Handle utimens
        if atime.is_some() || mtime.is_some() {
            let now = SystemTime::now();
            let access_time = match atime {
                Some(fuser::TimeOrNow::SpecificTime(t)) => t,
                Some(fuser::TimeOrNow::Now) => now,
                None => inode_data.attr.atime,
            };
            let modify_time = match mtime {
                Some(fuser::TimeOrNow::SpecificTime(t)) => t,
                Some(fuser::TimeOrNow::Now) => now,
                None => inode_data.attr.mtime,
            };

            match self.metadata_manager.utimens(path, access_time, modify_time) {
                Ok(_) => {
                    had_success = true;
                    debug!("utimens successful for {}", inode_data.path);
                }
                Err(e) => {
                    error!("utimens failed for {}: {:?}", inode_data.path, e);
                }
            }
        }

        if had_success || (mode.is_none() && uid.is_none() && gid.is_none() && size.is_none() && atime.is_none() && mtime.is_none()) {
            // Get updated attributes and return them
            match self.create_file_attr(path, inode_data.attr.kind == FileType::Directory) {
                Some(mut new_attr) => {
                    new_attr.ino = ino;
                    
                    // Update cached inode data
                    let mut inodes = self.inodes.write();
                    if let Some(cached_data) = inodes.get_mut(&ino) {
                        cached_data.attr = new_attr;
                    }
                    
                    reply.attr(&TTL, &new_attr);
                }
                None => {
                    reply.error(EIO);
                }
            }
        } else {
            reply.error(EIO);
        }
    }

    fn flush(&mut self, _req: &Request, ino: u64, _fh: u64, _lock_owner: u64, reply: fuser::ReplyEmpty) {
        info!("flush: ino={}", ino);
        // For now, we don't need to do anything special for flush
        // since we write synchronously
        reply.ok();
    }

    fn fsync(&mut self, _req: &Request, ino: u64, _fh: u64, _datasync: bool, reply: fuser::ReplyEmpty) {
        info!("fsync: ino={}", ino);
        // For now, we don't need to do anything special for fsync
        // since we write synchronously
        reply.ok();
    }

    fn statfs(&mut self, _req: &Request, _ino: u64, reply: fuser::ReplyStatfs) {
        info!("statfs called");
        
        use nix::sys::statvfs::{statvfs, FsFlags};
        use std::collections::HashMap;
        
        let config = self.config.read();
        let statfs_ignore = config.statfs_ignore;
        
        // Keep track of unique device IDs to avoid counting same filesystem multiple times
        let mut fs_stats: HashMap<u64, (nix::sys::statvfs::Statvfs, Arc<crate::branch::Branch>)> = HashMap::new();
        let mut min_bsize = u64::MAX;
        let mut min_frsize = u64::MAX;
        let mut min_namemax = u64::MAX;
        
        // Collect statvfs data for each branch
        for branch in &self.file_manager.branches {
            match std::fs::metadata(&branch.path) {
                Ok(metadata) => {
                    use std::os::unix::fs::MetadataExt;
                    let dev = metadata.dev();
                    
                    // Get filesystem stats using statvfs
                    match statvfs(&branch.path) {
                        Ok(stat) => {
                            // Track minimum values for normalization
                            if stat.block_size() > 0 && stat.block_size() < min_bsize {
                                min_bsize = stat.block_size();
                            }
                            if stat.fragment_size() > 0 && stat.fragment_size() < min_frsize {
                                min_frsize = stat.fragment_size();
                            }
                            if stat.name_max() > 0 && stat.name_max() < min_namemax {
                                min_namemax = stat.name_max();
                            }
                            
                            // Store stats by device ID to avoid duplicates
                            fs_stats.insert(dev, (stat, branch.clone()));
                        }
                        Err(e) => {
                            error!("Failed to get statvfs for {}: {}", branch.path.display(), e);
                        }
                    }
                }
                Err(e) => {
                    error!("Failed to get metadata for {}: {}", branch.path.display(), e);
                }
            }
        }
        
        // If we couldn't get any stats, use defaults
        if fs_stats.is_empty() {
            reply.statfs(0, 0, 0, 0, 0, 4096, 255, 4096);
            return;
        }
        
        // Use defaults if we didn't find valid minimums
        if min_bsize == u64::MAX {
            min_bsize = 4096;
        }
        if min_frsize == u64::MAX {
            min_frsize = 4096;
        }
        if min_namemax == u64::MAX {
            min_namemax = 255;
        }
        
        // Aggregate statistics from unique filesystems
        let mut total_blocks = 0u64;
        let mut total_bfree = 0u64;
        let mut total_bavail = 0u64;
        let mut total_files = 0u64;
        let mut total_ffree = 0u64;
        let mut _total_favail = 0u64;
        
        for (stat, branch) in fs_stats.values() {
            // Check if we should ignore this branch based on StatFSIgnore configuration
            let is_readonly = stat.flags().contains(FsFlags::ST_RDONLY);
            let should_ignore = match statfs_ignore {
                StatFSIgnore::None => false,
                StatFSIgnore::ReadOnly => is_readonly || branch.is_readonly_or_no_create(),
                StatFSIgnore::NoCreate => branch.is_no_create(),
            };
            
            // Normalize block counts to common fragment size (like the C++ version)
            let normalization_factor = stat.fragment_size() / min_frsize;
            
            total_blocks += stat.blocks() * normalization_factor;
            total_bfree += stat.blocks_free() * normalization_factor;
            
            // If we should ignore this branch, don't count its available space
            if should_ignore {
                // Still count the blocks but not available space
                total_files += stat.files();
            } else {
                total_bavail += stat.blocks_available() * normalization_factor;
                total_files += stat.files();
                total_ffree += stat.files_free();
                _total_favail += stat.files_available();
            }
        }
        
        reply.statfs(
            total_blocks,
            total_bfree,
            total_bavail,
            total_files,
            total_ffree,
            min_bsize as u32,
            min_namemax as u32,
            min_frsize as u32,
        );
    }

    fn rename(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        newparent: u64,
        newname: &OsStr,
        _flags: u32,
        reply: fuser::ReplyEmpty,
    ) {
        info!("rename: parent={}, name={:?} -> newparent={}, newname={:?}", 
            parent, name, newparent, newname);

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

        // Find which branch has the source file/directory
        let mut source_branch = None;
        for branch in &self.file_manager.branches {
            let full_old_path = branch.full_path(Path::new(&old_path));
            if full_old_path.exists() {
                source_branch = Some(branch);
                break;
            }
        }

        match source_branch {
            Some(branch) => {
                if !branch.allows_create() {
                    reply.error(EROFS);
                    return;
                }

                let full_old_path = branch.full_path(Path::new(&old_path));
                let full_new_path = branch.full_path(Path::new(&new_path));

                // Create parent directory if needed
                if let Some(parent) = full_new_path.parent() {
                    if let Err(_) = std::fs::create_dir_all(parent) {
                        reply.error(EIO);
                        return;
                    }
                }

                // Perform the rename
                match std::fs::rename(&full_old_path, &full_new_path) {
                    Ok(_) => {
                        // Update inode cache
                        let mut inodes = self.inodes.write();
                        let mut updates = Vec::new();
                        
                        for (&ino, data) in inodes.iter() {
                            if data.path == old_path {
                                updates.push((ino, new_path.clone()));
                            } else if data.path.starts_with(&format!("{}/", old_path)) {
                                // Update children paths
                                let suffix = &data.path[old_path.len()..];
                                updates.push((ino, format!("{}{}", new_path, suffix)));
                            }
                        }
                        
                        for (ino, new_path) in updates {
                            if let Some(data) = inodes.get_mut(&ino) {
                                data.path = new_path;
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
            None => {
                reply.error(ENOENT);
            }
        }
    }

    fn symlink(
        &mut self,
        _req: &Request,
        parent: u64,
        link_name: &OsStr,
        target: &Path,
        reply: ReplyEntry,
    ) {
        info!("symlink: parent={}, link_name={:?} -> target={:?}", 
            parent, link_name, target);

        let parent_data = match self.get_inode_data(parent) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let link_name_str = match link_name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        let link_path = if parent_data.path == "/" {
            format!("/{}", link_name_str)
        } else {
            format!("{}/{}", parent_data.path, link_name_str)
        };

        // Use create policy to determine which branch
        let path = Path::new(&link_path);
        match self.file_manager.create_policy.select_branch(&self.file_manager.branches, path) {
            Ok(branch) => {
                let full_link_path = branch.full_path(path);
                
                // Create parent directories if needed
                if let Some(parent) = full_link_path.parent() {
                    if let Err(_) = std::fs::create_dir_all(parent) {
                        reply.error(EIO);
                        return;
                    }
                }

                // Create the symlink
                #[cfg(unix)]
                {
                    use std::os::unix::fs::symlink;
                    match symlink(target, &full_link_path) {
                        Ok(_) => {
                            // Create inode for the symlink
                            let now = SystemTime::now();
                            let ino = self.allocate_inode();
                            
                            let attr = FileAttr {
                                ino,
                                size: target.as_os_str().len() as u64,
                                blocks: 1,
                                atime: now,
                                mtime: now,
                                ctime: now,
                                crtime: now,
                                kind: FileType::Symlink,
                                perm: 0o777,
                                nlink: 1,
                                uid: 1000,
                                gid: 1000,
                                rdev: 0,
                                flags: 0,
                                blksize: 512,
                            };

                            let inode_data = InodeData {
                                path: link_path,
                                attr,
                            };

                            self.inodes.write().insert(ino, inode_data);
                            reply.entry(&TTL, &attr, 0);
                        }
                        Err(e) => {
                            error!("Failed to create symlink: {:?}", e);
                            reply.error(EIO);
                        }
                    }
                }
                #[cfg(not(unix))]
                {
                    reply.error(ENOSYS);
                }
            }
            Err(e) => {
                reply.error(e.errno());
            }
        }
    }

    fn readlink(&mut self, _req: &Request, ino: u64, reply: fuser::ReplyData) {
        info!("readlink: ino={}", ino);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        if inode_data.attr.kind != FileType::Symlink {
            reply.error(EINVAL);
            return;
        }

        let path = Path::new(&inode_data.path);
        
        // Find which branch has the symlink
        for branch in &self.file_manager.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                match std::fs::read_link(&full_path) {
                    Ok(target) => {
                        use std::os::unix::ffi::OsStrExt;
                        reply.data(target.as_os_str().as_bytes());
                        return;
                    }
                    Err(e) => {
                        error!("Failed to read symlink: {:?}", e);
                        reply.error(EIO);
                        return;
                    }
                }
            }
        }
        
        reply.error(ENOENT);
    }

    fn link(
        &mut self,
        _req: &Request,
        ino: u64,
        newparent: u64,
        newname: &OsStr,
        reply: ReplyEntry,
    ) {
        info!("link: ino={}, newparent={}, newname={:?}", ino, newparent, newname);

        let inode_data = match self.get_inode_data(ino) {
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

        let newname_str = match newname.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };

        let source_path = Path::new(&inode_data.path);
        let link_path = if newparent_data.path == "/" {
            format!("/{}", newname_str)
        } else {
            format!("{}/{}", newparent_data.path, newname_str)
        };

        // Find which branch has the source file
        let mut source_branch = None;
        for branch in &self.file_manager.branches {
            let full_source = branch.full_path(source_path);
            if full_source.exists() && full_source.is_file() {
                source_branch = Some(branch);
                break;
            }
        }

        match source_branch {
            Some(branch) => {
                if !branch.allows_create() {
                    reply.error(EROFS);
                    return;
                }

                let full_source = branch.full_path(source_path);
                let full_link = branch.full_path(Path::new(&link_path));

                // Create parent directories if needed
                if let Some(parent) = full_link.parent() {
                    if let Err(_) = std::fs::create_dir_all(parent) {
                        reply.error(EIO);
                        return;
                    }
                }

                // Create the hard link
                match std::fs::hard_link(&full_source, &full_link) {
                    Ok(_) => {
                        // Update the existing inode's link count
                        let mut inodes = self.inodes.write();
                        if let Some(data) = inodes.get_mut(&ino) {
                            data.attr.nlink += 1;
                        }
                        
                        // Return the existing inode attributes
                        reply.entry(&TTL, &inode_data.attr, 0);
                    }
                    Err(e) => {
                        error!("Failed to create hard link: {:?}", e);
                        reply.error(EIO);
                    }
                }
            }
            None => {
                reply.error(ENOENT);
            }
        }
    }

    fn release(
        &mut self,
        _req: &Request,
        ino: u64,
        fh: u64,
        _flags: i32,
        _lock_owner: Option<u64>,
        _flush: bool,
        reply: fuser::ReplyEmpty,
    ) {
        info!("release: ino={}, fh={}", ino, fh);
        
        // Remove the file handle
        if let Some(handle) = self.file_handle_manager.remove_handle(fh) {
            debug!("Released file handle {} for path {:?}", fh, handle.path);
        } else {
            warn!("Attempted to release unknown file handle: {}", fh);
        }
        
        reply.ok();
    }

    fn access(&mut self, _req: &Request, ino: u64, mask: i32, reply: fuser::ReplyEmpty) {
        info!("access: ino={}, mask={}", ino, mask);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        // Check if file exists in any branch
        let path = Path::new(&inode_data.path);
        let exists = self.file_manager.branches.iter().any(|branch| {
            branch.full_path(path).exists()
        });

        if exists {
            // For now, we allow all access if the file exists
            // A proper implementation would check actual permissions
            reply.ok();
        } else {
            reply.error(ENOENT);
        }
    }

    fn getxattr(
        &mut self,
        _req: &Request,
        ino: u64,
        name: &OsStr,
        size: u32,
        reply: fuser::ReplyXattr,
    ) {
        info!("getxattr: ino={}, name={:?}, size={}", ino, name, size);
        
        // Handle control file xattr
        if ino == CONTROL_FILE_INO {
            let name_str = match name.to_str() {
                Some(s) => s,
                None => {
                    reply.error(EINVAL);
                    return;
                }
            };
            
            match self.config_manager.get_option(name_str) {
                Ok(value) => {
                    let data = value.as_bytes();
                    if size == 0 {
                        reply.size(data.len() as u32);
                    } else if size < data.len() as u32 {
                        reply.error(ERANGE);
                    } else {
                        reply.data(data);
                    }
                }
                Err(err) => reply.error(err.errno()),
            }
            return;
        }

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        match self.xattr_manager.get_xattr(path, name_str) {
            Ok(value) => {
                if size == 0 {
                    // Caller is asking for the size
                    reply.size(value.len() as u32);
                } else if size < value.len() as u32 {
                    // Buffer too small
                    reply.error(ERANGE);
                } else {
                    // Return the data
                    reply.data(&value);
                }
            }
            Err(XattrError::NotFound) => reply.error(61), // ENOATTR
            Err(XattrError::PermissionDenied) => reply.error(EACCES),
            Err(XattrError::NotSupported) => reply.error(95), // ENOTSUP
            Err(_) => reply.error(EIO),
        }
    }

    fn setxattr(
        &mut self,
        _req: &Request,
        ino: u64,
        name: &OsStr,
        value: &[u8],
        flags: i32,
        _position: u32,
        reply: fuser::ReplyEmpty,
    ) {
        info!("setxattr: ino={}, name={:?}, value_len={}, flags={}", 
            ino, name, value.len(), flags);
            
        // Handle control file xattr
        if ino == CONTROL_FILE_INO {
            let name_str = match name.to_str() {
                Some(s) => s,
                None => {
                    reply.error(EINVAL);
                    return;
                }
            };
            
            let value_str = match std::str::from_utf8(value) {
                Ok(s) => s,
                Err(_) => {
                    reply.error(EINVAL);
                    return;
                }
            };
            
            match self.config_manager.set_option(name_str, value_str) {
                Ok(_) => reply.ok(),
                Err(err) => reply.error(err.errno()),
            }
            return;
        }

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        // Convert FUSE flags to our XattrFlags
        let xattr_flags = match flags {
            1 => XattrFlags::Create,  // XATTR_CREATE
            2 => XattrFlags::Replace, // XATTR_REPLACE
            _ => XattrFlags::None,
        };
        
        match self.xattr_manager.set_xattr(path, name_str, value, xattr_flags) {
            Ok(_) => reply.ok(),
            Err(XattrError::NotFound) => reply.error(ENOENT),
            Err(XattrError::PermissionDenied) => reply.error(EACCES),
            Err(XattrError::InvalidArgument) => reply.error(EINVAL),
            Err(XattrError::NameTooLong) => reply.error(36), // ENAMETOOLONG
            Err(XattrError::ValueTooLarge) => reply.error(7), // E2BIG
            Err(XattrError::NotSupported) => reply.error(95), // ENOTSUP
            Err(_) => reply.error(EIO),
        }
    }

    fn listxattr(&mut self, _req: &Request, ino: u64, size: u32, reply: fuser::ReplyXattr) {
        info!("listxattr: ino={}, size={}", ino, size);
        
        // Handle control file xattr
        if ino == CONTROL_FILE_INO {
            let options = self.config_manager.list_options();
            
            // Build null-terminated list
            let mut data = Vec::new();
            for option in &options {
                data.extend(option.as_bytes());
                data.push(0);
            }
            
            if size == 0 {
                reply.size(data.len() as u32);
            } else if size < data.len() as u32 {
                reply.error(ERANGE);
            } else {
                reply.data(&data);
            }
            return;
        }

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        
        match self.xattr_manager.list_xattr(path) {
            Ok(attrs) => {
                // Build null-terminated list of attribute names
                let mut data = Vec::new();
                for attr in &attrs {
                    data.extend(attr.as_bytes());
                    data.push(0); // null terminator
                }
                
                if size == 0 {
                    // Caller is asking for the size
                    reply.size(data.len() as u32);
                } else if size < data.len() as u32 {
                    // Buffer too small
                    reply.error(ERANGE);
                } else {
                    // Return the data
                    reply.data(&data);
                }
            }
            Err(XattrError::NotFound) => reply.error(ENOENT),
            Err(XattrError::NotSupported) => reply.error(95), // ENOTSUP
            Err(_) => reply.error(EIO),
        }
    }

    fn removexattr(&mut self, _req: &Request, ino: u64, name: &OsStr, reply: fuser::ReplyEmpty) {
        info!("removexattr: ino={}, name={:?}", ino, name);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        match self.xattr_manager.remove_xattr(path, name_str) {
            Ok(_) => reply.ok(),
            Err(XattrError::NotFound) => reply.error(61), // ENOATTR
            Err(XattrError::PermissionDenied) => reply.error(EACCES),
            Err(XattrError::NotSupported) => reply.error(95), // ENOTSUP
            Err(_) => reply.error(EIO),
        }
    }

    fn mknod(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        mode: u32,
        _umask: u32,
        rdev: u32,
        reply: ReplyEntry,
    ) {
        info!("mknod: parent={}, name={:?}, mode={:o}, rdev={}", parent, name, mode, rdev);

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
                reply.error(EINVAL);
                return;
            }
        };

        let file_path = if parent_data.path == "/" {
            format!("/{}", name_str)
        } else {
            format!("{}/{}", parent_data.path, name_str)
        };

        // For now, we only support regular files through mknod
        // Special files (devices, pipes, sockets) are not supported
        if (mode & 0o170000) == 0o100000 {
            // Regular file - create it like create()
            let path = Path::new(&file_path);
            match self.file_manager.create_file(path, &[]) {
                Ok(_) => {
                    if let Some(mut attr) = self.create_file_attr(path, false) {
                        let ino = self.allocate_inode();
                        attr.ino = ino;
                        attr.perm = (mode & 0o7777) as u16;

                        let inode_data = InodeData {
                            path: file_path,
                            attr,
                        };

                        self.inodes.write().insert(ino, inode_data);
                        reply.entry(&TTL, &attr, 0);
                    } else {
                        reply.error(EIO);
                    }
                }
                Err(e) => {
                    error!("Failed to create file: {:?}", e);
                    reply.error(e.errno());
                }
            }
        } else {
            // Special files not supported
            reply.error(ENOSYS);
        }
    }

    fn opendir(&mut self, _req: &Request, ino: u64, _flags: i32, reply: ReplyOpen) {
        info!("opendir: ino={}", ino);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        if inode_data.attr.kind != FileType::Directory {
            reply.error(ENOTDIR);
            return;
        }

        // For now, we don't track directory handles
        reply.opened(0, 0);
    }

    fn releasedir(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        _flags: i32,
        reply: fuser::ReplyEmpty,
    ) {
        info!("releasedir: ino={}", ino);
        reply.ok();
    }

    fn fsyncdir(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        _datasync: bool,
        reply: fuser::ReplyEmpty,
    ) {
        info!("fsyncdir: ino={}", ino);
        reply.ok();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::policy::FirstFoundCreatePolicy;
    use std::sync::Arc;
    use tempfile::TempDir;

    fn setup_test_fs() -> (Vec<TempDir>, MergerFS) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1, branch2];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        let fs = MergerFS::new(file_manager);
        (vec![temp1, temp2], fs)
    }

    #[test]
    fn test_mergerfs_creation() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // Root inode should exist
        let root_data = fs.get_inode_data(1);
        assert!(root_data.is_some());
        
        let root = root_data.unwrap();
        assert_eq!(root.path, "/");
        assert_eq!(root.attr.ino, 1);
        assert_eq!(root.attr.kind, FileType::Directory);
    }

    #[test]
    fn test_create_file_attr() {
        let (_temp_dirs, mut fs) = setup_test_fs();
        
        // Create a test file first
        let test_content = b"test content";
        fs.file_manager.create_file(Path::new("test.txt"), test_content).unwrap();
        
        // Test creating attributes for existing file
        let attr = fs.create_file_attr(Path::new("test.txt"), false);
        assert!(attr.is_some());
        
        let attr = attr.unwrap();
        assert_eq!(attr.kind, FileType::RegularFile);
        assert_eq!(attr.size, test_content.len() as u64);
        
        // Test creating attributes for non-existing file
        let attr = fs.create_file_attr(Path::new("nonexistent.txt"), false);
        assert!(attr.is_none());
    }

    #[test]
    fn test_inode_allocation() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        let ino1 = fs.allocate_inode();
        let ino2 = fs.allocate_inode();
        let ino3 = fs.allocate_inode();
        
        assert_eq!(ino1, 2);
        assert_eq!(ino2, 3);
        assert_eq!(ino3, 4);
    }

    #[test]
    fn test_path_to_inode_lookup() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // Root should be found
        let root_ino = fs.path_to_inode("/");
        assert_eq!(root_ino, Some(1));
        
        // Non-existing path should not be found
        let missing_ino = fs.path_to_inode("/nonexistent");
        assert_eq!(missing_ino, None);
    }

    #[test]
    fn test_fuse_create_operation() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // Test the internal logic by directly calling the file manager
        let path = std::path::Path::new("test_create.txt");
        let result = fs.file_manager.create_file(path, b"test content");
        assert!(result.is_ok());
        
        // Verify the file exists
        assert!(fs.file_manager.file_exists(path));
        
        // Verify we can create attributes for it
        let attr = fs.create_file_attr(path, false);
        assert!(attr.is_some());
        
        let attr = attr.unwrap();
        assert_eq!(attr.kind, FileType::RegularFile);
        assert_eq!(attr.size, 12); // "test content".len()
    }

    #[test]
    fn test_fuse_write_operation() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // First create a file
        let path = std::path::Path::new("test_write.txt");
        fs.file_manager.create_file(path, b"initial").unwrap();
        
        // Create an inode for it
        let mut attr = fs.create_file_attr(path, false).unwrap();
        let ino = fs.allocate_inode();
        attr.ino = ino;
        
        let inode_data = InodeData {
            path: "test_write.txt".to_string(),
            attr,
        };
        
        fs.inodes.write().insert(ino, inode_data);
        
        // Test writing new content
        let new_content = b"updated content";
        let result = fs.file_manager.create_file(path, new_content);
        assert!(result.is_ok());
        
        // Verify the content was written
        let read_content = fs.file_manager.read_file(path).unwrap();
        assert_eq!(read_content, new_content);
    }

    #[test]
    fn test_fuse_read_operation() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // Create a file with content
        let path = std::path::Path::new("test_read.txt");
        let content = b"Hello, FUSE world!";
        fs.file_manager.create_file(path, content).unwrap();
        
        // Read it back through the file manager (simulating FUSE read)
        let read_content = fs.file_manager.read_file(path).unwrap();
        assert_eq!(read_content, content);
        
        // Test partial read (simulating FUSE read with offset)
        let partial = &read_content[7..12]; // "FUSE "
        assert_eq!(partial, b"FUSE ");
    }

    #[test] 
    fn test_fuse_file_lookup() {
        let (_temp_dirs, fs) = setup_test_fs();
        
        // Create a file
        let path = std::path::Path::new("lookup_test.txt");
        let content = b"lookup test content";
        fs.file_manager.create_file(path, content).unwrap();
        
        // Test that we can create attributes for existing file
        let attr = fs.create_file_attr(path, false);
        assert!(attr.is_some());
        
        let attr = attr.unwrap();
        assert_eq!(attr.kind, FileType::RegularFile);
        assert_eq!(attr.size, content.len() as u64);
        assert_eq!(attr.nlink, 1);
        assert_eq!(attr.perm, 0o644);
        
        // Test that non-existing file returns None
        let missing_attr = fs.create_file_attr(std::path::Path::new("missing.txt"), false);
        assert!(missing_attr.is_none());
    }
}