use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::ActionPolicy;
use std::path::Path;
use std::sync::Arc;

/// ExistingPath All policy - operate on all instances but only on existing paths
pub struct ExistingPathAllActionPolicy;

impl ExistingPathAllActionPolicy {
    pub fn new() -> Self {
        Self
    }
}

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