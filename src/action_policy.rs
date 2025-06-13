use crate::branch::{Branch, PolicyError};
use std::path::Path;
use std::sync::Arc;

/// Action policies determine which branch instances to operate on for metadata changes
pub trait ActionPolicy: Send + Sync {
    fn name(&self) -> &'static str;
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
}

/// All policy - operate on all instances across all writable branches
pub struct AllActionPolicy;

impl ActionPolicy for AllActionPolicy {
    fn name(&self) -> &'static str {
        "all"
    }

    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut target_branches = Vec::new();
        
        for branch in branches {
            if !branch.allows_create() {
                continue; // Skip readonly branches
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() {
                target_branches.push(branch.clone());
            }
        }
        
        if target_branches.is_empty() {
            Err(PolicyError::NoBranchesAvailable)
        } else {
            Ok(target_branches)
        }
    }
}

/// ExistingPath All policy - operate on all instances but only on existing paths
pub struct ExistingPathAllActionPolicy;

impl ActionPolicy for ExistingPathAllActionPolicy {
    fn name(&self) -> &'static str {
        "epall"
    }

    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut target_branches = Vec::new();
        let mut found_existing = false;
        
        // First check if the path exists anywhere
        for branch in branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                found_existing = true;
                break;
            }
        }
        
        if !found_existing {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        // Now collect all writable branches where the path exists
        for branch in branches {
            if !branch.allows_create() {
                continue; // Skip readonly branches
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() {
                target_branches.push(branch.clone());
            }
        }
        
        if target_branches.is_empty() {
            Err(PolicyError::ReadOnlyFilesystem)
        } else {
            Ok(target_branches)
        }
    }
}

/// ExistingPath FirstFound policy - operate on first found instance only
pub struct ExistingPathFirstFoundActionPolicy;

impl ActionPolicy for ExistingPathFirstFoundActionPolicy {
    fn name(&self) -> &'static str {
        "epff"
    }

    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        for branch in branches {
            if !branch.allows_create() {
                continue; // Skip readonly branches
            }
            
            let full_path = branch.full_path(path);
            if full_path.exists() {
                return Ok(vec![branch.clone()]);
            }
        }
        
        Err(PolicyError::NoBranchesAvailable)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use std::path::Path;
    use tempfile::TempDir;

    fn setup_test_branches_with_files() -> (Vec<TempDir>, Vec<Arc<Branch>>) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        // Create test files in branches 1 and 2, but not 3
        std::fs::write(temp1.path().join("test.txt"), "content1").unwrap();
        std::fs::write(temp2.path().join("test.txt"), "content2").unwrap();
        std::fs::write(temp1.path().join("unique1.txt"), "unique").unwrap();

        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch3 = Arc::new(Branch::new(
            temp3.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));

        let branches = vec![branch1, branch2, branch3];
        (vec![temp1, temp2, temp3], branches)
    }

    #[test]
    fn test_all_action_policy() {
        let (_temp_dirs, branches) = setup_test_branches_with_files();
        let policy = AllActionPolicy;

        // Test file that exists in multiple writable branches
        let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.len(), 2, "Should select both writable branches with the file");
        
        // Verify it selected the right branches (writable ones)
        assert!(result.iter().all(|b| b.allows_create()));

        // Test file that exists in only one branch
        let result = policy.select_branches(&branches, Path::new("unique1.txt")).unwrap();
        assert_eq!(result.len(), 1, "Should select only the branch containing the file");

        // Test non-existent file
        let result = policy.select_branches(&branches, Path::new("missing.txt"));
        assert!(result.is_err(), "Should fail for non-existent file");
    }

    #[test]
    fn test_existing_path_all_policy() {
        let (_temp_dirs, branches) = setup_test_branches_with_files();
        let policy = ExistingPathAllActionPolicy;

        // Test file that exists in multiple branches
        let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.len(), 2, "Should select both writable branches with the file");

        // Test file that exists in only one branch
        let result = policy.select_branches(&branches, Path::new("unique1.txt")).unwrap();
        assert_eq!(result.len(), 1, "Should select the branch containing the file");

        // Test non-existent file
        let result = policy.select_branches(&branches, Path::new("missing.txt"));
        assert!(result.is_err(), "Should fail for non-existent file");
    }

    #[test]
    fn test_existing_path_first_found_policy() {
        let (_temp_dirs, branches) = setup_test_branches_with_files();
        let policy = ExistingPathFirstFoundActionPolicy;

        // Test file that exists in multiple branches - should return only first
        let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.len(), 1, "Should select only first branch with the file");
        assert_eq!(result[0].path, branches[0].path, "Should select first branch");

        // Test file that exists in only one branch
        let result = policy.select_branches(&branches, Path::new("unique1.txt")).unwrap();
        assert_eq!(result.len(), 1, "Should select the branch containing the file");

        // Test non-existent file
        let result = policy.select_branches(&branches, Path::new("missing.txt"));
        assert!(result.is_err(), "Should fail for non-existent file");
    }

    #[test]
    fn test_readonly_branch_handling() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();

        // Create file in readonly branch
        std::fs::write(temp2.path().join("readonly_file.txt"), "content").unwrap();

        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));

        let branches = vec![branch1, branch2];
        let policy = AllActionPolicy;

        // Should not select readonly branch even if file exists there
        let result = policy.select_branches(&branches, Path::new("readonly_file.txt"));
        assert!(result.is_err(), "Should fail when file only exists in readonly branch");
    }

    #[test]
    fn test_policy_names() {
        let all_policy = AllActionPolicy;
        let epall_policy = ExistingPathAllActionPolicy;
        let epff_policy = ExistingPathFirstFoundActionPolicy;

        assert_eq!(all_policy.name(), "all");
        assert_eq!(epall_policy.name(), "epall");
        assert_eq!(epff_policy.name(), "epff");
    }
}