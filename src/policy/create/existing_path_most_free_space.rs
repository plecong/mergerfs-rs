use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use crate::policy::utils::DiskSpace;
use std::path::Path;
use std::sync::Arc;

pub struct ExistingPathMostFreeSpaceCreatePolicy;

impl ExistingPathMostFreeSpaceCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for ExistingPathMostFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "epmfs"
    }
    
    fn is_path_preserving(&self) -> bool {
        true
    }
    
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        if branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut max_free_space = 0u64;
        let mut last_error = PolicyError::PathNotFound;
        let mut has_writable = false;
        
        for branch in branches {
            // Skip non-writable branches
            if !branch.allows_create() {
                has_writable = has_writable || false;
                Self::update_error(&mut last_error, PolicyError::ReadOnlyFilesystem);
                continue;
            }
            
            has_writable = true;
            
            // Check if parent path exists on this branch
            let full_path = branch.path.join(path.strip_prefix("/").unwrap_or(path));
            let parent = match full_path.parent() {
                Some(p) => p,
                None => {
                    Self::update_error(&mut last_error, PolicyError::PathNotFound);
                    continue;
                }
            };
            
            if !parent.exists() {
                Self::update_error(&mut last_error, PolicyError::PathNotFound);
                continue;
            }
            
            // Get filesystem info
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    // TODO: Check minimum free space when configuration support is added
                    // For now, we don't have a minimum free space requirement
                    
                    // Track branch with most free space among those with existing path
                    if disk_space.available > max_free_space {
                        max_free_space = disk_space.available;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(e) => {
                    eprintln!("Warning: Failed to get disk space for {}: {}", branch.path.display(), e);
                    Self::update_error(&mut last_error, PolicyError::IoError(e));
                    continue;
                }
            }
        }
        
        if let Some(ref branch) = best_branch {
            tracing::info!("EPMFS policy selected branch {:?} with {} bytes free", branch.path, max_free_space);
        }
        
        best_branch.ok_or_else(|| {
            // Return appropriate error based on what we found
            if !has_writable {
                PolicyError::ReadOnlyFilesystem
            } else {
                last_error
            }
        })
    }
}

