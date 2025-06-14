use crate::branch::Branch;
use crate::policy::{CreatePolicy, SearchPolicy, PolicyError};
use std::collections::HashSet;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::Arc;

pub struct FileManager {
    pub branches: Vec<Arc<Branch>>,
    pub create_policy: Box<dyn CreatePolicy>,
    pub search_policy: Box<dyn SearchPolicy>,
}

impl FileManager {
    pub fn new(branches: Vec<Arc<Branch>>, create_policy: Box<dyn CreatePolicy>) -> Self {
        use crate::policy::FirstFoundSearchPolicy;
        Self {
            branches,
            create_policy,
            search_policy: Box::new(FirstFoundSearchPolicy::new()),
        }
    }

    pub fn create_file(&self, path: &Path, content: &[u8]) -> Result<(), PolicyError> {
        // Select branch for new file using create policy
        let branch = self.create_policy.select_branch(&self.branches, path)?;
        let full_path = branch.full_path(path);
        
        tracing::info!("Creating new file {:?} in branch {:?}", path, branch.path);
        tracing::info!("Full path will be: {:?}", full_path);
        
        // Create parent directories if needed
        if let Some(parent) = full_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        
        let mut file = File::create(&full_path)?;
        file.write_all(content)?;
        file.sync_all()?; // Ensure data is written to disk
        
        tracing::info!("File created successfully at {:?}", full_path);
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

    pub fn create_directory(&self, path: &Path) -> Result<(), PolicyError> {
        let branch = self.create_policy.select_branch(&self.branches, path)?;
        let full_path = branch.full_path(path);
        
        std::fs::create_dir_all(full_path)?;
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
            if full_path.exists() && full_path.is_file() {
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::policy::FirstFoundCreatePolicy;
    use std::path::Path;
    use tempfile::TempDir;

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
}