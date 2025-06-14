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
            Box::new(AllActionPolicy),
            Box::new(FirstFoundSearchPolicy),
            Box::new(FirstFoundCreatePolicy),
            config,
        );
        
        // Perform rename
        let result = rename_mgr.rename(old_path, new_path);
        
        match &result {
            Ok(()) => println!("Rename succeeded"),
            Err(e) => println!("Rename failed: {:?}", e),
        }
        
        assert!(result.is_ok(), "Rename failed: {:?}", result);
        
        // Verify rename
        assert!(!branch2.path.join(old_path).exists());
        assert!(branch2.path.join(new_path).exists());
    }
}