use crate::branch::Branch;
use crate::policy::{SearchPolicy, PolicyError};
use std::path::Path;
use std::sync::Arc;

pub struct FirstFoundSearchPolicy;

impl FirstFoundSearchPolicy {
    pub fn new() -> Self {
        Self
    }
}

impl SearchPolicy for FirstFoundSearchPolicy {
    fn name(&self) -> &'static str {
        "ff"
    }
    
    fn search_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        // Return the first branch where the file exists
        for branch in branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                return Ok(vec![branch.clone()]);
            }
        }
        
        Err(PolicyError::NoBranchesAvailable)
    }
}

// Add convenient method names
impl FirstFoundSearchPolicy {
    pub fn search(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        self.search_branches(branches, path)
    }
}