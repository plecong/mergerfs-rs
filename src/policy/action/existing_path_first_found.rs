use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::ActionPolicy;
use std::path::Path;
use std::sync::Arc;

/// ExistingPath FirstFound policy - operate on first found instance only
pub struct ExistingPathFirstFoundActionPolicy;

impl ExistingPathFirstFoundActionPolicy {
    pub fn new() -> Self {
        Self
    }
}

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