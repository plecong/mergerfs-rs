use crate::branch::Branch;
use crate::policy::{PolicyError, SearchPolicy};
use std::path::Path;
use std::sync::Arc;
use std::time::SystemTime;

/// Newest search policy - returns the branch with the newest modification time
pub struct NewestSearchPolicy;

impl NewestSearchPolicy {
    pub fn new() -> Self {
        Self
    }
}

impl SearchPolicy for NewestSearchPolicy {
    fn name(&self) -> &'static str {
        "newest"
    }

    /// Search for a path and return the branch with the newest modification time
    fn search_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut newest_branch = None;
        let mut newest_time = SystemTime::UNIX_EPOCH;
        
        for branch in branches.iter() {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                match full_path.metadata() {
                    Ok(metadata) => {
                        if let Ok(modified) = metadata.modified() {
                            if modified > newest_time {
                                newest_time = modified;
                                newest_branch = Some(Arc::clone(branch));
                            }
                        }
                    }
                    Err(_) => continue,
                }
            }
        }
        
        match newest_branch {
            Some(branch) => Ok(vec![branch]),
            None => Err(PolicyError::NoBranchesAvailable),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::BranchMode;
    use std::fs;
    use std::thread;
    use std::time::Duration;
    use tempfile::TempDir;

    fn setup_test_branches() -> (Vec<TempDir>, Vec<Arc<Branch>>) {
        let temp_dirs = vec![
            TempDir::new().unwrap(),
            TempDir::new().unwrap(),
            TempDir::new().unwrap(),
        ];
        
        let branches = temp_dirs
            .iter()
            .map(|dir| Arc::new(Branch::new(dir.path().to_path_buf(), BranchMode::ReadWrite)))
            .collect();
            
        (temp_dirs, branches)
    }

    #[test]
    fn test_newest_finds_most_recent_file() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = NewestSearchPolicy::new();
        
        // Create files with different timestamps
        for (idx, branch) in branches.iter().enumerate() {
            let file_path = branch.full_path(Path::new("test.txt"));
            fs::write(&file_path, format!("test{}", idx)).unwrap();
            
            // Add small delay between file creations to ensure different mtimes
            thread::sleep(Duration::from_millis(10));
        }
        
        let result = policy.search_branches(&branches, Path::new("test.txt")).unwrap();
        // Should return exactly one branch
        assert_eq!(result.len(), 1);
    }
    
    #[test]
    fn test_newest_finds_only_existing_file() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = NewestSearchPolicy::new();
        
        // Create file only in middle branch
        let file_path = branches[1].full_path(Path::new("single.txt"));
        fs::write(&file_path, "test").unwrap();
        
        let result = policy.search_branches(&branches, Path::new("single.txt")).unwrap();
        assert_eq!(result.len(), 1);
        // Verify it's the correct branch
        assert_eq!(result[0].path, branches[1].path);
    }
    
    #[test]
    fn test_newest_returns_error_when_not_found() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = NewestSearchPolicy::new();
        
        let result = policy.search_branches(&branches, Path::new("nonexistent.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_newest_works_with_directories() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = NewestSearchPolicy::new();
        
        // Create directories with delays
        let dir_path_0 = branches[0].full_path(Path::new("testdir"));
        fs::create_dir(&dir_path_0).unwrap();
        
        thread::sleep(Duration::from_millis(50));
        
        let dir_path_2 = branches[2].full_path(Path::new("testdir"));
        fs::create_dir(&dir_path_2).unwrap();
        
        let result = policy.search_branches(&branches, Path::new("testdir")).unwrap();
        assert_eq!(result.len(), 1);
        // Verify it's the last branch
        assert_eq!(result[0].path, branches[2].path);
    }
    
    #[test]
    fn test_newest_with_updated_file() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = NewestSearchPolicy::new();
        
        // Create files in all branches
        for branch in &branches {
            let file_path = branch.full_path(Path::new("update.txt"));
            fs::write(&file_path, "initial").unwrap();
        }
        
        // Wait and update the file in branch 0
        thread::sleep(Duration::from_millis(50));
        let update_path = branches[0].full_path(Path::new("update.txt"));
        fs::write(&update_path, "updated").unwrap();
        
        let result = policy.search_branches(&branches, Path::new("update.txt")).unwrap();
        assert_eq!(result.len(), 1);
        // Verify it's the first branch (where we updated)
        assert_eq!(result[0].path, branches[0].path);
    }
}