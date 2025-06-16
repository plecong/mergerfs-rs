use crate::branch::Branch;
use crate::policy::error::PolicyError;
use crate::policy::traits::CreatePolicy;
use crate::policy::utils::DiskSpace;
use std::io;
use std::path::Path;
use std::sync::Arc;

pub struct MostFreeSpaceCreatePolicy;

impl MostFreeSpaceCreatePolicy {
    pub fn new() -> Self {
        Self
    }
}

impl CreatePolicy for MostFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str {
        "mfs"
    }
    
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Arc<Branch>, PolicyError> {
        let _span = tracing::debug_span!("mfs::select_branch", path = ?_path).entered();
        tracing::debug!("Evaluating {} branches", branches.len());
        
        if branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut max_free_space = 0u64;
        
        for branch in branches {
            if !branch.allows_create() {
                continue;
            }
            
            match DiskSpace::for_path(&branch.path) {
                Ok(disk_space) => {
                    tracing::debug!("Branch {:?} has {} bytes available", branch.path, disk_space.available);
                    if disk_space.available > max_free_space {
                        max_free_space = disk_space.available;
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
        
        if let Some(ref branch) = best_branch {
            tracing::info!("MFS policy selected branch {:?} with {} bytes free", branch.path, max_free_space);
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