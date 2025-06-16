use crate::branch::Branch;
use crate::policy::{CreatePolicy, PolicyError};
use crate::policy::utils::DiskSpace;
use std::path::Path;
use std::sync::Arc;
use tracing::{debug, trace};

#[derive(Debug, Clone)]
pub struct ExistingPathLeastFreeSpaceCreatePolicy;

impl ExistingPathLeastFreeSpaceCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for ExistingPathLeastFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "eplfs"
    }

    fn select_branch(&self, branches: &[Arc<Branch>], path: &Path) -> Result<Arc<Branch>, PolicyError> {
        trace!("ExistingPathLeastFreeSpace policy selecting branch for path: {:?}", path);

        let mut selected_branch = None;
        let mut min_free_space = u64::MAX;
        let mut highest_priority_error = None;

        // Get the parent directory path
        let parent = if let Some(p) = path.parent() {
            trace!("Parent path extracted: {:?}", p);
            p
        } else {
            // Root directory - treat as existing everywhere
            trace!("No parent path (root), selecting first writable branch");
            return branches
                .iter()
                .find(|b| b.allows_create())
                .cloned()
                .ok_or_else(|| PolicyError::ReadOnlyFilesystem);
        };

        for branch in branches {
            // Skip non-writable branches
            if !branch.allows_create() {
                trace!("Skipping read-only branch: {:?}", branch.path);
                continue;
            }

            // Check if parent path exists on this branch
            let branch_parent = branch.path.join(parent.strip_prefix("/").unwrap_or(parent));
            trace!("Checking parent path {:?} on branch {:?}, full path: {:?}", parent, branch.path, branch_parent);
            
            match branch_parent.try_exists() {
                Ok(true) => {
                    trace!("Parent exists on branch: {:?}", branch.path);
                    
                    // Get disk space for this branch
                    match DiskSpace::for_path(&branch.path) {
                        Ok(disk_space) => {
                            let available = disk_space.available;
                            trace!("Branch {:?} has {} bytes available", branch.path, available);
                            
                            if available < min_free_space {
                                min_free_space = available;
                                selected_branch = Some(branch.clone());
                                debug!("Selected branch with least free space: {:?} ({} bytes)", 
                                    branch.path, available);
                            }
                        }
                        Err(e) => {
                            debug!("Failed to get disk space for branch {:?}: {}", branch.path, e);
                            // Track this as an I/O error
                            if highest_priority_error.is_none() {
                                highest_priority_error = Some(PolicyError::IoError(e));
                            }
                        }
                    }
                }
                Ok(false) => {
                    trace!("Parent does not exist on branch: {:?}", branch.path);
                    // Track that we couldn't find the path
                    if highest_priority_error.is_none() {
                        highest_priority_error = Some(PolicyError::PathNotFound);
                    }
                }
                Err(e) => {
                    debug!("Failed to check parent existence on branch {:?}: {}", branch.path, e);
                    // This is an I/O error, but lower priority than NotFound
                    if highest_priority_error.is_none() || 
                       matches!(highest_priority_error.as_ref(), Some(PolicyError::PathNotFound)) {
                        highest_priority_error = Some(PolicyError::IoError(e));
                    }
                }
            }
        }

        if let Some(branch) = selected_branch {
            debug!("ExistingPathLeastFreeSpace selected branch: {:?}", branch.path);
            Ok(branch)
        } else {
            // Return the most appropriate error
            Err(highest_priority_error.unwrap_or(PolicyError::PathNotFound))
        }
    }

    fn is_path_preserving(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::BranchMode;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_eplfs_selects_least_free_space_with_existing_path() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        let temp_dir3 = TempDir::new().unwrap();

        // Create parent directory in branches 1 and 2 only
        fs::create_dir_all(temp_dir1.path().join("parent")).unwrap();
        fs::create_dir_all(temp_dir2.path().join("parent")).unwrap();
        // Branch 3 does not have the parent directory

        // Create branches
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir3.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        
        // Since both temp directories likely have similar free space,
        // we'll just verify that one of the branches with the parent is selected
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));
        assert!(result.is_ok());
        
        let selected = result.unwrap();
        // Should be either branch 0 or 1, not branch 2
        assert!(selected.path == temp_dir1.path() || selected.path == temp_dir2.path());
    }

    #[test]
    fn test_eplfs_no_existing_parent() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        // Don't create parent directory in any branch

        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));
        
        assert!(result.is_err());
    }

    #[test]
    fn test_eplfs_readonly_branches() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        // Create parent directory in both branches
        fs::create_dir_all(temp_dir1.path().join("parent")).unwrap();
        fs::create_dir_all(temp_dir2.path().join("parent")).unwrap();

        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadOnly)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));
        
        assert!(result.is_ok());
        // Should select the only writable branch
        assert_eq!(result.unwrap().path, temp_dir2.path());
    }

    #[test]
    fn test_eplfs_root_path() {
        let temp_dir = TempDir::new().unwrap();
        let branches = vec![
            Arc::new(Branch::new(temp_dir.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/"));
        
        // Root path should work on any writable branch
        assert!(result.is_ok());
    }

    #[test]
    fn test_eplfs_is_path_preserving() {
        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        assert!(policy.is_path_preserving());
    }
    
    #[test]
    fn test_eplfs_debug_parent_path() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        
        // Create parent directory only in branch 2
        fs::create_dir_all(temp_dir2.path().join("testdir")).unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        let policy = ExistingPathLeastFreeSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/testdir/test.txt"));
        
        assert!(result.is_ok());
        let selected = result.unwrap();
        // Should select branch 2 where testdir exists
        assert_eq!(selected.path, temp_dir2.path(), "Should select branch where parent exists");
    }
}