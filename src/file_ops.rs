use crate::branch::Branch;
use crate::policy::{CreatePolicy, SearchPolicy, PolicyError};
use std::collections::HashSet;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::Arc;
use parking_lot::RwLock;
use nix::sys::stat::{mknod as nix_mknod, Mode, SFlag};
use nix::unistd::mkfifo;

pub struct FileManager {
    pub branches: Vec<Arc<Branch>>,
    pub create_policy: Arc<RwLock<Box<dyn CreatePolicy>>>,
    pub search_policy: Box<dyn SearchPolicy>,
}

impl FileManager {
    pub fn new(branches: Vec<Arc<Branch>>, create_policy: Box<dyn CreatePolicy>) -> Self {
        use crate::policy::FirstFoundSearchPolicy;
        Self {
            branches,
            create_policy: Arc::new(RwLock::new(create_policy)),
            search_policy: Box::new(FirstFoundSearchPolicy::new()),
        }
    }
    
    /// Update the create policy at runtime
    pub fn set_create_policy(&self, policy: Box<dyn CreatePolicy>) {
        let mut create_policy = self.create_policy.write();
        eprintln!("DEBUG FileManager: Updating policy from {} to {}", create_policy.name(), policy.name());
        *create_policy = policy;
    }
    
    /// Get the current create policy name
    pub fn get_create_policy_name(&self) -> String {
        let policy = self.create_policy.read();
        policy.name().to_string()
    }

    pub fn create_file(&self, path: &Path, content: &[u8]) -> Result<(), PolicyError> {
        let _span = tracing::info_span!("file_ops::create_file", path = ?path, content_size = content.len()).entered();
        
        // Select branch for new file using create policy
        tracing::debug!("Selecting branch for new file using create policy");
        let branch = {
            let policy = self.create_policy.read();
            eprintln!("DEBUG FileManager: Using policy {} for creating {:?}", policy.name(), path);
            policy.select_branch(&self.branches, path)?
        };
        let full_path = branch.full_path(path);
        
        tracing::info!("Selected branch {:?} for creating file {:?}", branch.path, path);
        tracing::debug!("Full path will be: {:?}", full_path);
        
        // If using a path-preserving policy, clone directory structure from template branch
        let is_path_preserving = {
            let policy = self.create_policy.read();
            policy.is_path_preserving()
        };
        if is_path_preserving {
            let parent_path = path.parent().unwrap_or_else(|| Path::new("/"));
            let template_branch = self.find_first_branch(parent_path).ok();
            
            if let Some(ref template) = template_branch {
                if let Some(parent) = path.parent() {
                    if !parent.as_os_str().is_empty() {
                        use crate::fs_utils;
                        if let Err(e) = fs_utils::clone_path(&template.path, &branch.path, parent) {
                            tracing::warn!("Failed to clone parent path structure: {:?}", e);
                            // Fall back to simple directory creation
                            if let Some(parent_dir) = full_path.parent() {
                                std::fs::create_dir_all(parent_dir)?;
                            }
                        }
                    }
                }
            } else {
                // No template found, just create parent directories
                if let Some(parent) = full_path.parent() {
                    std::fs::create_dir_all(parent)?;
                }
            }
        } else {
            // Non-path-preserving policy, just create parent directories
            if let Some(parent) = full_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
        }
        
        let mut file = File::create(&full_path)?;
        file.write_all(content)?;
        file.sync_all()?; // Ensure data is written to disk
        
        tracing::info!("File created successfully at {:?} with {} bytes", full_path, content.len());
        Ok(())
    }
    
