use crate::branch::Branch;
use crate::policy::{CreatePolicy, PolicyError};
use rand::distributions::WeightedIndex;
use rand::prelude::*;
use std::path::Path;
use std::sync::Arc;

/// Proportional Fill Random Distribution (PFRD) create policy
/// Selects branches randomly weighted by their available space
pub struct ProportionalFillRandomDistributionCreatePolicy;

impl ProportionalFillRandomDistributionCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for ProportionalFillRandomDistributionCreatePolicy {
    fn name(&self) -> &'static str {
        "pfrd"
    }

    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        let _span = tracing::debug_span!("pfrd_policy::select_branch").entered();
        
        // Filter branches that can be used for creation
        let available_branches: Vec<(usize, u64)> = branches
            .iter()
            .enumerate()
            .filter_map(|(idx, branch)| {
                if branch.allows_create() {
                    branch.free_space().ok().map(|space| (idx, space))
                } else {
                    None
                }
            })
            .filter(|(_, space)| *space > 0) // Only consider branches with free space
            .collect();

        if available_branches.is_empty() {
            tracing::warn!("No branches available with free space");
            return Err(PolicyError::NoBranchesAvailable);
        }

        // If only one branch, return it
        if available_branches.len() == 1 {
            let idx = available_branches[0].0;
            tracing::debug!("Only one branch available, selecting branch at index {}", idx);
            return Ok(branches[idx].clone());
        }

        // Extract weights (available space) for weighted random selection
        let weights: Vec<u64> = available_branches.iter().map(|(_, space)| *space).collect();
        
        // Log available branches and their weights
        for (idx, weight) in available_branches.iter() {
            tracing::trace!("Branch {} has weight {} bytes", idx, weight);
        }

        // Create weighted distribution
        match WeightedIndex::new(&weights) {
            Ok(dist) => {
                let mut rng = thread_rng();
                let selected_idx = dist.sample(&mut rng);
                let branch_idx = available_branches[selected_idx].0;
                
                tracing::debug!(
                    "PFRD selected branch at index {} with {} bytes free space",
                    branch_idx,
                    available_branches[selected_idx].1
                );
                
                Ok(branches[branch_idx].clone())
            }
            Err(_) => {
                tracing::error!("Failed to create weighted distribution");
                Err(PolicyError::NoBranchesAvailable)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use std::path::PathBuf;
    use tempfile::TempDir;

    fn create_test_branch(path: PathBuf, mode: BranchMode) -> Arc<Branch> {
        Arc::new(Branch::new(path, mode))
    }

    #[test]
    fn test_pfrd_single_branch() {
        let dir = TempDir::new().unwrap();
        let branch = create_test_branch(dir.path().to_path_buf(), BranchMode::ReadWrite);
        let branches = vec![branch.clone()];
        
        let policy = ProportionalFillRandomDistributionCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test.txt")).unwrap();
        
        assert!(Arc::ptr_eq(&result, &branch));
    }

    #[test]
    fn test_pfrd_no_writable_branches() {
        let dir1 = TempDir::new().unwrap();
        let dir2 = TempDir::new().unwrap();
        
        let branch1 = create_test_branch(dir1.path().to_path_buf(), BranchMode::ReadOnly);
        let branch2 = create_test_branch(dir2.path().to_path_buf(), BranchMode::ReadOnly);
        let branches = vec![branch1, branch2];
        
        let policy = ProportionalFillRandomDistributionCreatePolicy::new();
        let result = policy.select_branch(&branches, Path::new("/test.txt"));
        
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }

    #[test]
    fn test_pfrd_selects_based_on_space() {
        // This test would require mocking the free_space() method
        // For now, we just verify the policy doesn't panic with multiple branches
        let dir1 = TempDir::new().unwrap();
        let dir2 = TempDir::new().unwrap();
        let dir3 = TempDir::new().unwrap();
        
        let branch1 = create_test_branch(dir1.path().to_path_buf(), BranchMode::ReadWrite);
        let branch2 = create_test_branch(dir2.path().to_path_buf(), BranchMode::ReadWrite);
        let branch3 = create_test_branch(dir3.path().to_path_buf(), BranchMode::NoCreate);
        let branches = vec![branch1, branch2, branch3];
        
        let policy = ProportionalFillRandomDistributionCreatePolicy::new();
        
        // Run multiple times to ensure randomness works
        for _ in 0..10 {
            let result = policy.select_branch(&branches, Path::new("/test.txt"));
            assert!(result.is_ok());
            let selected = result.unwrap();
            // Should not select branch3 (NoCreate)
            assert_ne!(selected.path, dir3.path());
        }
    }

    #[test]
    fn test_pfrd_policy_name() {
        let policy = ProportionalFillRandomDistributionCreatePolicy::new();
        assert_eq!(policy.name(), "pfrd");
    }
}