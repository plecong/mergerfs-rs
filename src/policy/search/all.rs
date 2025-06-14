use crate::branch::Branch;
use crate::policy::{PolicyError, SearchPolicy};
use std::path::Path;
use std::sync::Arc;

/// All search policy - returns all branches where the path exists
pub struct AllSearchPolicy;

impl AllSearchPolicy {
    pub fn new() -> Self {
        Self
    }
}

impl SearchPolicy for AllSearchPolicy {
    fn name(&self) -> &'static str {
        "all"
    }

    /// Search for a path and return all branches where it exists
    fn search_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut found_branches = Vec::new();
        
        for branch in branches.iter() {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                found_branches.push(Arc::clone(branch));
            }
        }
        
        if found_branches.is_empty() {
            Err(PolicyError::NoBranchesAvailable)
        } else {
            Ok(found_branches)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::BranchMode;
    use std::fs;
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
    fn test_all_finds_file_in_all_branches() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = AllSearchPolicy::new();
        
        // Create file in all branches
        for branch in &branches {
            let file_path = branch.full_path(Path::new("test.txt"));
            fs::write(&file_path, "test").unwrap();
        }
        
        let result = policy.search_branches(&branches, Path::new("test.txt")).unwrap();
        assert_eq!(result.len(), 3);
    }
    
    #[test]
    fn test_all_finds_file_in_some_branches() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = AllSearchPolicy::new();
        
        // Create file only in first and last branch
        let file_path_0 = branches[0].full_path(Path::new("partial.txt"));
        fs::write(&file_path_0, "test").unwrap();
        
        let file_path_2 = branches[2].full_path(Path::new("partial.txt"));
        fs::write(&file_path_2, "test").unwrap();
        
        let result = policy.search_branches(&branches, Path::new("partial.txt")).unwrap();
        assert_eq!(result.len(), 2);
    }
    
    #[test]
    fn test_all_returns_error_when_not_found() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = AllSearchPolicy::new();
        
        let result = policy.search_branches(&branches, Path::new("nonexistent.txt"));
        assert!(matches!(result, Err(PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_all_works_with_directories() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = AllSearchPolicy::new();
        
        // Create directory in branches 0 and 1
        let dir_path_0 = branches[0].full_path(Path::new("testdir"));
        fs::create_dir(&dir_path_0).unwrap();
        
        let dir_path_1 = branches[1].full_path(Path::new("testdir"));
        fs::create_dir(&dir_path_1).unwrap();
        
        let result = policy.search_branches(&branches, Path::new("testdir")).unwrap();
        assert_eq!(result.len(), 2);
    }
    
    #[test]
    fn test_all_works_with_nested_paths() {
        let (_temp_dirs, branches) = setup_test_branches();
        let policy = AllSearchPolicy::new();
        
        // Create nested file in branch 1
        let nested_dir = branches[1].full_path(Path::new("dir1/dir2"));
        fs::create_dir_all(&nested_dir).unwrap();
        let nested_file = branches[1].full_path(Path::new("dir1/dir2/file.txt"));
        fs::write(&nested_file, "nested").unwrap();
        
        let result = policy.search_branches(&branches, Path::new("dir1/dir2/file.txt")).unwrap();
        assert_eq!(result.len(), 1);
    }
}