use crate::action_policy::AllActionPolicy;
use crate::branch::PolicyError;
use crate::file_ops::FileManager;
use crate::metadata_ops::MetadataManager;
use fuser::{
    FileAttr, FileType, Filesystem, ReplyAttr, ReplyCreate, ReplyData, ReplyDirectory, ReplyEntry, 
    ReplyOpen, ReplyWrite, Request,
};
// Use standard errno constants compatible with MUSL
const ENOENT: i32 = 2;
const ENOTDIR: i32 = 20;
const EINVAL: i32 = 22;
const EIO: i32 = 5;
const ENOTEMPTY: i32 = 39;
const EACCES: i32 = 13;
use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tracing::{debug, error, info, warn};

const TTL: Duration = Duration::from_secs(1);

pub struct MergerFS {
    pub file_manager: Arc<FileManager>,
    pub metadata_manager: Arc<MetadataManager>,
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
        let metadata_manager = MetadataManager::new(branches, action_policy);
        
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

        match self.get_inode_data(ino) {
            Some(data) => reply.attr(&TTL, &data.attr),
            None => reply.error(ENOENT),
        }
    }

    fn open(&mut self, _req: &Request, ino: u64, _flags: i32, reply: ReplyOpen) {
        debug!("open: ino={}", ino);

        match self.get_inode_data(ino) {
            Some(data) => {
                if data.attr.kind == FileType::RegularFile {
                    reply.opened(0, 0);
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
        _fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock: Option<u64>,
        reply: ReplyData,
    ) {
        debug!("read: ino={}, offset={}, size={}", ino, offset, size);

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
                reply.error(EIO);
            }
        }
    }

    fn write(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        offset: i64,
        data: &[u8],
        _write_flags: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyWrite,
    ) {
        debug!("write: ino={}, offset={}, len={}", ino, offset, data.len());

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        
        // For simplicity, we only support writing at offset 0 (overwrite)
        if offset != 0 {
            reply.error(EINVAL);
            return;
        }

        match self.file_manager.create_file(path, data) {
            Ok(_) => {
                // Update file size in inode
                let mut inodes = self.inodes.write();
                if let Some(inode_data) = inodes.get_mut(&ino) {
                    inode_data.attr.size = data.len() as u64;
                    inode_data.attr.blocks = (data.len() as u64 + 511) / 512;
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
        _size: Option<u64>,
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
        debug!("setattr: ino={}, mode={:?}, uid={:?}, gid={:?}", ino, mode, uid, gid);

        let inode_data = match self.get_inode_data(ino) {
            Some(data) => data,
            None => {
                reply.error(ENOENT);
                return;
            }
        };

        let path = Path::new(&inode_data.path);
        let mut had_success = false;

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

        if had_success || (mode.is_none() && uid.is_none() && gid.is_none() && atime.is_none() && mtime.is_none()) {
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