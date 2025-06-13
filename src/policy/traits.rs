use crate::branch::Branch;
use crate::policy::error::PolicyError;
use std::path::Path;
use std::sync::Arc;

/// Create policies determine which branch to use for creating new files/directories
pub trait CreatePolicy: Send + Sync {
    fn name(&self) -> &'static str;
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Arc<Branch>, PolicyError>;
}

/// Action policies determine which branch instances to operate on for metadata changes
pub trait ActionPolicy: Send + Sync {
    fn name(&self) -> &'static str;
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
}

/// Search policies determine how to search for existing files across branches
/// (Not yet implemented in the original codebase)
pub trait SearchPolicy: Send + Sync {
    fn name(&self) -> &'static str;
    fn search_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
}