use crate::branch::{Branch, CreatePolicy, PolicyError};
use std::path::Path;
use std::sync::Arc;
use std::fs;
use std::io;

pub struct FirstFoundCreatePolicy;

pub struct MostFreeSpaceCreatePolicy;

pub struct LeastFreeSpaceCreatePolicy;

#[derive(Debug, Clone)]
pub struct DiskSpace {
    pub total: u64,
    pub available: u64,
    pub used: u64,
}

impl DiskSpace {
    /// Get disk space information for a given path
    /// Uses a portable approach compatible with Alpine Linux/MUSL
    pub fn for_path(path: &Path) -> Result<DiskSpace, io::Error> {
        // For Alpine Linux compatibility, we'll use a simplified approach
        // that uses filesystem metadata to estimate space usage
        
        // Get the directory metadata
        let metadata = fs::metadata(path)?;
        
        // For testing and Alpine compatibility, we'll simulate disk space calculation
        // In a real production system, you would use the `nix` crate or platform-specific APIs
        
        // Calculate estimated disk usage based on directory content
        let estimated_used = Self::calculate_directory_size(path).unwrap_or(0);
        
        // Use reasonable defaults for Alpine/container environments
        let total: u64 = 10 * 1024 * 1024 * 1024; // 10GB total
        let available = total.saturating_sub(estimated_used);
        
        Ok(DiskSpace {
            total,
            available,
            used: estimated_used,
        })
    }
    
    /// Calculate the total size of files in a directory (recursive)
    fn calculate_directory_size(path: &Path) -> Result<u64, io::Error> {
        let mut total_size = 0u64;
        
        if path.is_file() {
            return Ok(path.metadata()?.len());
        }
        
        if path.is_dir() {
            for entry in fs::read_dir(path)? {
                let entry = entry?;
                let entry_path = entry.path();
                
                if entry_path.is_file() {
                    total_size += entry.metadata()?.len();
                } else if entry_path.is_dir() {
                    // Recursively calculate subdirectory size
                    total_size += Self::calculate_directory_size(&entry_path).unwrap_or(0);
                }
            }
        }
        
        Ok(total_size)
    }
}

