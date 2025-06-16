use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use crate::policy::utils::DiskSpace;
use std::io;
use std::path::Path;
use std::sync::Arc;

pub struct LeastUsedSpaceCreatePolicy;

impl LeastUsedSpaceCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for LeastUsedSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "lus"
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
        let mut least_used_space = u64::MAX;
        let mut last_error = None;
        
        for branch in branches {
            if !branch.allows_create() {
                continue;
            }
            
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    // Select branch with least used space
                    if disk_space.used < least_used_space {
                        least_used_space = disk_space.used;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(e) => {
                    // Track errors with priority (EROFS > ENOSPC > ENOENT)
                    let error_kind = e.kind();
                    let error_msg = e.to_string();
                    let error_priority = match error_kind {
                        io::ErrorKind::PermissionDenied => 3, // Treat as EROFS
                        io::ErrorKind::Other => {
                            // Check if it's actually ENOSPC
                            if error_msg.contains("No space") {
                                2
                            } else {
                                1
                            }
                        }
                        _ => 1, // Default/ENOENT priority
                    };
                    
                    tracing::warn!(
                        "Failed to get disk space for {}: {}", 
                        branch.path.display(), 
                        error_msg
                    );
                    
                    // Update error if higher priority
                    if last_error.is_none() || error_priority > last_error.as_ref().map(|(_, p)| *p).unwrap_or(0) {
                        last_error = Some((e, error_priority));
                    }
                    
                    continue;
                }
            }
        }
        
        best_branch.ok_or_else(|| {
            // Return appropriate error based on priority
            if let Some((error, _)) = last_error {
                if error.kind() == io::ErrorKind::PermissionDenied {
                    PolicyError::ReadOnlyFilesystem
                } else if error.to_string().contains("No space") {
                    PolicyError::NoSpace
                } else {
                    PolicyError::IoError(error)
                }
            } else {
                // Check if all branches are readonly
                let has_writable = branches.iter().any(|b| b.allows_create());
                if has_writable {
                    PolicyError::IoError(io::Error::new(
                        io::ErrorKind::Other,
                        "Failed to get disk space for any writable branch"
                    ))
                } else {
                    PolicyError::ReadOnlyFilesystem
                }
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::test_utils::SpacePolicyTestSetup;
    use std::fs;
    use tempfile::tempdir;
    
    #[test]
    fn test_least_used_space_empty_branches() {
        let policy = LeastUsedSpaceCreatePolicy::new();
        let branches = vec![];
        let result = policy.select_branch(&branches, Path::new("/test"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_least_used_space_single_branch() {
        let temp_dir = tempdir().unwrap();
        let branch_path = temp_dir.path().join("branch1");
        fs::create_dir(&branch_path).unwrap();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let policy = LeastUsedSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test")).unwrap();
        assert_eq!(result.path, branch_path);
    }
    
    #[test]
    fn test_least_used_space_multiple_branches() {
        // Create test setup with different available spaces
        // This will create branches with different used spaces
        let setup = SpacePolicyTestSetup::new(80, 50, 20); // Available space in MB
        setup.setup_space();
        let branches = setup.get_branches();
        
        let policy = LeastUsedSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test")).unwrap();
        
        // With 100MB total per branch:
        // Branch 0: 80MB available = 20MB used (least)
        // Branch 1: 50MB available = 50MB used
        // Branch 2: 20MB available = 80MB used
        // Should select branch 0 with least used space
        assert_eq!(result.path, branches[0].path);
    }
    
    #[test]
    fn test_least_used_space_skip_readonly() {
        let temp_dir = tempdir().unwrap();
        let branch1_path = temp_dir.path().join("branch1");
        let branch2_path = temp_dir.path().join("branch2");
        
        fs::create_dir(&branch1_path).unwrap();
        fs::create_dir(&branch2_path).unwrap();
        
        // Write space markers
        fs::write(branch1_path.join(".space_marker"), "90").unwrap(); // 10MB used
        fs::write(branch2_path.join(".space_marker"), "70").unwrap(); // 30MB used
        
        let branches = vec![
            Arc::new(Branch::new(branch1_path.clone(), BranchMode::ReadOnly)),
            Arc::new(Branch::new(branch2_path.clone(), BranchMode::ReadWrite)),
        ];
        
        let policy = LeastUsedSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test")).unwrap();
        
        // Should select branch2 even though it has more used space
        assert_eq!(result.path, branch2_path);
    }
    
    #[test]
    fn test_least_used_space_all_readonly() {
        let temp_dir = tempdir().unwrap();
        let branch1_path = temp_dir.path().join("branch1");
        let branch2_path = temp_dir.path().join("branch2");
        
        fs::create_dir(&branch1_path).unwrap();
        fs::create_dir(&branch2_path).unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(branch1_path, BranchMode::ReadOnly)),
            Arc::new(Branch::new(branch2_path, BranchMode::NoCreate)),
        ];
        
        let policy = LeastUsedSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test"));
        
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }
    
    #[test]
    fn test_least_used_space_equal_space() {
        let temp_dir = tempdir().unwrap();
        let branch1_path = temp_dir.path().join("branch1");
        let branch2_path = temp_dir.path().join("branch2");
        
        fs::create_dir(&branch1_path).unwrap();
        fs::create_dir(&branch2_path).unwrap();
        
        // Both branches have same available space (and thus same used space)
        fs::write(branch1_path.join(".space_marker"), "60").unwrap(); // 40MB used
        fs::write(branch2_path.join(".space_marker"), "60").unwrap(); // 40MB used
        
        let branches = vec![
            Arc::new(Branch::new(branch1_path.clone(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(branch2_path.clone(), BranchMode::ReadWrite)),
        ];
        
        let policy = LeastUsedSpaceCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test")).unwrap();
        
        // Should select first branch when equal
        assert_eq!(result.path, branch1_path);
    }
}