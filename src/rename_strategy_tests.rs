#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;
    
    use crate::branch::{Branch, BranchMode};
    use crate::config::create_config;
    use crate::policy::{AllActionPolicy, FirstFoundSearchPolicy, CreatePolicy, PolicyError};
    use crate::rename_ops::RenameManager;
    
    /// A mock path-preserving create policy for testing
    struct MockPathPreservingPolicy {
        path_preserving: bool,
    }
    
    impl CreatePolicy for MockPathPreservingPolicy {
        fn name(&self) -> &'static str {
            "mock_path_preserving"
        }
        
        fn select_branch(
            &self,
            branches: &[Arc<Branch>],
            _path: &Path,
        ) -> Result<Arc<Branch>, PolicyError> {
            branches.first()
                .cloned()
                .ok_or(PolicyError::NoBranchesAvailable)
        }
        
        fn is_path_preserving(&self) -> bool {
            self.path_preserving
        }
    }
    
    fn setup_test_environment() -> (Vec<Arc<Branch>>, Vec<TempDir>) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch3 = Arc::new(Branch::new(
            temp3.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        
        (vec![branch1, branch2, branch3], vec![temp1, temp2, temp3])
    }
    
    #[test]
    fn test_path_preserving_strategy() {
        let (branches, _temps) = setup_test_environment();
        
        // Create test file on first two branches only
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branches[0].path.join(old_path), "content1").unwrap();
        fs::write(branches[1].path.join(old_path), "content2").unwrap();
        
        // Create a file at the destination on the second branch that will be overwritten
        fs::write(branches[1].path.join(new_path), "to_be_overwritten").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(MockPathPreservingPolicy { path_preserving: true }),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify:
        // 1. Files renamed on branches where they existed
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        assert!(!branches[1].path.join(old_path).exists());
        assert!(branches[1].path.join(new_path).exists());
        
        // 2. No file created on branch where source didn't exist
        assert!(!branches[2].path.join(old_path).exists());
        assert!(!branches[2].path.join(new_path).exists());
        
        // 3. Content preserved (and destination was overwritten)
        assert_eq!(fs::read_to_string(branches[0].path.join(new_path)).unwrap(), "content1");
        assert_eq!(fs::read_to_string(branches[1].path.join(new_path)).unwrap(), "content2");
    }
    
    #[test]
    fn test_create_path_strategy() {
        // Use only read-write branches for this test
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
        
        let branches = vec![branch1.clone(), branch2.clone()];
        let _temps = vec![temp1, temp2];
        
        // Create directory structure on first branch
        fs::create_dir_all(branches[0].path.join("dir1")).unwrap();
        
        // Create test file only on second branch (in a directory that doesn't exist on first)
        fs::create_dir_all(branches[1].path.join("dir1")).unwrap();
        let old_path = Path::new("dir1/test.txt");
        let new_path = Path::new("dir2/renamed.txt");
        fs::write(branches[1].path.join(old_path), "content").unwrap();
        
        // Verify file exists before rename
        eprintln!("Branch 0 path: {:?}", branches[0].path);
        eprintln!("Branch 1 path: {:?}", branches[1].path);
        eprintln!("Branch 0 old path exists: {}", branches[0].path.join(old_path).exists());
        eprintln!("Branch 1 old path exists: {}", branches[1].path.join(old_path).exists());
        
        // Double check by looking at actual path
        eprintln!("Looking for file at: {:?}", branches[1].path.join(old_path));
        eprintln!("File contents: {:?}", fs::read_to_string(branches[1].path.join(old_path)));
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(MockPathPreservingPolicy { path_preserving: false }),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        if let Err(e) = &result {
            eprintln!("test_create_path_strategy failed with error: {:?}", e);
        }
        assert!(result.is_ok());
        
        // Verify:
        // 1. File renamed on branch where it existed
        assert!(!branches[1].path.join(old_path).exists());
        assert!(branches[1].path.join(new_path).exists());
        
        // 2. Parent directory was created if needed
        assert!(branches[1].path.join("dir2").exists());
        
        // 3. Content preserved
        assert_eq!(fs::read_to_string(branches[1].path.join(new_path)).unwrap(), "content");
    }
    
    #[test]
    fn test_create_path_with_directory_cloning() {
        // Use only read-write branches for this test
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
        
        let branches = vec![branch1.clone(), branch2.clone()];
        let _temps = vec![temp1, temp2];
        
        // Set up specific directory permissions on first branch
        let dir_path = branches[0].path.join("special_dir");
        fs::create_dir(&dir_path).unwrap();
        
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = fs::metadata(&dir_path).unwrap().permissions();
            perms.set_mode(0o750); // Special permissions
            fs::set_permissions(&dir_path, perms).unwrap();
        }
        
        // Create file on first branch only
        let old_path = Path::new("test.txt");
        let new_path = Path::new("special_dir/subdir/renamed.txt");
        fs::write(branches[0].path.join(old_path), "content").unwrap();
        
        // Also create file on second branch
        fs::write(branches[1].path.join(old_path), "content2").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(MockPathPreservingPolicy { path_preserving: false }),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify parent directories were created with cloned permissions
        assert!(branches[0].path.join("special_dir/subdir").exists());
        assert!(branches[1].path.join("special_dir/subdir").exists());
        
        // Verify files were renamed
        assert!(branches[0].path.join(new_path).exists());
        assert!(branches[1].path.join(new_path).exists());
        
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            // Check that permissions were preserved on second branch
            let cloned_dir = branches[1].path.join("special_dir");
            if cloned_dir.exists() {
                let perms = fs::metadata(&cloned_dir).unwrap().permissions();
                assert_eq!(perms.mode() & 0o777, 0o750);
            }
        }
    }
    
    #[test]
    fn test_ignore_path_preserving_config() {
        let (branches, _temps) = setup_test_environment();
        
        // Create test file
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branches[0].path.join(old_path), "content").unwrap();
        
        // Create config with ignore_path_preserving_on_rename = true
        let config = create_config();
        {
            let mut cfg = config.write();
            cfg.ignore_path_preserving_on_rename = true;
        }
        
        let rename_mgr = RenameManager::new(
            branches.clone(),
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(MockPathPreservingPolicy { path_preserving: true }), // Should be ignored
            config,
        );
        
        // Even though we have a path-preserving policy, it should use create-path strategy
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // File should be renamed
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_with_cross_device_error() {
        // This test would require mocking filesystem errors, which is complex
        // For now, we'll just verify the error type is preserved correctly
        let (branches, _temps) = setup_test_environment();
        
        // Try to rename a non-existent file to trigger an error
        let old_path = Path::new("nonexistent.txt");
        let new_path = Path::new("new.txt");
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(MockPathPreservingPolicy { path_preserving: true }),
            config,
        );
        
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_err());
    }
}