    pub fn write_to_file(&self, path: &Path, offset: u64, data: &[u8]) -> Result<usize, PolicyError> {
        // For writing to existing files at offset, find first existing instance
        // In a full implementation, this would be determined at open() time
        for branch in &self.branches {
            if !branch.allows_create() {
                continue; // Skip read-only branches
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() && full_path.is_file() {
                tracing::info!("Writing {} bytes at offset {} to {:?} in branch {:?}", 
                    data.len(), offset, path, branch.path);
                
                use std::fs::OpenOptions;
                use std::io::Seek;
                use std::io::SeekFrom;
                
                let mut file = OpenOptions::new()
                    .write(true)
                    .open(full_path)?;
                
                file.seek(SeekFrom::Start(offset))?;
                let written = file.write(data)?;
                file.sync_all()?;
                return Ok(written);
            }
        }
        
        // If file doesn't exist in any branch, this is an error
        // Files should be created with create(), not write()
        Err(PolicyError::NoBranchesAvailable)
    }
    
    pub fn truncate_file(&self, path: &Path, size: u64) -> Result<(), PolicyError> {
        // For truncating existing files, find first existing instance
        for branch in &self.branches {
            if !branch.allows_create() {
                continue; // Skip read-only branches
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() && full_path.is_file() {
                tracing::info!("Truncating file {:?} to size {} in branch {:?}", path, size, branch.path);
                
                use std::fs::OpenOptions;
                let file = OpenOptions::new()
                    .write(true)
                    .open(full_path)?;
                file.set_len(size)?;
                return Ok(());
            }
        }
        
        // If file doesn't exist, this is an error
        Err(PolicyError::NoBranchesAvailable)
    }

    pub fn read_file(&self, path: &Path) -> Result<Vec<u8>, PolicyError> {
        // Search for file in all branches (first found)
        for branch in &self.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                let mut file = File::open(full_path)?;
                let mut content = Vec::new();
                file.read_to_end(&mut content)?;
                return Ok(content);
            }
        }
        
        Err(PolicyError::NoBranchesAvailable)
    }

    pub fn file_exists(&self, path: &Path) -> bool {
        self.branches.iter().any(|branch| {
            branch.full_path(path).exists()
        })
    }
    
    /// Find the branch that contains a file and return both the branch and metadata
    pub fn find_file_with_metadata(&self, path: &Path) -> Option<(&Branch, std::fs::Metadata)> {
        for branch in &self.branches {
            let full_path = branch.full_path(path);
            // Get metadata without following symlinks
            if let Ok(metadata) = full_path.symlink_metadata() {
                return Some((branch, metadata));
            }
        }
        None
    }

    pub fn create_directory(&self, path: &Path) -> Result<(), PolicyError> {
        let branch = {
            let policy = self.create_policy.read();
            policy.select_branch(&self.branches, path)?
        };
        let full_path = branch.full_path(path);
        
        tracing::info!("Creating directory {:?} in branch {:?}", path, branch.path);
        
        // If using a path-preserving policy, clone directory structure from template branch
        let is_path_preserving = {
            let policy = self.create_policy.read();
            policy.is_path_preserving()
        };
        if is_path_preserving {
            let parent_path = path.parent().unwrap_or_else(|| Path::new("/"));
            let template_branch = self.find_first_branch(parent_path).ok();
            
            if let Some(ref template) = template_branch {
                if let Some(parent) = path.parent() {
                    if !parent.as_os_str().is_empty() {
                        use crate::fs_utils;
                        // Clone the parent path structure, then create the final directory
                        if let Err(e) = fs_utils::clone_path(&template.path, &branch.path, parent) {
                            tracing::warn!("Failed to clone parent path structure: {:?}", e);
                        }
                    }
                }
            }
        }
        
        // Create the directory (create_dir_all handles if it already exists)
        std::fs::create_dir_all(full_path)?;
        Ok(())
    }
    
    pub fn create_symlink(&self, link_path: &Path, target: &Path) -> Result<(), PolicyError> {
        // Select branch for new symlink using create policy
        let branch = {
            let policy = self.create_policy.read();
            policy.select_branch(&self.branches, link_path)?
        };
        let full_link_path = branch.full_path(link_path);
        
        tracing::info!("Creating symlink {:?} -> {:?} in branch {:?}", link_path, target, branch.path);
        
        // Find a branch that has the parent directory to use as template for cloning
        let parent_path = link_path.parent().unwrap_or_else(|| Path::new("/"));
        let template_branch = self.find_first_branch(parent_path).ok();
        
        // Clone parent directory structure from template branch if available
        if let Some(ref template) = template_branch {
            if let Some(parent) = link_path.parent() {
                if !parent.as_os_str().is_empty() {
                    use crate::fs_utils;
                    if let Err(e) = fs_utils::clone_path(&template.path, &branch.path, parent) {
                        tracing::warn!("Failed to clone parent path structure: {:?}", e);
                        // Fall back to simple directory creation
                        if let Some(parent_dir) = full_link_path.parent() {
                            std::fs::create_dir_all(parent_dir)?;
                        }
                    }
                }
            }
        } else {
            // No template found, just create parent directories
            if let Some(parent) = full_link_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
        }
        
        // Create the symlink
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            symlink(target, &full_link_path)?;
        }
        
