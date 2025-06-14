use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::ActionPolicy;
use std::path::Path;
use std::sync::Arc;

/// All policy - operate on all instances across all writable branches
pub struct AllActionPolicy;

impl AllActionPolicy {
    pub fn new() -> Self {
        Self
    }
    
    // Add execute method for compatibility with xattr operations
    pub fn execute(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        self.select_branches(branches, path)
    }
}

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
            if branch.is_readonly() {
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