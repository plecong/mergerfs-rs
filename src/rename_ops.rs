use std::path::Path;
use std::sync::Arc;
use std::fs;
use std::io;
use thiserror::Error;
use tracing;

use crate::branch::{Branch, BranchMode};
use crate::policy::{ActionPolicy, SearchPolicy, CreatePolicy, PolicyError};
use crate::config::ConfigRef;
use crate::fs_utils;

#[derive(Debug, Error)]
#[allow(dead_code)]
pub enum RenameError {
    #[error("Source file not found")]
    NotFound,
    
    #[error("Permission denied")]
    PermissionDenied,
    
    #[error("Read-only filesystem")]
    ReadOnly,
    
    #[error("No space left on device")]
    NoSpace,
    
    #[error("Cross-device rename not supported")]
    CrossDevice,
    
    #[error("Destination already exists")]
    DestinationExists,
    
    #[error("Invalid path")]
    InvalidPath,
    
    #[error("IO error: {0}")]
    Io(#[from] io::Error),
    
    #[error("Policy error: {0}")]
    Policy(#[from] PolicyError),
}

impl RenameError {
    pub fn to_errno(&self) -> i32 {
        match self {
            RenameError::NotFound => 2,           // ENOENT
            RenameError::PermissionDenied => 13,  // EACCES
            RenameError::ReadOnly => 30,          // EROFS
            RenameError::NoSpace => 28,           // ENOSPC
            RenameError::CrossDevice => 18,       // EXDEV
            RenameError::DestinationExists => 17, // EEXIST
            RenameError::InvalidPath => 22,       // EINVAL
            RenameError::Io(e) => e.raw_os_error().unwrap_or(5), // EIO
            RenameError::Policy(_) => 5,          // EIO
        }
    }
    
    fn priority(&self) -> u32 {
        match self {
            RenameError::NotFound => 1,
            RenameError::PermissionDenied => 2,
            RenameError::ReadOnly => 3,
            RenameError::NoSpace => 4,
            RenameError::CrossDevice => 5,
            RenameError::DestinationExists => 6,
            RenameError::InvalidPath => 7,
            RenameError::Io(_) => 8,
            RenameError::Policy(_) => 9,
        }
    }
}

fn io_error_to_rename_error(e: io::Error) -> RenameError {
    match e.kind() {
        io::ErrorKind::NotFound => RenameError::NotFound,
        io::ErrorKind::PermissionDenied => RenameError::PermissionDenied,
        io::ErrorKind::AlreadyExists => RenameError::DestinationExists,
        _ => {
            // Check for EXDEV (cross-device)
            if let Some(errno) = e.raw_os_error() {
                if errno == 18 { // EXDEV
                    return RenameError::CrossDevice;
                }
            }
            RenameError::Io(e)
        }
    }
}

pub struct RenameManager {
    branches: Vec<Arc<Branch>>,
    action_policy: Box<dyn ActionPolicy>,
    search_policy: Box<dyn SearchPolicy>,
    create_policy: Box<dyn CreatePolicy>,
    config: ConfigRef,
}

impl RenameManager {
    pub fn new(
        branches: Vec<Arc<Branch>>,
        action_policy: Box<dyn ActionPolicy>,
        search_policy: Box<dyn SearchPolicy>,
        create_policy: Box<dyn CreatePolicy>,
        config: ConfigRef,
    ) -> Self {
        Self {
            branches,
            action_policy,
            search_policy,
            create_policy,
            config,
        }
    }
    
    pub fn rename(&self, old_path: &Path, new_path: &Path) -> Result<(), RenameError> {
        let _span = tracing::info_span!("rename::rename", old = ?old_path, new = ?new_path).entered();
        tracing::debug!("Starting rename operation");
        
        // Determine which strategy to use
        let config = self.config.read();
        let use_path_preserving = self.create_policy.is_path_preserving() && 
                                  !config.ignore_path_preserving_on_rename;
        
        let strategy = if use_path_preserving { "path-preserving" } else { "create-path" };
        tracing::info!("Using {} rename strategy", strategy);
        
        let result = if use_path_preserving {
            self.rename_preserve_path(old_path, new_path)
        } else {
            self.rename_create_path(old_path, new_path)
        };
        
        match &result {
            Ok(_) => tracing::info!("Rename completed successfully"),
            Err(e) => tracing::error!("Rename failed: {:?}", e),
        }
        result
    }
    
    fn rename_preserve_path(&self, old_path: &Path, new_path: &Path) -> Result<(), RenameError> {
        let _span = tracing::debug_span!("rename::preserve_path", old = ?old_path, new = ?new_path).entered();
        tracing::debug!("Starting path-preserving rename");
        
        // 1. Find branches where source file exists using action policy
        let source_branches = self.action_policy.select_branches(&self.branches, old_path)?;
        if source_branches.is_empty() {
            return Err(RenameError::NotFound);
        }
        
        let mut success = false;
        let mut to_remove = Vec::new();
        let mut last_error = None;
        
        // 2. For each branch in the pool
        for branch in &self.branches {
            let new_full_path = branch.full_path(new_path);
            
            // 3. If source doesn't exist on this branch, mark destination for removal
            if !source_branches.iter().any(|b| Arc::ptr_eq(b, branch)) {
                to_remove.push(new_full_path);
                continue;
            }
            
            // Skip read-only branches
            if branch.mode == BranchMode::ReadOnly {
                continue;
            }
            
            // 4. Attempt rename on this branch
            let old_full_path = branch.full_path(old_path);
            tracing::debug!("Attempting rename on branch {:?}: {:?} -> {:?}", branch.path, old_full_path, new_full_path);
            match fs::rename(&old_full_path, &new_full_path) {
                Ok(()) => {
                    tracing::debug!("Rename successful on branch {:?}", branch.path);
                    success = true;
                }
                Err(e) => {
                    tracing::warn!("Rename failed on branch {:?}: {:?}", branch.path, e);
                    last_error = Some(io_error_to_rename_error(e));
                    to_remove.push(old_full_path);
                }
            }
        }
        
        // 5. If no renames succeeded, return EXDEV
        if !success {
            return Err(last_error.unwrap_or(RenameError::CrossDevice));
        }
        
        // 6. Clean up marked files
        for path in to_remove {
            let _ = fs::remove_file(path);
        }
        
        Ok(())
    }
    
    fn rename_create_path(&self, old_path: &Path, new_path: &Path) -> Result<(), RenameError> {
        let _span = tracing::debug_span!("rename::create_path", old = ?old_path, new = ?new_path).entered();
        tracing::debug!("Starting create-path rename");
        
        // 1. Find branches where source file exists using action policy
        let source_branches = self.action_policy.select_branches(&self.branches, old_path)?;
        if source_branches.is_empty() {
            return Err(RenameError::NotFound);
        }
        
        // 2. Get target branches for new path's parent using search policy
        // Note: It's OK if parent doesn't exist yet - we'll create it
        let parent_path = new_path.parent().ok_or(RenameError::InvalidPath)?;
        let target_branches = self.search_policy.search_branches(&self.branches, parent_path)
            .unwrap_or_else(|_| Vec::new());
        
        let mut any_success = false;
        let mut to_remove = Vec::new();
        let mut last_error = None;
        
        // 3. For each branch in the pool
        for branch in &self.branches {
            let new_full_path = branch.full_path(new_path);
            
            // 4. If source doesn't exist on this branch, mark destination for removal
            if !source_branches.iter().any(|b| Arc::ptr_eq(b, branch)) {
                to_remove.push(new_full_path);
                continue;
            }
            
            // Skip read-only branches
            if branch.mode == BranchMode::ReadOnly {
                continue;
            }
            
            let old_full_path = branch.full_path(old_path);
            
            // 5. Attempt rename
            let mut rename_result = fs::rename(&old_full_path, &new_full_path);
            
            // 6. If rename fails with ENOENT, try creating parent directory
            if let Err(ref e) = rename_result {
                if e.kind() == io::ErrorKind::NotFound {
                    // Try to create parent directory
                    let created = if !target_branches.is_empty() {
                        // Clone path structure from first target branch
                        fs_utils::ensure_parent_cloned(
                            &target_branches[0].path,
                            &branch.path,
                            new_path
                        ).is_ok()
                    } else {
                        // No existing parent on target branches, try to find it on source branches
                        let mut cloned = false;
                        if let Some(parent) = new_path.parent() {
                            // Look for the parent directory on any branch
                            for src_branch in &self.branches {
                                if src_branch.full_path(parent).exists() {
                                    // Clone from this branch
                                    if fs_utils::ensure_parent_cloned(
                                        &src_branch.path,
                                        &branch.path,
                                        new_path
                                    ).is_ok() {
                                        cloned = true;
                                        break;
                                    }
                                }
                            }
                            
                            // If still not cloned, create directory without cloning
                            if !cloned {
                                let parent_full = branch.full_path(parent);
                                fs::create_dir_all(&parent_full).is_ok()
                            } else {
                                true
                            }
                        } else {
                            false
                        }
                    };
                    
                    if created {
                        // Retry rename
                        rename_result = fs::rename(&old_full_path, &new_full_path);
                    }
                }
            }
            
            // 7. Track results
            match rename_result {
                Ok(()) => {
                    any_success = true;
                }
                Err(e) => {
                    last_error = Some(io_error_to_rename_error(e));
                    to_remove.push(old_full_path);
                }
            }
        }
        
        // 8. Return appropriate error if no success
        if !any_success {
            return Err(last_error.unwrap_or(RenameError::Io(
                io::Error::new(io::ErrorKind::Other, "No rename succeeded")
            )));
        }
        
        // 9. Clean up if any rename succeeded
        for path in to_remove {
            let _ = fs::remove_file(path);
        }
        
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::{AllActionPolicy, FirstFoundSearchPolicy, FirstFoundCreatePolicy};
    use crate::config::create_config;
    use tempfile::TempDir;
    
    fn setup_test_branches() -> (Vec<Arc<Branch>>, Vec<TempDir>) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        
        (vec![branch1, branch2], vec![temp1, temp2])
    }
    
    #[test]
    fn test_simple_rename_same_directory() {
        let (branches, _temps) = setup_test_branches();
        
        // Create test file
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branches[0].path.join(old_path), "test content").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        
        // Verify content preserved
        let content = fs::read_to_string(branches[0].path.join(new_path)).unwrap();
        assert_eq!(content, "test content");
    }
    
    #[test]
    fn test_rename_across_directories() {
        let (branches, _temps) = setup_test_branches();
        
        // Create directory structure
        fs::create_dir_all(branches[0].path.join("dir1")).unwrap();
        fs::create_dir_all(branches[0].path.join("dir2")).unwrap();
        
        // Create test file
        let old_path = Path::new("dir1/test.txt");
        let new_path = Path::new("dir2/renamed.txt");
        fs::write(branches[0].path.join(old_path), "test content").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_nonexistent_file() {
        let (branches, _temps) = setup_test_branches();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        let result = rename_mgr.rename(Path::new("nonexistent.txt"), Path::new("new.txt"));
        match result {
            Err(RenameError::Policy(_)) => {
                // This is expected when action policy finds no branches with the file
            },
            Err(RenameError::NotFound) => {
                // This is also acceptable
            },
            _ => panic!("Expected Policy or NotFound error, got: {:?}", result),
        }
    }
    
    #[test]
    fn test_rename_with_readonly_branch() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        
        // Create file on both branches
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branch1.path.join(old_path), "content1").unwrap();
        fs::write(branch2.path.join(old_path), "content2").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            vec![branch1.clone(), branch2.clone()],
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename only happened on writable branch
        assert!(!branch1.path.join(old_path).exists());
        assert!(branch1.path.join(new_path).exists());
        
        // Read-only branch should still have old file
        assert!(branch2.path.join(old_path).exists());
        assert!(!branch2.path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_multi_branch_file() {
        let (branches, _temps) = setup_test_branches();
        
        // Create file on both branches
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branches[0].path.join(old_path), "content1").unwrap();
        fs::write(branches[1].path.join(old_path), "content2").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename happened on both branches
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        assert!(!branches[1].path.join(old_path).exists());
        assert!(branches[1].path.join(new_path).exists());
        
        // Verify content preserved
        let content1 = fs::read_to_string(branches[0].path.join(new_path)).unwrap();
        let content2 = fs::read_to_string(branches[1].path.join(new_path)).unwrap();
        assert_eq!(content1, "content1");
        assert_eq!(content2, "content2");
    }
}