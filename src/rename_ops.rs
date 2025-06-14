use std::path::Path;
use std::sync::Arc;
use std::fs;
use std::io;
use thiserror::Error;
use tracing::debug;

use crate::branch::{Branch, BranchMode};
use crate::policy::{ActionPolicy, SearchPolicy, CreatePolicy, PolicyError};

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

pub struct RenameManager {
    branches: Vec<Arc<Branch>>,
    #[allow(dead_code)]
    action_policy: Box<dyn ActionPolicy>,
    #[allow(dead_code)]
    search_policy: Box<dyn SearchPolicy>,
    #[allow(dead_code)]
    create_policy: Box<dyn CreatePolicy>,
}

impl RenameManager {
    pub fn new(
        branches: Vec<Arc<Branch>>,
        action_policy: Box<dyn ActionPolicy>,
        search_policy: Box<dyn SearchPolicy>,
        create_policy: Box<dyn CreatePolicy>,
    ) -> Self {
        Self {
            branches,
            action_policy,
            search_policy,
            create_policy,
        }
    }
    
    pub fn rename(&self, old_path: &Path, new_path: &Path) -> Result<(), RenameError> {
        debug!("RenameManager::rename - old_path: {:?}, new_path: {:?}", old_path, new_path);
        
        // 1. Find branches where source file exists using action policy
        let source_branches = self.find_source_branches(old_path)?;
        if source_branches.is_empty() {
            debug!("No source branches found for {:?}", old_path);
            return Err(RenameError::NotFound);
        }
        debug!("Found {} source branches for {:?}", source_branches.len(), old_path);
        
        // 2. Determine target branches
        let target_branches = self.determine_target_branches(&source_branches, old_path, new_path)?;
        
        // 3. Perform renames and track what needs cleanup
        let mut successful_renames = Vec::new();
        let mut errors = Vec::new();
        
        for branch in &target_branches {
            match self.rename_on_branch(branch, old_path, new_path) {
                Ok(()) => {
                    successful_renames.push(branch.clone());
                }
                Err(e) => {
                    errors.push(e);
                }
            }
        }
        
        // 4. If any renames succeeded, clean up source files from other branches
        if !successful_renames.is_empty() && errors.is_empty() {
            self.cleanup_source_files(&source_branches, &successful_renames, old_path);
            Ok(())
        } else if !errors.is_empty() {
            // Return the highest priority error
            let err = self.prioritize_errors(errors);
            Err(err)
        } else {
            // No target branches found
            Err(RenameError::InvalidPath)
        }
    }
    
    fn find_source_branches(&self, path: &Path) -> Result<Vec<Arc<Branch>>, RenameError> {
        let mut branches = Vec::new();
        
        for branch in &self.branches {
            let full_path = branch.full_path(path);
            debug!("Checking branch {:?} for path {:?} -> full_path: {:?}, exists: {}", 
                branch.path, path, full_path, full_path.exists());
            if full_path.exists() {
                branches.push(branch.clone());
            }
        }
        
        Ok(branches)
    }
    
    fn determine_target_branches(
        &self,
        source_branches: &[Arc<Branch>],
        _old_path: &Path,
        _new_path: &Path,
    ) -> Result<Vec<Arc<Branch>>, RenameError> {
        // For now, use a simple strategy: rename on the same branches where file exists
        // TODO: Implement path-preserving vs create-path strategies
        
        let mut target_branches = Vec::new();
        
        for branch in source_branches {
            // Skip read-only branches
            if branch.mode == BranchMode::ReadOnly {
                continue;
            }
            
            target_branches.push(branch.clone());
        }
        
        Ok(target_branches)
    }
    
    fn rename_on_branch(
        &self,
        branch: &Branch,
        old_path: &Path,
        new_path: &Path,
    ) -> Result<(), RenameError> {
        let old_full = branch.full_path(old_path);
        let new_full = branch.full_path(new_path);
        
        // Create parent directory if needed
        if let Some(parent) = new_full.parent() {
            if !parent.exists() {
                fs::create_dir_all(parent).map_err(|e| {
                    if e.kind() == io::ErrorKind::PermissionDenied {
                        RenameError::PermissionDenied
                    } else {
                        RenameError::Io(e)
                    }
                })?;
            }
        }
        
        // Perform the rename
        match fs::rename(&old_full, &new_full) {
            Ok(()) => Ok(()),
            Err(e) => {
                match e.kind() {
                    io::ErrorKind::NotFound => Err(RenameError::NotFound),
                    io::ErrorKind::PermissionDenied => Err(RenameError::PermissionDenied),
                    io::ErrorKind::AlreadyExists => Err(RenameError::DestinationExists),
                    _ => {
                        // Check for EXDEV (cross-device)
                        if let Some(errno) = e.raw_os_error() {
                            if errno == 18 { // EXDEV
                                return Err(RenameError::CrossDevice);
                            }
                        }
                        Err(RenameError::Io(e))
                    }
                }
            }
        }
    }
    
    fn cleanup_source_files(
        &self,
        source_branches: &[Arc<Branch>],
        successful_branches: &[Arc<Branch>],
        old_path: &Path,
    ) {
        for source_branch in source_branches {
            // Don't remove from branches where rename succeeded
            if successful_branches.iter().any(|b| Arc::ptr_eq(b, source_branch)) {
                continue;
            }
            
            // Don't remove from read-only branches
            if source_branch.mode == BranchMode::ReadOnly {
                continue;
            }
            
            // Remove the source file
            let full_path = source_branch.path.join(old_path);
            let _ = fs::remove_file(full_path);
        }
    }
    
    fn prioritize_errors(&self, errors: Vec<RenameError>) -> RenameError {
        errors.into_iter()
            .max_by_key(|e| e.priority())
            .unwrap_or(RenameError::Io(io::Error::new(io::ErrorKind::Other, "Unknown error")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::{AllActionPolicy, FirstFoundSearchPolicy, FirstFoundCreatePolicy};
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
        
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
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
        
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
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
        
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
        );
        
        let result = rename_mgr.rename(Path::new("nonexistent.txt"), Path::new("new.txt"));
        assert!(matches!(result, Err(RenameError::NotFound)));
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
        
        let rename_mgr = RenameManager::new(
            vec![branch1.clone(), branch2.clone()],
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
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
        
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
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