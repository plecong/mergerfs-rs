use crate::branch::{Branch, BranchMode};
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use crate::policy::utils::DiskSpace;
use std::path::Path;
use std::sync::Arc;
use tracing::{debug, instrument};

/// Existing Path First Found (epff) create policy
/// Selects the first branch where the parent directory exists
/// and has sufficient free space
pub struct ExistingPathFirstFoundCreatePolicy;

impl ExistingPathFirstFoundCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for ExistingPathFirstFoundCreatePolicy {
    fn name(&self) -> &'static str {
        "epff"
    }

    #[instrument(skip(self, branches), fields(policy = "epff"))]
    fn select_branch<'a>(
        &self,
        branches: &'a [Arc<Branch>],
        path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        debug!("Selecting branch for path: {:?}", path);

        // For path-preserving policies, we need to check if the parent exists
        let parent_path = path.parent().unwrap_or(Path::new("/"));
        debug!("Checking for parent path: {:?}", parent_path);

        for branch in branches {
            // Skip read-only or no-create branches
            if matches!(branch.mode, BranchMode::ReadOnly | BranchMode::NoCreate) {
                debug!("Skipping branch {:?} - read-only or no-create", branch.path);
                continue;
            }

            // Check if parent directory exists on this branch
            let full_parent_path = branch.path.join(parent_path.strip_prefix("/").unwrap_or(parent_path));
            if !full_parent_path.exists() {
                debug!("Parent path {:?} does not exist on branch {:?}", parent_path, branch.path);
                continue;
            }

            // Check filesystem info
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    // TODO: Check minimum free space when configuration support is added
                    // For now, just check if we have any space available
                    if disk_space.available == 0 {
                        debug!(
                            "Branch {:?} has no available space",
                            branch.path
                        );
                        continue;
                    }
                    
                    // Found first valid branch with existing parent path
                    debug!("Selected branch: {:?} with parent path existing", branch.path);
                    return Ok(Arc::clone(branch));
                }
                Err(e) => {
                    debug!("Failed to get disk space for branch {:?}: {}", branch.path, e);
                    continue;
                }
            }
        }

        Err(PolicyError::NoBranchesAvailable)
    }

    fn is_path_preserving(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use std::fs;

    #[test]
    fn test_epff_selects_first_with_parent() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();
        let temp_dir3 = TempDir::new().unwrap();

        // Create parent directory only in second and third branches
        fs::create_dir_all(temp_dir2.path().join("parent")).unwrap();
        fs::create_dir_all(temp_dir3.path().join("parent")).unwrap();

        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir3.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathFirstFoundCreatePolicy;
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));

        assert!(result.is_ok());
        let selected = result.unwrap();
        // Should select the second branch (first one with parent)
        assert_eq!(selected.path, temp_dir2.path());
    }

    #[test]
    fn test_epff_skips_readonly() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        // Create parent directory in both
        fs::create_dir_all(temp_dir1.path().join("parent")).unwrap();
        fs::create_dir_all(temp_dir2.path().join("parent")).unwrap();

        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadOnly)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathFirstFoundCreatePolicy;
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));

        assert!(result.is_ok());
        let selected = result.unwrap();
        // Should skip readonly and select second branch
        assert_eq!(selected.path, temp_dir2.path());
    }

    #[test]
    fn test_epff_no_parent_exists() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        // Don't create parent directory in any branch

        let branches = vec![
            Arc::new(Branch::new(temp_dir1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp_dir2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];

        let policy = ExistingPathFirstFoundCreatePolicy;
        let result = policy.select_branch(&branches, Path::new("/parent/file.txt"));

        assert!(result.is_err());
    }

    #[test]
    fn test_is_path_preserving() {
        let policy = ExistingPathFirstFoundCreatePolicy;
        assert!(policy.is_path_preserving());
    }

    #[test]
    fn test_name() {
        let policy = ExistingPathFirstFoundCreatePolicy;
        assert_eq!(policy.name(), "epff");
    }
}