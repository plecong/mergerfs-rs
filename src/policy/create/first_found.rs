use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use std::path::Path;
use std::sync::Arc;

pub struct FirstFoundCreatePolicy;

impl FirstFoundCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for FirstFoundCreatePolicy {
    fn name(&self) -> &'static str {
        "ff"
    }

    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        for branch in branches {
            if branch.allows_create() {
                return Ok(branch.clone());
            }
        }
        
        if branches.is_empty() {
            Err(PolicyError::NoBranchesAvailable)
        } else {
            Err(PolicyError::ReadOnlyFilesystem)
        }
    }
}