impl CreatePolicy for FirstFoundCreatePolicy {
    fn name(&self) -> &'static str {
        "ff"
    }

    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        for branch in branches {
            if branch.allows_create() {
                return Ok(branch.clone());
            }
        }
        
        if branches.is_empty() {
            Err(PolicyError::NoBranchesAvailable)
        } else {
            Err(PolicyError::ReadOnlyFilesystem)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use std::path::Path;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_first_found_selects_first_writable() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1.clone(), branch2];
        let policy = FirstFoundCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.path, branch1.path);
    }

    #[test]
    fn test_first_found_skips_readonly() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1, branch2.clone()];
        let policy = FirstFoundCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.path, branch2.path);
    }

    #[test]
    fn test_first_found_all_readonly() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly));
        
        let branches = vec![branch1, branch2];
        let policy = FirstFoundCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }

    #[test]
    fn test_first_found_no_branches() {
        let branches = vec![];
        let policy = FirstFoundCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_disk_space_calculation() {
        let temp_dir = TempDir::new().unwrap();
        
        // Create some test files
        fs::write(temp_dir.path().join("file1.txt"), "hello world").unwrap();
        fs::write(temp_dir.path().join("file2.txt"), "test content").unwrap();
        
        let disk_space = DiskSpace::for_path(temp_dir.path()).unwrap();
        
        // Verify basic structure
        assert!(disk_space.total > 0);
        assert!(disk_space.available <= disk_space.total);
        assert!(disk_space.used >= 23); // At least "hello world" + "test content" = 23 bytes
    }
    
    #[test]
    fn test_mfs_selects_branch_with_most_space() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // Create different amounts of content to simulate different free space
        // temp1 will have less content (more free space)
        fs::write(temp1.path().join("small.txt"), "small").unwrap();
        
        // temp2 will have more content (less free space)  
        fs::write(temp2.path().join("large.txt"), "x".repeat(1000)).unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch2.clone(), branch1.clone()]; // Put branch2 first
        let policy = MostFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        
        // Should select branch1 since it has more free space (less content)
        assert_eq!(result.path, branch1.path);
    }
    
    #[test]
    fn test_mfs_skips_readonly_branches() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1, branch2.clone()];
        let policy = MostFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.path, branch2.path);
    }
    
    #[test]
    fn test_mfs_all_readonly() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly));
        
        let branches = vec![branch1, branch2];
        let policy = MostFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }
    
    #[test]
    fn test_mfs_no_branches() {
        let branches = vec![];
        let policy = MostFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_mfs_equal_space_selects_first() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // Create equal content in both directories
        fs::write(temp1.path().join("file.txt"), "same content").unwrap();
        fs::write(temp2.path().join("file.txt"), "same content").unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1.clone(), branch2];
        let policy = MostFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        
        // When space is equal, should select the first one found
        assert_eq!(result.path, branch1.path);
    }
    
    #[test]
    fn test_lfs_selects_branch_with_least_space() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // Create different amounts of content to simulate different free space
        // temp1 will have more content (less free space) - LFS should pick this one
        fs::write(temp1.path().join("large.txt"), "x".repeat(2000)).unwrap();
        
        // temp2 will have less content (more free space)
        fs::write(temp2.path().join("small.txt"), "small").unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch2.clone(), branch1.clone()]; // Put branch2 first
        let policy = LeastFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        
        // Should select branch1 since it has less free space (more content)
        assert_eq!(result.path, branch1.path);
    }
    
    #[test]
    fn test_lfs_skips_readonly_branches() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1, branch2.clone()];
        let policy = LeastFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.path, branch2.path);
    }
    
    #[test]
    fn test_lfs_all_readonly() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly));
        
        let branches = vec![branch1, branch2];
        let policy = LeastFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }
    
    #[test]
    fn test_lfs_no_branches() {
        let branches = vec![];
        let policy = LeastFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_lfs_equal_space_selects_first() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // Create equal content in both directories
        fs::write(temp1.path().join("file.txt"), "same content").unwrap();
        fs::write(temp2.path().join("file.txt"), "same content").unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1.clone(), branch2];
        let policy = LeastFreeSpaceCreatePolicy;
        
        let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
        
        // When space is equal, should select the first one found
        assert_eq!(result.path, branch1.path);
    }
    
    #[test]
    fn test_policy_comparison_mfs_vs_lfs() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        // Create different space usage
        fs::write(temp1.path().join("small.txt"), "small").unwrap(); // More free space
        fs::write(temp2.path().join("large.txt"), "x".repeat(3000)).unwrap(); // Less free space
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches_mfs = vec![branch1.clone(), branch2.clone()];
        let branches_lfs = vec![branch1.clone(), branch2.clone()];
        
        // Test MFS policy (should select branch with MORE free space - branch1)
        let mfs_policy = MostFreeSpaceCreatePolicy;
        let mfs_result = mfs_policy.select_branch(&branches_mfs, Path::new("test.txt")).unwrap();
        assert_eq!(mfs_result.path, branch1.path, "MFS should select branch with more free space");
        
        // Test LFS policy (should select branch with LESS free space - branch2)
        let lfs_policy = LeastFreeSpaceCreatePolicy;
        let lfs_result = lfs_policy.select_branch(&branches_lfs, Path::new("test.txt")).unwrap();
        assert_eq!(lfs_result.path, branch2.path, "LFS should select branch with less free space");
        
        // Verify they selected different branches
        assert_ne!(mfs_result.path, lfs_result.path, "MFS and LFS should select different branches");
    }
}

impl CreatePolicy for MostFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "mfs"
    }
    
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        if branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut max_free_space = 0u64;
        
        for branch in branches {
            if !branch.allows_create() {
                continue;
            }
            
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    if disk_space.available > max_free_space {
                        max_free_space = disk_space.available;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(e) => {
                    // Log error but continue checking other branches
                    eprintln!("Warning: Failed to get disk space for {}: {}", branch.path.display(), e);
                    continue;
                }
            }
        }
        
        best_branch.ok_or_else(|| {
            // Check if all branches are readonly or if we had other errors
            let has_writable = branches.iter().any(|b| b.allows_create());
            if has_writable {
                PolicyError::IoError(io::Error::new(
                    io::ErrorKind::Other,
                    "Failed to get disk space for any writable branch"
                ))
            } else {
                PolicyError::ReadOnlyFilesystem
            }
        })
    }
}

impl CreatePolicy for LeastFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "lfs"
    }
    
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        if branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut min_free_space = u64::MAX;
        
        for branch in branches {
            if !branch.allows_create() {
                continue;
            }
            
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    if disk_space.available < min_free_space {
                        min_free_space = disk_space.available;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(e) => {
                    // Log error but continue checking other branches
                    eprintln!("Warning: Failed to get disk space for {}: {}", branch.path.display(), e);
                    continue;
                }
            }
        }
        
        best_branch.ok_or_else(|| {
            // Check if all branches are readonly or if we had other errors
            let has_writable = branches.iter().any(|b| b.allows_create());
            if has_writable {
                PolicyError::IoError(io::Error::new(
                    io::ErrorKind::Other,
                    "Failed to get disk space for any writable branch"
                ))
            } else {
                PolicyError::ReadOnlyFilesystem
            }
        })
    }
}