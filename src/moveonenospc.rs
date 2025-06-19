use crate::branch::Branch;
use crate::policy::{CreatePolicy, PolicyError};
use crate::config::ConfigRef;
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;
use tempfile::NamedTempFile;
use nix::unistd::dup2;
use std::os::unix::io::{AsRawFd, RawFd};

#[derive(Debug, Error)]
pub enum MoveError {
    #[error("No space available on any branch")]
    NoSpaceAvailable,
    
    #[error("File not found on any branch")]
    FileNotFound,
    
    #[error("Policy error: {0}")]
    PolicyError(#[from] PolicyError),
    
    #[error("IO error: {0}")]
    IoError(#[from] io::Error),
    
    #[error("System error: {0}")]
    SystemError(#[from] nix::Error),
}

/// Represents the result of attempting to move a file
pub struct MoveResult {
    pub new_branch_idx: usize,
    pub new_path: PathBuf,
}

/// Main struct for handling moveonenospc operations
pub struct MoveOnENOSPCHandler {
    config: ConfigRef,
}

impl MoveOnENOSPCHandler {
    pub fn new(config: ConfigRef) -> Self {
        Self { config }
    }
    
    /// Check if moveonenospc is enabled
    pub fn is_enabled(&self) -> bool {
        self.config.read().moveonenospc.enabled
    }
    
    /// Get the configured policy name
    pub fn get_policy_name(&self) -> String {
        self.config.read().moveonenospc.policy_name.clone()
    }
    
    /// Attempt to move a file to another branch when ENOSPC occurs
    pub fn move_file_on_enospc(
        &self,
        path: &Path,
        current_branch_idx: usize,
        branches: &[Arc<Branch>],
        _fallback_policy: &dyn CreatePolicy,
        fd: Option<RawFd>,
    ) -> Result<MoveResult, MoveError> {
        tracing::info!("Attempting to move file {:?} from branch {} due to ENOSPC", 
            path, current_branch_idx);
        
        // Verify we have a valid current branch
        if current_branch_idx >= branches.len() {
            return Err(MoveError::FileNotFound);
        }
        
        let current_branch = &branches[current_branch_idx];
        let source_path = current_branch.full_path(path);
        
        // Verify the file exists on the current branch
        if !source_path.exists() {
            return Err(MoveError::FileNotFound);
        }
        
        // Filter branches to exclude the current one
        let available_branches: Vec<Arc<Branch>> = branches.iter()
            .enumerate()
            .filter(|(idx, _)| *idx != current_branch_idx)
            .map(|(_, branch)| branch.clone())
            .collect();
        
        if available_branches.is_empty() {
            return Err(MoveError::NoSpaceAvailable);
        }
        
        // Get the configured policy or use fallback
        let policy_name = self.get_policy_name();
        let policy: Box<dyn CreatePolicy> = crate::policy::create_policy_from_name(&policy_name)
            .unwrap_or_else(|| {
                tracing::warn!("Unknown moveonenospc policy '{}', using fallback", policy_name);
                Box::new(crate::policy::ProportionalFillRandomDistributionCreatePolicy::new())
            });
        
        // Select target branch using the policy
        let target_branch = policy.select_branch(&available_branches, path)?;
        
        // Find the index of the selected branch in the original array
        let new_branch_idx = branches.iter()
            .position(|b| Arc::ptr_eq(b, &target_branch))
            .ok_or(MoveError::NoSpaceAvailable)?;
        
        tracing::info!("Selected target branch {} for file move", new_branch_idx);
        
        // Perform the actual file move
        self.move_file_between_branches(
            path,
            current_branch,
            &target_branch,
            fd,
        )?;
        
        Ok(MoveResult {
            new_branch_idx,
            new_path: target_branch.full_path(path),
        })
    }
    
    /// Move a file from one branch to another
    fn move_file_between_branches(
        &self,
        path: &Path,
        src_branch: &Branch,
        dst_branch: &Branch,
        fd: Option<RawFd>,
    ) -> Result<(), MoveError> {
        let src_path = src_branch.full_path(path);
        let dst_path = dst_branch.full_path(path);
        
        tracing::debug!("Moving file from {:?} to {:?}", src_path, dst_path);
        
        // Create parent directories on destination branch
        if let Some(parent) = dst_path.parent() {
            std::fs::create_dir_all(parent)?;
            
            // Clone directory metadata
            if let Some(src_parent) = src_path.parent() {
                self.clone_directory_metadata(src_parent, parent)?;
            }
        }
        
        // Create temporary file on destination
        let temp_file = NamedTempFile::new_in(
            dst_path.parent().unwrap_or(Path::new("/"))
        )?;
        let temp_path = temp_file.path().to_path_buf();
        
        // Copy file contents
        self.copy_file_contents(&src_path, &temp_path)?;
        
        // Copy file metadata
        self.copy_file_metadata(&src_path, &temp_path)?;
        
        // If we have a file descriptor, we need to handle it specially
        if let Some(old_fd) = fd {
            // Get the original file flags
            let flags = self.get_file_flags(old_fd)?;
            let clean_flags = self.clean_open_flags(flags);
            
            // Persist the temp file (prevents deletion on drop)
            let _temp_file = temp_file.persist(&dst_path)
                .map_err(|e| MoveError::IoError(e.error))?;
            
            // Open the new file
            // Use hardcoded constants for MUSL compatibility
            const O_RDONLY: i32 = 0;
            const O_WRONLY: i32 = 1;
            const O_RDWR: i32 = 2;
            const O_APPEND: i32 = 1024;
            
            let new_file = OpenOptions::new()
                .read(clean_flags & O_RDWR == O_RDWR || (clean_flags & (O_WRONLY | O_RDWR)) == 0)
                .write(clean_flags & O_WRONLY == O_WRONLY || clean_flags & O_RDWR == O_RDWR)
                .append(clean_flags & O_APPEND != 0)
                .open(&dst_path)?;
            
            let new_fd = new_file.as_raw_fd();
            
            // Replace the old fd with the new one
            dup2(new_fd, old_fd)?;
            
            // The new_file will be closed when it goes out of scope
        } else {
            // No file descriptor to update, just rename
            let _temp_file = temp_file.persist(&dst_path)
                .map_err(|e| MoveError::IoError(e.error))?;
        }
        
        // Remove the original file
        std::fs::remove_file(&src_path)?;
        
        tracing::info!("Successfully moved file from {:?} to {:?}", src_path, dst_path);
        
        Ok(())
    }
    
    /// Copy file contents from source to destination
    fn copy_file_contents(&self, src: &Path, dst: &Path) -> Result<(), io::Error> {
        let mut src_file = File::open(src)?;
        let mut dst_file = OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(dst)?;
        
        // Use a buffer for efficient copying
        let mut buffer = vec![0u8; 64 * 1024]; // 64KB buffer
        
        loop {
            let bytes_read = src_file.read(&mut buffer)?;
            if bytes_read == 0 {
                break;
            }
            dst_file.write_all(&buffer[..bytes_read])?;
        }
        
        dst_file.sync_all()?;
        Ok(())
    }
    
    /// Copy file metadata (permissions, ownership, timestamps)
    fn copy_file_metadata(&self, src: &Path, dst: &Path) -> Result<(), io::Error> {
        let metadata = std::fs::metadata(src)?;
        
        // Copy permissions
        std::fs::set_permissions(dst, metadata.permissions())?;
        
        // Copy timestamps
        let atime = filetime::FileTime::from_last_access_time(&metadata);
        let mtime = filetime::FileTime::from_last_modification_time(&metadata);
        filetime::set_file_times(dst, atime, mtime)?;
        
        // Copy extended attributes if available
        #[cfg(target_os = "linux")]
        {
            use xattr::{list, get, set};
            if let Ok(attrs) = list(src) {
                for attr in attrs {
                    if let Ok(value) = get(src, &attr) {
                        if let Some(value) = value {
                            let _ = set(dst, &attr, &value);
                        }
                    }
                }
            }
        }
        
        Ok(())
    }
    
    /// Clone directory metadata
    fn clone_directory_metadata(&self, src: &Path, dst: &Path) -> Result<(), io::Error> {
        if !dst.exists() {
            return Ok(());
        }
        
        let metadata = std::fs::metadata(src)?;
        
        // Copy directory permissions
        std::fs::set_permissions(dst, metadata.permissions())?;
        
        // Copy timestamps
        let atime = filetime::FileTime::from_last_access_time(&metadata);
        let mtime = filetime::FileTime::from_last_modification_time(&metadata);
        filetime::set_file_times(dst, atime, mtime)?;
        
        Ok(())
    }
    
    /// Get file descriptor flags
    fn get_file_flags(&self, fd: RawFd) -> Result<i32, nix::Error> {
        use nix::fcntl::{fcntl, FcntlArg};
        fcntl(fd, FcntlArg::F_GETFL)
    }
    
    /// Clean open flags (remove O_CREAT, O_EXCL, O_TRUNC)
    fn clean_open_flags(&self, flags: i32) -> i32 {
        // Use hardcoded constants for MUSL compatibility
        const O_CREAT: i32 = 64;
        const O_EXCL: i32 = 128;
        const O_TRUNC: i32 = 512;
        
        flags & !(O_CREAT | O_EXCL | O_TRUNC)
    }
}

/// Helper function to check if an error is ENOSPC or EDQUOT
pub fn is_out_of_space_error(error: &io::Error) -> bool {
    // Use hardcoded constants for MUSL compatibility
    const ENOSPC: i32 = 28;   // No space left on device
    const EDQUOT: i32 = 122;  // Disk quota exceeded
    
    match error.raw_os_error() {
        Some(ENOSPC) => true,
        Some(EDQUOT) => true,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;
    
    #[test]
    fn test_is_out_of_space_error() {
        // Test ENOSPC
        let enospc = io::Error::from_raw_os_error(28); // ENOSPC
        assert!(is_out_of_space_error(&enospc));
        
        // Test EDQUOT
        let edquot = io::Error::from_raw_os_error(122); // EDQUOT
        assert!(is_out_of_space_error(&edquot));
        
        // Test other errors
        let enoent = io::Error::from_raw_os_error(2); // ENOENT
        assert!(!is_out_of_space_error(&enoent));
    }
    
    #[test]
    fn test_clean_open_flags() {
        let handler = MoveOnENOSPCHandler::new(config::create_config());
        
        // Use hardcoded constants
        const O_RDWR: i32 = 2;
        const O_CREAT: i32 = 64;
        const O_EXCL: i32 = 128;
        const O_APPEND: i32 = 1024;
        const O_TRUNC: i32 = 512;
        
        let flags = O_RDWR | O_CREAT | O_EXCL | O_APPEND;
        let clean = handler.clean_open_flags(flags);
        
        assert_eq!(clean, O_RDWR | O_APPEND);
        assert!(clean & O_CREAT == 0);
        assert!(clean & O_EXCL == 0);
        assert!(clean & O_TRUNC == 0);
    }
}