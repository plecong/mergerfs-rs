use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use crate::policy::utils::DiskSpace;
use std::io;
use std::path::Path;
use std::sync::Arc;

pub struct LeastFreeSpaceCreatePolicy;

impl LeastFreeSpaceCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for LeastFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "lfs"
    }
    
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        if branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut min_free_space = u64::MAX;
        
        for branch in branches {
            if !branch.allows_create() {
                continue;
            }
            
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    if disk_space.available < min_free_space {
                        min_free_space = disk_space.available;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(e) => {
                    // Log error but continue checking other branches
                    eprintln!("Warning: Failed to get disk space for {}: {}", branch.path.display(), e);
                    continue;
                }
            }
        }
        
        best_branch.ok_or_else(|| {
            // Check if all branches are readonly or if we had other errors
            let has_writable = branches.iter().any(|b| b.allows_create());
            if has_writable {
                PolicyError::IoError(io::Error::new(
                    io::ErrorKind::Other,
                    "Failed to get disk space for any writable branch"
                ))
            } else {
                PolicyError::ReadOnlyFilesystem
            }
        })
    }
}