#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;
    
    use crate::branch::{Branch, BranchMode};
    use crate::config::create_config;
    use crate::policy::{AllActionPolicy, FirstFoundSearchPolicy, FirstFoundCreatePolicy};
    use crate::rename_ops::{RenameManager, RenameError};
    
    #[test]
    fn test_rename_to_existing_file() {
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        // Create source and destination files
        let old_path = Path::new("source.txt");
        let new_path = Path::new("dest.txt");
        fs::write(branch.path.join(old_path), "source content").unwrap();
        fs::write(branch.path.join(new_path), "dest content").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename should overwrite existing file
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify source is gone and destination has source content
        assert!(!branch.path.join(old_path).exists());
        assert!(branch.path.join(new_path).exists());
        let content = fs::read_to_string(branch.path.join(new_path)).unwrap();
        assert_eq!(content, "source content");
    }
    
    #[test]
    fn test_rename_empty_directory() {
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        // Create empty directory
        let old_path = Path::new("old_dir");
        let new_path = Path::new("new_dir");
        fs::create_dir(branch.path.join(old_path)).unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename directory
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename
        assert!(!branch.path.join(old_path).exists());
        assert!(branch.path.join(new_path).exists());
        assert!(branch.path.join(new_path).is_dir());
    }
    
    #[test]
    fn test_rename_directory_with_contents() {
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        // Create directory with contents
        let old_path = Path::new("old_dir");
        let new_path = Path::new("new_dir");
        fs::create_dir(branch.path.join(old_path)).unwrap();
        fs::write(branch.path.join(old_path).join("file1.txt"), "content1").unwrap();
        fs::write(branch.path.join(old_path).join("file2.txt"), "content2").unwrap();
        fs::create_dir(branch.path.join(old_path).join("subdir")).unwrap();
        fs::write(branch.path.join(old_path).join("subdir/file3.txt"), "content3").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename directory
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename and contents
        assert!(!branch.path.join(old_path).exists());
        assert!(branch.path.join(new_path).exists());
        assert!(branch.path.join(new_path).join("file1.txt").exists());
        assert!(branch.path.join(new_path).join("file2.txt").exists());
        assert!(branch.path.join(new_path).join("subdir/file3.txt").exists());
        
        // Verify file contents preserved
        let content1 = fs::read_to_string(branch.path.join(new_path).join("file1.txt")).unwrap();
        assert_eq!(content1, "content1");
    }
    
    #[test]
    fn test_rename_with_all_readonly_branches() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadOnly)),
            Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly)),
        ];
        
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
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename should fail with all readonly branches
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_err());
        
        // Files should remain unchanged
        assert!(branches[0].path.join(old_path).exists());
        assert!(branches[1].path.join(old_path).exists());
        assert!(!branches[0].path.join(new_path).exists());
        assert!(!branches[1].path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_partial_success() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadOnly)),
        ];
        
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
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename should succeed on writable branch only
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename on writable branch
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        
        // Read-only branch unchanged
        assert!(branches[1].path.join(old_path).exists());
        assert!(!branches[1].path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_with_no_create_branch() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::NoCreate)),
        ];
        
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
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename should work on both branches (NoCreate allows modifications)
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify rename on both branches
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        assert!(!branches[1].path.join(old_path).exists());
        assert!(branches[1].path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_nonexistent_parent_directory() {
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        // Create file
        let old_path = Path::new("test.txt");
        let new_path = Path::new("deep/nested/dir/renamed.txt");
        fs::write(branch.path.join(old_path), "content").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename should create parent directories
        let result = rename_mgr.rename(old_path, new_path);
        assert!(result.is_ok());
        
        // Verify directory structure created
        assert!(branch.path.join("deep/nested/dir").exists());
        assert!(branch.path.join(new_path).exists());
        assert!(!branch.path.join(old_path).exists());
    }
    
    #[test]
    fn test_rename_same_path() {
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        // Create file
        let path = Path::new("test.txt");
        fs::write(branch.path.join(path), "content").unwrap();
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Rename to same path should succeed (no-op)
        let result = rename_mgr.rename(path, path);
        assert!(result.is_ok());
        
        // File should still exist with same content
        assert!(branch.path.join(path).exists());
        let content = fs::read_to_string(branch.path.join(path)).unwrap();
        assert_eq!(content, "content");
    }
    
    #[test]
    fn test_rename_with_permission_error() {
        // This test would require setting up specific permissions that cause rename to fail
        // For now, we'll test the error handling path by trying to rename a non-existent file
        let temp = TempDir::new().unwrap();
        let branch = Arc::new(Branch::new(temp.path().to_path_buf(), BranchMode::ReadWrite));
        let branches = vec![branch];
        
        let old_path = Path::new("nonexistent.txt");
        let new_path = Path::new("renamed.txt");
        
        let config = create_config();
        let rename_mgr = RenameManager::new(
            branches,
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy::new()),
            config,
        );
        
        // Should fail with NotFound
        let result = rename_mgr.rename(old_path, new_path);
        assert!(matches!(result, Err(RenameError::Policy(_))));
    }
}