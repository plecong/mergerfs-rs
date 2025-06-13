use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use rand::seq::SliceRandom;
use rand::thread_rng;
use std::path::Path;
use std::sync::Arc;

pub struct RandomCreatePolicy;

impl RandomCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for RandomCreatePolicy {
    fn name(&self) -> &'static str {
        "rand"
    }

    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        // Collect all writable branches
        let mut writable_branches = Vec::new();
        let mut has_readonly_fs = false;
        
        for branch in branches {
            // Check branch mode
            if !branch.allows_create() {
                has_readonly_fs = true;
                continue;
            }
            
            // Check if we can actually write to the branch
            // Try to check if the directory is writable
            match std::fs::metadata(&branch.path) {
                Ok(metadata) => {
                    // Check if directory is writable
                    if metadata.permissions().readonly() {
                        has_readonly_fs = true;
                        continue;
                    }
                    // On Unix, we need to check write permissions more carefully
                    // The readonly() method only checks the user write bit
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::PermissionsExt;
                        let mode = metadata.permissions().mode();
                        // Check if owner can write (assuming we're the owner)
                        if (mode & 0o200) == 0 {
                            has_readonly_fs = true;
                            continue;
                        }
                    }
                }
                Err(_) => {
                    // Can't access branch
                    continue;
                }
            }
            
            writable_branches.push(branch.clone());
        }

        if writable_branches.is_empty() {
            if has_readonly_fs {
                return Err(PolicyError::ReadOnlyFilesystem);
            } else {
                return Err(PolicyError::NoBranchesAvailable);
            }
        }

        // Randomly select one branch
        let mut rng = thread_rng();
        writable_branches
            .choose(&mut rng)
            .cloned()
            .ok_or(PolicyError::NoBranchesAvailable)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use std::collections::HashSet;
    use tempfile::TempDir;

    #[test]
    fn test_random_selects_from_writable() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        let branch3 = Arc::new(Branch::new(temp3.path().to_path_buf(), BranchMode::ReadOnly));

        let branches = vec![branch1.clone(), branch2.clone(), branch3];
        let policy = RandomCreatePolicy::new();

        // Run multiple times to verify randomness
        let mut selected_paths = HashSet::new();
        for _ in 0..20 {
            let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
            selected_paths.insert(result.path.clone());
        }

        // Should have selected both writable branches at least once
        assert_eq!(selected_paths.len(), 2, "Should randomly select from both writable branches");
        assert!(selected_paths.contains(&branch1.path));
        assert!(selected_paths.contains(&branch2.path));
    }

    #[test]
    fn test_random_single_writable() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));

        let branches = vec![branch1, branch2.clone()];
        let policy = RandomCreatePolicy::new();

        // Should always select the only writable branch
        for _ in 0..10 {
            let result = policy.select_branch(&branches, Path::new("test.txt")).unwrap();
            assert_eq!(result.path, branch2.path);
        }
    }

    #[test]
    fn test_random_all_readonly() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly));

        let branches = vec![branch1, branch2];
        let policy = RandomCreatePolicy::new();

        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::ReadOnlyFilesystem)));
    }

    #[test]
    fn test_random_no_branches() {
        let branches = vec![];
        let policy = RandomCreatePolicy::new();

        let result = policy.select_branch(&branches, Path::new("test.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
}