impl ExistingPathMostFreeSpaceCreatePolicy {
    /// Update error based on priority (similar to C++ error_and_continue)
    /// Priority: PathNotFound < NoSpace < ReadOnlyFilesystem < IoError
    fn update_error(current: &mut PolicyError, new: PolicyError) {
        use PolicyError::*;
        
        match (current.clone(), new) {
            // PathNotFound has lowest priority, always update
            (PathNotFound, new_err) => *current = new_err,
            
            // NoSpace overrides PathNotFound
            (NoSpace, PathNotFound) => {}, // Keep current
            (NoSpace, new_err) => *current = new_err,
            
            // ReadOnlyFilesystem overrides PathNotFound and NoSpace
            (ReadOnlyFilesystem, PathNotFound) | (ReadOnlyFilesystem, NoSpace) => {}, // Keep current
            (ReadOnlyFilesystem, new_err) => *current = new_err,
            
            // For other errors, keep the first one
            _ => {},
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use std::fs;
    use tempfile::TempDir;
    
    #[test]
    fn test_error_priority() {
        use PolicyError::*;
        
        // Test that PathNotFound is replaced by anything
        let mut err = PathNotFound;
        ExistingPathMostFreeSpaceCreatePolicy::update_error(&mut err, NoSpace);
        assert!(matches!(err, NoSpace));
        
        // Test that NoSpace is not replaced by PathNotFound
        let mut err = NoSpace;
        ExistingPathMostFreeSpaceCreatePolicy::update_error(&mut err, PathNotFound);
        assert!(matches!(err, NoSpace));
        
        // Test that ReadOnlyFilesystem is not replaced by lower priority errors
        let mut err = ReadOnlyFilesystem;
        ExistingPathMostFreeSpaceCreatePolicy::update_error(&mut err, PathNotFound);
        assert!(matches!(err, ReadOnlyFilesystem));
        
        let mut err = ReadOnlyFilesystem;
        ExistingPathMostFreeSpaceCreatePolicy::update_error(&mut err, NoSpace);
        assert!(matches!(err, ReadOnlyFilesystem));
    }
    
    #[test]
    fn test_select_branch_no_branches() {
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![];
        let result = policy.select_branch(&branches, Path::new("/test.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_select_branch_all_readonly() {
        let temp_dir = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(
            temp_dir.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![branch];
        let result = policy.select_branch(&branches, Path::new("/test.txt"));
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }
    
    #[test]
    fn test_select_branch_path_not_exists() {
        let temp_dir = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(
            temp_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![branch];
        // Path /nonexistent/test.txt - parent doesn't exist
        let result = policy.select_branch(&branches, Path::new("/nonexistent/test.txt"));
        assert!(matches!(result, Err(PolicyError::PathNotFound)));
    }
    
    #[test]
    fn test_select_branch_with_existing_path() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory in both branches
        fs::create_dir(temp_dir1.path().join("mydir")).unwrap();
        fs::create_dir(temp_dir2.path().join("mydir")).unwrap();
        
        let branch1 = Arc::new(Branch::new(
            temp_dir1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp_dir2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![branch1.clone(), branch2.clone()];
        
        // Should select a branch (the one with more free space)
        let result = policy.select_branch(&branches, Path::new("/mydir/test.txt"));
        assert!(result.is_ok());
        let selected = result.unwrap();
        assert!(selected == branch1 || selected == branch2);
    }
    
    #[test]
    fn test_is_path_preserving() {
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        assert!(policy.is_path_preserving());
    }
    
    #[test]
    fn test_name() {
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        assert_eq!(policy.name(), "epmfs");
    }
    
    #[test]
    fn test_epmfs_selects_branch_with_existing_path_and_most_space() {
        // Create three branches
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        let temp_dir3 = TempDir::new().unwrap();
        
        // Create directory structure in branch 1 and 2 only
        fs::create_dir_all(temp_dir1.path().join("existing/dir")).unwrap();
        fs::create_dir_all(temp_dir2.path().join("existing/dir")).unwrap();
        // Branch 3 doesn't have the path
        
        let branch1 = Arc::new(Branch::new(
            temp_dir1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp_dir2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch3 = Arc::new(Branch::new(
            temp_dir3.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        
        // Test 1: All branches have similar space - should select from branch1 or branch2
        let branches = vec![branch1.clone(), branch2.clone(), branch3.clone()];
        let result = policy.select_branch(&branches, Path::new("/existing/dir/file.txt"));
        assert!(result.is_ok());
        let selected = result.unwrap();
        // Should NOT select branch3 since it doesn't have the parent path
        assert_ne!(selected, branch3);
        
        // Test 2: With a readonly branch that has the path
        let branch2_ro = Arc::new(Branch::new(
            temp_dir2.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        let branches = vec![branch1.clone(), branch2_ro, branch3.clone()];
        let result = policy.select_branch(&branches, Path::new("/existing/dir/file.txt"));
        assert!(result.is_ok());
        let selected = result.unwrap();
        // Should select branch1 as it's the only writable branch with the path
        assert_eq!(selected, branch1);
    }
    
    #[test]
    fn test_epmfs_fallback_when_no_existing_path() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Don't create any directories - simulate new path creation
        
        let branch1 = Arc::new(Branch::new(
            temp_dir1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp_dir2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![branch1, branch2];
        
        // Should return PathNotFound when parent doesn't exist anywhere
        let result = policy.select_branch(&branches, Path::new("/nonexistent/dir/file.txt"));
        assert!(matches!(result, Err(PolicyError::PathNotFound)));
    }
    
    #[test]
    fn test_epmfs_mixed_branches_with_path() {
        // Create branches with different scenarios
        let temp_dir_rw_with_path = TempDir::new().unwrap();
        let temp_dir_ro_with_path = TempDir::new().unwrap();
        let temp_dir_rw_no_path = TempDir::new().unwrap();
        
        // Create paths
        fs::create_dir_all(temp_dir_rw_with_path.path().join("data")).unwrap();
        fs::create_dir_all(temp_dir_ro_with_path.path().join("data")).unwrap();
        
        let branch_rw_path = Arc::new(Branch::new(
            temp_dir_rw_with_path.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch_ro_path = Arc::new(Branch::new(
            temp_dir_ro_with_path.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        let branch_rw_no_path = Arc::new(Branch::new(
            temp_dir_rw_no_path.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        let policy = ExistingPathMostFreeSpaceCreatePolicy::new();
        let branches = vec![branch_rw_path.clone(), branch_ro_path, branch_rw_no_path];
        
        let result = policy.select_branch(&branches, Path::new("/data/file.txt"));
        assert!(result.is_ok());
        // Should select the RW branch with the path
        assert_eq!(result.unwrap(), branch_rw_path);
    }
}