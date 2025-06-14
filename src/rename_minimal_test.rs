#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;
    
    use crate::branch::{Branch, BranchMode};
    use crate::config::create_config;
    use crate::policy::{AllActionPolicy, FirstFoundSearchPolicy, FirstFoundCreatePolicy};
    use crate::rename_ops::RenameManager;
    
    #[test]
    fn test_simple_create_path_rename() {
        // Setup
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
        
        // Create test file on second branch only
        let old_path = Path::new("test.txt");
        let new_path = Path::new("renamed.txt");
        fs::write(branch2.path.join(old_path), "content").unwrap();
        
        // Verify file exists before rename
        assert!(branch2.path.join(old_path).exists());
        assert!(!branch1.path.join(old_path).exists());
        
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
        assert!(result.is_ok(), "Rename failed: {:?}", result);
        
        // Verify rename
        assert!(!branch2.path.join(old_path).exists());
        assert!(branch2.path.join(new_path).exists());
    }
    
    #[test]
    fn test_rename_with_subdirectories() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        // Create directory structure and file on first branch
        fs::create_dir_all(branches[0].path.join("dir1/subdir")).unwrap();
        let old_path = Path::new("dir1/subdir/test.txt");
        let new_path = Path::new("dir2/newdir/renamed.txt");
        fs::write(branches[0].path.join(old_path), "content").unwrap();
        
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
        assert!(result.is_ok(), "Rename failed: {:?}", result);
        
        // Verify rename and directory creation
        assert!(!branches[0].path.join(old_path).exists());
        assert!(branches[0].path.join(new_path).exists());
        assert!(branches[0].path.join("dir2/newdir").is_dir());
    }
}