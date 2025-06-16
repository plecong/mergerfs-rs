use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use parking_lot::RwLock;

#[derive(Debug, Clone)]
pub struct FileHandle {
    pub ino: u64,
    pub path: PathBuf,
    pub flags: i32,
    pub branch_idx: Option<usize>,  // Which branch the file was opened from
    pub direct_io: bool,
}

pub struct FileHandleManager {
    handles: RwLock<HashMap<u64, FileHandle>>,
    next_handle: AtomicU64,
}

impl FileHandleManager {
    pub fn new() -> Self {
        Self {
            handles: RwLock::new(HashMap::new()),
            next_handle: AtomicU64::new(1), // Start from 1, 0 is often reserved
        }
    }

    pub fn create_handle(&self, ino: u64, path: PathBuf, flags: i32, branch_idx: Option<usize>) -> u64 {
        let fh = self.next_handle.fetch_add(1, Ordering::SeqCst);
        
        let handle = FileHandle {
            ino,
            path,
            flags,
            branch_idx,
            direct_io: false, // TODO: Check flags for O_DIRECT
        };
        
        self.handles.write().insert(fh, handle);
        fh
    }

    pub fn get_handle(&self, fh: u64) -> Option<FileHandle> {
        self.handles.read().get(&fh).cloned()
    }

    pub fn remove_handle(&self, fh: u64) -> Option<FileHandle> {
        self.handles.write().remove(&fh)
    }

    pub fn get_handle_count(&self) -> usize {
        self.handles.read().len()
    }
    
    pub fn update_branch(&self, fh: u64, new_branch_idx: usize) {
        if let Some(handle) = self.handles.write().get_mut(&fh) {
            handle.branch_idx = Some(new_branch_idx);
            tracing::debug!("Updated file handle {} to use branch {}", fh, new_branch_idx);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_handle_manager() {
        let manager = FileHandleManager::new();
        
        // Create a handle
        let fh1 = manager.create_handle(1, PathBuf::from("/test.txt"), 0, Some(0));
        assert_eq!(fh1, 1);
        
        // Create another handle
        let fh2 = manager.create_handle(2, PathBuf::from("/test2.txt"), 0, Some(1));
        assert_eq!(fh2, 2);
        
        // Get handle
        let handle = manager.get_handle(fh1).unwrap();
        assert_eq!(handle.ino, 1);
        assert_eq!(handle.path, PathBuf::from("/test.txt"));
        assert_eq!(handle.branch_idx, Some(0));
        
        // Check count
        assert_eq!(manager.get_handle_count(), 2);
        
        // Remove handle
        let removed = manager.remove_handle(fh1).unwrap();
        assert_eq!(removed.ino, 1);
        assert_eq!(manager.get_handle_count(), 1);
        
        // Try to get removed handle
        assert!(manager.get_handle(fh1).is_none());
    }

    #[test]
    fn test_file_handle_flags() {
        let manager = FileHandleManager::new();
        
        // Test with different flags
        let fh_read = manager.create_handle(1, PathBuf::from("/read.txt"), 0, Some(0)); // O_RDONLY
        let fh_write = manager.create_handle(2, PathBuf::from("/write.txt"), 1, Some(0)); // O_WRONLY
        let fh_rdwr = manager.create_handle(3, PathBuf::from("/rdwr.txt"), 2, Some(1)); // O_RDWR
        
        let handle_read = manager.get_handle(fh_read).unwrap();
        assert_eq!(handle_read.flags, 0);
        
        let handle_write = manager.get_handle(fh_write).unwrap();
        assert_eq!(handle_write.flags, 1);
        
        let handle_rdwr = manager.get_handle(fh_rdwr).unwrap();
        assert_eq!(handle_rdwr.flags, 2);
    }

    #[test]
    fn test_file_handle_no_branch() {
        let manager = FileHandleManager::new();
        
        // Create handle without specific branch
        let fh = manager.create_handle(1, PathBuf::from("/nobranch.txt"), 0, None);
        
        let handle = manager.get_handle(fh).unwrap();
        assert_eq!(handle.branch_idx, None);
    }

    #[test]
    fn test_concurrent_handles() {
        let manager = FileHandleManager::new();
        
        // Create multiple handles for the same file
        let fh1 = manager.create_handle(1, PathBuf::from("/shared.txt"), 0, Some(0));
        let fh2 = manager.create_handle(1, PathBuf::from("/shared.txt"), 0, Some(0));
        let fh3 = manager.create_handle(1, PathBuf::from("/shared.txt"), 1, Some(0));
        
        assert_ne!(fh1, fh2);
        assert_ne!(fh2, fh3);
        assert_eq!(manager.get_handle_count(), 3);
        
        // Each handle should be independent
        manager.remove_handle(fh1);
        assert!(manager.get_handle(fh1).is_none());
        assert!(manager.get_handle(fh2).is_some());
        assert!(manager.get_handle(fh3).is_some());
    }

    #[test]
    fn test_handle_id_increments() {
        let manager = FileHandleManager::new();
        
        let mut handles = Vec::new();
        for i in 0..10 {
            let fh = manager.create_handle(i, PathBuf::from(format!("/file{}.txt", i)), 0, None);
            handles.push(fh);
        }
        
        // Check that handles are sequential
        for i in 1..handles.len() {
            assert_eq!(handles[i], handles[i-1] + 1);
        }
    }
}