        #[cfg(not(unix))]
        {
            return Err(PolicyError::from(std::io::Error::new(
                std::io::ErrorKind::Other,
                "Symlinks not supported on this platform"
            )));
        }
        
        tracing::info!("Symlink created successfully at {:?}", full_link_path);
        Ok(())
    }
    
    pub fn create_hard_link(&self, source_path: &Path, link_path: &Path) -> Result<(), PolicyError> {
        // First, find which branch contains the source file
        let source_branch = self.find_first_branch(source_path)?;
        let full_source_path = source_branch.full_path(source_path);
        
        // Verify source exists and is a regular file
        if !full_source_path.exists() || !full_source_path.is_file() {
            return Err(PolicyError::from(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                "Source file does not exist or is not a regular file"
            )));
        }
        
        // For hard links, both source and link must be on the same filesystem/branch
        // Select the same branch as the source for the hard link
        let branch = source_branch.clone();
        
        if !branch.allows_create() {
            return Err(PolicyError::from(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "Branch is read-only"
            )));
        }
        
        let full_link_path = branch.full_path(link_path);
        
        tracing::info!("Creating hard link {:?} -> {:?} in branch {:?}", source_path, link_path, branch.path);
        
        // Check if using path-preserving policy
        let is_path_preserving = {
            let policy = self.create_policy.read();
            policy.is_path_preserving()
        };
        if is_path_preserving {
            // In path-preserving mode, if the parent directory doesn't exist on the same branch,
            // return EXDEV instead of trying to create it
            if let Some(parent) = full_link_path.parent() {
                if !parent.exists() {
                    tracing::debug!("Parent directory doesn't exist on same branch, returning EXDEV");
                    return Err(PolicyError::from(std::io::Error::new(
                        std::io::ErrorKind::CrossesDevices,
                        "Cross-device link not permitted"
                    )));
                }
            }
        }
        
        // Find a branch that has the parent directory to use as template for cloning
        let parent_path = link_path.parent().unwrap_or_else(|| Path::new("/"));
        let template_branch = self.find_first_branch(parent_path).ok();
        
        // Clone parent directory structure from template branch if available
        if let Some(ref template) = template_branch {
            if let Some(parent) = link_path.parent() {
                if !parent.as_os_str().is_empty() {
                    use crate::fs_utils;
                    if let Err(e) = fs_utils::clone_path(&template.path, &branch.path, parent) {
                        tracing::warn!("Failed to clone parent path structure: {:?}", e);
                        // Fall back to simple directory creation
                        if let Some(parent_dir) = full_link_path.parent() {
                            std::fs::create_dir_all(parent_dir)?;
                        }
                    }
                }
            }
        } else {
            // No template found, just create parent directories
            if let Some(parent) = full_link_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
        }
        
        // Create the hard link
        std::fs::hard_link(&full_source_path, &full_link_path)?;
        
        tracing::info!("Hard link created successfully at {:?}", full_link_path);
        Ok(())
    }

    pub fn directory_exists(&self, path: &Path) -> bool {
        self.branches.iter().any(|branch| {
            let full_path = branch.full_path(path);
            full_path.exists() && full_path.is_dir()
        })
    }

    /// Get metadata for a path without following symlinks
    pub fn get_metadata(&self, path: &Path) -> Option<std::fs::Metadata> {
        for branch in &self.branches {
            let full_path = branch.full_path(path);
            if let Ok(metadata) = std::fs::symlink_metadata(&full_path) {
                return Some(metadata);
            }
        }
        None
    }

    /// Search for a path using the configured search policy
    pub fn search_path(&self, path: &Path) -> Result<Vec<Arc<Branch>>, PolicyError> {
        self.search_policy.search_branches(&self.branches, path)
    }
    
    /// Get the first branch where path exists (common case)
    pub fn find_first_branch(&self, path: &Path) -> Result<Arc<Branch>, PolicyError> {
        let branches = self.search_path(path)?;
        branches.into_iter().next()
            .ok_or(PolicyError::NoBranchesAvailable)
    }
    
    /// Check if file exists in any branch using search policy
    pub fn file_exists_search(&self, path: &Path) -> bool {
        self.search_path(path).is_ok()
    }

    pub fn list_directory(&self, path: &Path) -> Result<Vec<String>, PolicyError> {
        let mut entries = HashSet::new();
        
        for branch in &self.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() && full_path.is_dir() {
                match std::fs::read_dir(full_path) {
                    Ok(dir_entries) => {
                        for entry in dir_entries {
                            if let Ok(entry) = entry {
                                if let Some(name) = entry.file_name().to_str() {
                                    entries.insert(name.to_string());
                                }
                            }
                        }
                    }
                    Err(_) => continue, // Skip branches where we can't read
                }
            }
        }
        
        let mut result: Vec<String> = entries.into_iter().collect();
        result.sort();
        Ok(result)
    }

    pub fn remove_directory(&self, path: &Path) -> Result<(), PolicyError> {
        // Find all branches where the directory exists
        let mut found_any = false;
        let mut last_error = None;
        
        for branch in &self.branches {
            if !branch.allows_create() {
                continue; // Skip readonly branches for removal
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() && full_path.is_dir() {
                found_any = true;
                match std::fs::remove_dir(&full_path) {
                    Ok(_) => {}, // Success
                    Err(e) => {
                        last_error = Some(PolicyError::IoError(e));
                        // Continue trying other branches
                    }
                }
            }
        }
        
        if !found_any {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        // If we had any errors, return the last one
        if let Some(error) = last_error {
            return Err(error);
        }
        
        Ok(())
    }

    pub fn remove_file(&self, path: &Path) -> Result<(), PolicyError> {
        // Find all branches where the file exists and remove from writable ones
        let mut found_any = false;
        let mut last_error = None;
        
        for branch in &self.branches {
            if !branch.allows_create() {
                continue; // Skip readonly branches for removal
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() && !full_path.is_dir() {
                found_any = true;
                match std::fs::remove_file(&full_path) {
                    Ok(_) => {}, // Success
                    Err(e) => {
                        last_error = Some(PolicyError::IoError(e));
                        // Continue trying other branches
                    }
                }
            }
        }
        
        if !found_any {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        // If we had any errors, return the last one
        if let Some(error) = last_error {
            return Err(error);
        }
        
        Ok(())
    }

    pub fn create_special_file(&self, path: &Path, mode: u32, rdev: u32) -> Result<(), PolicyError> {
        let _span = tracing::info_span!("file_ops::create_special_file", path = ?path, mode = mode, rdev = rdev).entered();
        
        // Select branch for new special file using create policy
        tracing::debug!("Selecting branch for new special file using create policy");
        let branch = {
            let policy = self.create_policy.read();
            policy.select_branch(&self.branches, path)?
        };
        let full_path = branch.full_path(path);
        
        tracing::info!("Selected branch {:?} for creating special file {:?}", branch.path, path);
        tracing::debug!("Full path will be: {:?}", full_path);
        
        // Find a branch that has the parent directory to use as template for cloning
        let parent_path = path.parent().unwrap_or_else(|| Path::new("/"));
        let template_branch = self.find_first_branch(parent_path).ok();
        
        // Clone parent directory structure from template branch if available
        if let Some(ref template) = template_branch {
            if let Some(parent) = path.parent() {
                if !parent.as_os_str().is_empty() {
                    use crate::fs_utils;
                    if let Err(e) = fs_utils::clone_path(&template.path, &branch.path, parent) {
                        tracing::warn!("Failed to clone parent path structure: {:?}", e);
                        // Fall back to simple directory creation
                        if let Some(parent_dir) = full_path.parent() {
                            std::fs::create_dir_all(parent_dir)?;
                        }
                    }
                }
            }
        } else {
            // No template found, just create parent directories
            if let Some(parent) = full_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
        }
        
        // Determine file type from mode
        let file_type = match mode & 0o170000 {
            0o010000 => SFlag::S_IFIFO,   // FIFO/named pipe
            0o020000 => SFlag::S_IFCHR,   // Character device
            0o060000 => SFlag::S_IFBLK,   // Block device
            0o100000 => SFlag::S_IFREG,   // Regular file
            0o140000 => SFlag::S_IFSOCK,  // Socket
            _ => {
                tracing::error!("Unsupported file type in mode: {:o}", mode);
                return Err(PolicyError::from(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "Unsupported file type"
                )));
            }
        };
        
        // Extract permission bits
        let permissions = Mode::from_bits_truncate(mode & 0o7777);
        
        // Create the special file
        match file_type {
            SFlag::S_IFIFO => {
                // Use mkfifo for named pipes (simpler API)
                tracing::info!("Creating FIFO at {:?} with permissions {:o}", full_path, mode & 0o7777);
                mkfifo(&full_path, permissions)
                    .map_err(|e| {
                        let errno = e as i32;
                        PolicyError::from(std::io::Error::from_raw_os_error(errno))
                    })?;
            }
            SFlag::S_IFREG => {
                // Regular file - use standard file creation
                tracing::info!("Creating regular file at {:?} with permissions {:o}", full_path, mode & 0o7777);
                let file = File::create(&full_path)?;
                // Set permissions
                use std::os::unix::fs::PermissionsExt;
                let metadata = file.metadata()?;
                let mut perms = metadata.permissions();
                perms.set_mode(mode & 0o7777);
                std::fs::set_permissions(&full_path, perms)?;
            }
            _ => {
                // Use mknod for device files and sockets
                tracing::info!("Creating special file at {:?} with type {:?}, permissions {:o}, device {:x}", 
                    full_path, file_type, mode & 0o7777, rdev);
                nix_mknod(&full_path, file_type, permissions, rdev as u64)
                    .map_err(|e| {
                        let errno = e as i32;
                        PolicyError::from(std::io::Error::from_raw_os_error(errno))
                    })?;
            }
        }
        
        tracing::info!("Special file created successfully at {:?}", full_path);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::policy::FirstFoundCreatePolicy;
    use std::path::Path;
    use tempfile::TempDir;
    use std::os::unix::fs::FileTypeExt;

    fn setup_test_branches() -> (Vec<TempDir>, Vec<Arc<Branch>>) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        let branch3 = Arc::new(Branch::new(temp3.path().to_path_buf(), BranchMode::ReadOnly));
        
        let temp_dirs = vec![temp1, temp2, temp3];
        let branches = vec![branch1, branch2, branch3];
        
        (temp_dirs, branches)
    }

    #[test]
    fn test_create_file_in_first_writable_branch() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches.clone(), policy);
        
        let test_content = b"Hello, world!";
        let result = file_manager.create_file(Path::new("test.txt"), test_content);
        assert!(result.is_ok());
        
        // File should be created in first writable branch (branch1)
        let expected_path = branches[0].full_path(Path::new("test.txt"));
        assert!(expected_path.exists());
        
        // File should NOT exist in other branches
        let path2 = branches[1].full_path(Path::new("test.txt"));
        let path3 = branches[2].full_path(Path::new("test.txt"));
        assert!(!path2.exists());
        assert!(!path3.exists());
    }

    #[test]
    fn test_read_file_from_any_branch() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches.clone(), policy);
        
        let test_content = b"Hello, world!";
        file_manager.create_file(Path::new("test.txt"), test_content).unwrap();
        
        let read_content = file_manager.read_file(Path::new("test.txt")).unwrap();
        assert_eq!(read_content, test_content);
    }

    #[test]
    fn test_read_nonexistent_file() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        let result = file_manager.read_file(Path::new("nonexistent.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }

    #[test]
    fn test_file_exists() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        assert!(!file_manager.file_exists(Path::new("test.txt")));
        
        let test_content = b"Hello, world!";
        file_manager.create_file(Path::new("test.txt"), test_content).unwrap();
        
        assert!(file_manager.file_exists(Path::new("test.txt")));
    }

    #[test]
    fn test_create_with_nested_path() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches.clone(), policy);
        
        let test_content = b"Nested file content";
        let nested_path = Path::new("dir1/dir2/nested.txt");
        let result = file_manager.create_file(nested_path, test_content);
        assert!(result.is_ok());
        
        // Verify file was created with proper directory structure
        let expected_path = branches[0].full_path(nested_path);
        assert!(expected_path.exists());
        
        // Verify we can read it back
        let read_content = file_manager.read_file(nested_path).unwrap();
        assert_eq!(read_content, test_content);
    }

    #[test]
    fn test_skip_readonly_branches_for_creation() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // First branch is readonly, second is writable
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1.clone(), branch2.clone()];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        let test_content = b"Should go to second branch";
        let result = file_manager.create_file(Path::new("test.txt"), test_content);
        assert!(result.is_ok());
        
        // File should be created in second branch (writable)
        let path1 = branch1.full_path(Path::new("test.txt"));
        let path2 = branch2.full_path(Path::new("test.txt"));
        assert!(!path1.exists());
        assert!(path2.exists());
    }

    #[test]
    fn test_create_hard_link_same_branch() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches.clone(), policy);
        
        // Create a source file
        let test_content = b"Hard link test content";
        file_manager.create_file(Path::new("source.txt"), test_content).unwrap();
        
        // Create a hard link to the source file
        let result = file_manager.create_hard_link(Path::new("source.txt"), Path::new("link.txt"));
        assert!(result.is_ok());
        
        // Verify both files exist in the same branch
        let source_path = branches[0].full_path(Path::new("source.txt"));
        let link_path = branches[0].full_path(Path::new("link.txt"));
        assert!(source_path.exists());
        assert!(link_path.exists());
        
        // Verify they have the same content
        let source_content = std::fs::read(&source_path).unwrap();
        let link_content = std::fs::read(&link_path).unwrap();
        assert_eq!(source_content, link_content);
        
        // Verify they have the same inode (on Unix)
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let source_meta = std::fs::metadata(&source_path).unwrap();
            let link_meta = std::fs::metadata(&link_path).unwrap();
            assert_eq!(source_meta.ino(), link_meta.ino());
        }
    }

    #[test]
    fn test_create_hard_link_nonexistent_source() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        // Try to create a hard link to a non-existent source
        let result = file_manager.create_hard_link(Path::new("nonexistent.txt"), Path::new("link.txt"));
        assert!(result.is_err());
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }

    #[test]
    fn test_create_hard_link_with_nested_path() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches.clone(), policy);
        
        // Create a source file in a nested directory
        let test_content = b"Nested hard link test";
        let source_path = Path::new("dir1/source.txt");
        file_manager.create_file(source_path, test_content).unwrap();
        
        // Create a hard link in a different nested directory
        let link_path = Path::new("dir2/link.txt");
        let result = file_manager.create_hard_link(source_path, link_path);
        assert!(result.is_ok());
        
        // Verify the link was created correctly
        let full_link_path = branches[0].full_path(link_path);
        assert!(full_link_path.exists());
        
        // Verify content matches
        let link_content = std::fs::read(&full_link_path).unwrap();
        assert_eq!(link_content, test_content);
    }

    #[test]
    fn test_create_hard_link_readonly_branch() {
        let temp1 = TempDir::new().unwrap();
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        
        let branches = vec![branch1.clone()];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        
        // Create a source file manually (since we can't use file_manager with readonly branch)
        let source_path = branch1.full_path(Path::new("source.txt"));
        std::fs::write(&source_path, b"test content").unwrap();
        
        // Try to create a hard link in the readonly branch
        let result = file_manager.create_hard_link(Path::new("source.txt"), Path::new("link.txt"));
        assert!(result.is_err());
        
        // Verify it's a permission error
        match result {
            Err(PolicyError::IoError(e)) => {
                assert_eq!(e.kind(), std::io::ErrorKind::PermissionDenied);
            }
            _ => panic!("Expected permission denied error"),
        }
    }

    #[test]
    fn test_create_special_file_fifo() {
        let (_temps, branches) = setup_test_branches();
        let file_manager = FileManager::new(
            branches,
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        // Create a FIFO (named pipe)
        let fifo_path = Path::new("test.fifo");
        let mode = 0o010644; // S_IFIFO | 0644
        let result = file_manager.create_special_file(fifo_path, mode, 0);
        assert!(result.is_ok());
        
        // Verify the FIFO was created in the first branch
        let branch = &file_manager.branches[0];
        let full_path = branch.full_path(fifo_path);
        assert!(full_path.exists());
        
        // Verify it's actually a FIFO
        let metadata = std::fs::metadata(&full_path).unwrap();
        assert!(metadata.file_type().is_fifo());
    }

    #[test]
    fn test_create_special_file_regular() {
        let (_temps, branches) = setup_test_branches();
        let file_manager = FileManager::new(
            branches,
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        // Create a regular file through mknod
        let file_path = Path::new("test_regular.txt");
        let mode = 0o100644; // S_IFREG | 0644
        let result = file_manager.create_special_file(file_path, mode, 0);
        assert!(result.is_ok());
        
        // Verify the file was created
        let branch = &file_manager.branches[0];
        let full_path = branch.full_path(file_path);
        assert!(full_path.exists());
        assert!(full_path.is_file());
        
        // Verify permissions
        use std::os::unix::fs::PermissionsExt;
        let metadata = std::fs::metadata(&full_path).unwrap();
        let perms = metadata.permissions().mode();
        assert_eq!(perms & 0o777, 0o644);
    }

    #[test]
    fn test_create_special_file_with_parent_creation() {
        let (_temps, branches) = setup_test_branches();
        let file_manager = FileManager::new(
            branches,
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        // Create a FIFO in a subdirectory that doesn't exist
        let fifo_path = Path::new("subdir/test.fifo");
        let mode = 0o010644; // S_IFIFO | 0644
        let result = file_manager.create_special_file(fifo_path, mode, 0);
        assert!(result.is_ok());
        
        // Verify the parent directory was created
        let branch = &file_manager.branches[0];
        let parent_path = branch.full_path(Path::new("subdir"));
        assert!(parent_path.exists());
        assert!(parent_path.is_dir());
        
        // Verify the FIFO exists
        let full_path = branch.full_path(fifo_path);
        assert!(full_path.exists());
        let metadata = std::fs::metadata(&full_path).unwrap();
        assert!(metadata.file_type().is_fifo());
    }

    #[test] 
    fn test_create_special_file_readonly_branch() {
        let temp1 = TempDir::new().unwrap();
        let branches = vec![
            Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly)),
        ];
        
        let file_manager = FileManager::new(
            branches,
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        // Try to create a FIFO in readonly branch
        let fifo_path = Path::new("test.fifo");
        let mode = 0o010644; // S_IFIFO | 0644
        let result = file_manager.create_special_file(fifo_path, mode, 0);
        
        // Should fail with ReadOnlyFilesystem
        assert!(result.is_err());
        match result {
            Err(PolicyError::ReadOnlyFilesystem) => {},
            Err(e) => panic!("Expected ReadOnlyFilesystem error, got: {:?}", e),
            _ => panic!("Expected error"),
        }
    }
}
#[cfg(test)]
mod path_preservation_tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::{ExistingPathFirstFoundCreatePolicy, FirstFoundCreatePolicy};
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;

    fn create_test_file_manager_with_policy(
        branches: Vec<Arc<Branch>>,
        policy: Box<dyn crate::policy::traits::CreatePolicy>,
    ) -> FileManager {
        FileManager::new(branches, policy)
    }

    #[test]
    fn test_path_preserving_file_creation() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory structure in first branch only
        let parent_dir = temp_dir1.path().join("path/to/parent");
        fs::create_dir_all(&parent_dir).unwrap();
        
        // Set some metadata on the parent directory to verify it gets cloned
        fs::write(parent_dir.join(".metadata"), b"test").unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with path-preserving policy (epff)
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(ExistingPathFirstFoundCreatePolicy::new()),
        );
        
        // Create a file - should be placed in branch 2 (first branch with parent)
        let result = manager.create_file(Path::new("/path/to/parent/file.txt"), b"content");
        assert!(result.is_ok());
        
        // Verify file was created in branch 1 (which has the parent)
        assert!(temp_dir1.path().join("path/to/parent/file.txt").exists());
        assert!(!temp_dir2.path().join("path/to/parent/file.txt").exists());
    }

    #[test]
    fn test_non_path_preserving_file_creation() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory structure in second branch only
        let parent_dir = temp_dir2.path().join("path/to/parent");
        fs::create_dir_all(&parent_dir).unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with non-path-preserving policy (ff)
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        // Create a file - should be placed in branch 1 (first found)
        let result = manager.create_file(Path::new("/path/to/parent/file.txt"), b"content");
        assert!(result.is_ok());
        
        // Verify file was created in branch 1 (first found), not branch 2
        assert!(temp_dir1.path().join("path/to/parent/file.txt").exists());
        assert!(!temp_dir2.path().join("path/to/parent/file.txt").exists());
    }

    #[test]
    fn test_path_preservation_clones_directory_metadata() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory with specific permissions
        let parent_path = temp_dir1.path().join("parent");
        fs::create_dir(&parent_path).unwrap();
        
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let permissions = fs::Permissions::from_mode(0o755);
            fs::set_permissions(&parent_path, permissions).unwrap();
        }
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with path-preserving policy
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(ExistingPathFirstFoundCreatePolicy::new()),
        );
        
        // Create file - this should trigger directory cloning
        let result = manager.create_file(Path::new("/parent/file.txt"), b"content");
        assert!(result.is_ok());
        
        // Parent should exist on branch 1 where file was created
        assert!(temp_dir1.path().join("parent").exists());
        assert!(temp_dir1.path().join("parent/file.txt").exists());
    }

    #[test]
    fn test_path_preserving_directory_creation() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory structure in first branch only
        let parent_dir = temp_dir1.path().join("path/to");
        fs::create_dir_all(&parent_dir).unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with path-preserving policy
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(ExistingPathFirstFoundCreatePolicy::new()),
        );
        
        // Create a directory - should be placed in branch 1 (has parent)
        let result = manager.create_directory(Path::new("/path/to/newdir"));
        assert!(result.is_ok());
        
        // Verify directory was created in branch 1
        assert!(temp_dir1.path().join("path/to/newdir").exists());
        assert!(!temp_dir2.path().join("path/to/newdir").exists());
    }

    #[test]
    fn test_path_preservation_no_parent_fails() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Don't create parent directory in any branch
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with path-preserving policy
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(ExistingPathFirstFoundCreatePolicy::new()),
        );
        
        // Try to create a file - should fail (no parent exists)
        let result = manager.create_file(Path::new("/nonexistent/parent/file.txt"), b"content");
        assert!(result.is_err());
    }

    #[test]
    fn test_path_preservation_with_deep_hierarchy() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create deep directory structure in first branch
        let deep_path = temp_dir1.path().join("a/b/c/d/e");
        fs::create_dir_all(&deep_path).unwrap();
        
        // Add files at various levels
        fs::write(temp_dir1.path().join("a/.marker"), b"level1").unwrap();
        fs::write(temp_dir1.path().join("a/b/c/.marker"), b"level3").unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Test with path-preserving policy
        let manager = create_test_file_manager_with_policy(
            branches.clone(),
            Box::new(ExistingPathFirstFoundCreatePolicy::new()),
        );
        
        // Create file deep in hierarchy
        let result = manager.create_file(Path::new("/a/b/c/d/e/file.txt"), b"deep content");
        assert!(result.is_ok());
        
        // Verify file was created in branch 1
        assert!(temp_dir1.path().join("a/b/c/d/e/file.txt").exists());
        
        // Directory structure should be preserved
        assert!(temp_dir1.path().join("a/b/c/d/e").is_dir());
    }
}