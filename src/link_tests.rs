#[cfg(test)]
mod tests {
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::FirstFoundCreatePolicy;
    use std::fs;
    use std::os::unix::fs::MetadataExt;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[test]
    fn test_create_hard_link_same_branch() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a source file
        let source_path = Path::new("/source.txt");
        let full_source = branch.full_path(source_path);
        fs::write(&full_source, b"Hello, world!").unwrap();
        
        // Create a hard link
        let link_path = Path::new("/link.txt");
        file_manager.create_hard_link(source_path, link_path).unwrap();
        
        // Verify link exists
        let full_link = branch.full_path(link_path);
        assert!(full_link.exists());
        
        // Verify it's a hard link (same inode)
        let source_meta = fs::metadata(&full_source).unwrap();
        let link_meta = fs::metadata(&full_link).unwrap();
        assert_eq!(source_meta.ino(), link_meta.ino());
        assert_eq!(source_meta.nlink(), 2);
        assert_eq!(link_meta.nlink(), 2);
        
        // Verify content is the same
        let content = fs::read_to_string(&full_link).unwrap();
        assert_eq!(content, "Hello, world!");
    }
    
    #[test]
    fn test_create_hard_link_with_parent_dirs() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a source file
        let source_path = Path::new("/source.txt");
        let full_source = branch.full_path(source_path);
        fs::write(&full_source, b"Test content").unwrap();
        
        // Create a hard link in a nested directory
        let link_path = Path::new("/dir1/dir2/link.txt");
        file_manager.create_hard_link(source_path, link_path).unwrap();
        
        // Verify parent directories were created
        assert!(branch.full_path(Path::new("/dir1")).exists());
        assert!(branch.full_path(Path::new("/dir1/dir2")).exists());
        
        // Verify link exists
        let full_link = branch.full_path(link_path);
        assert!(full_link.exists());
        
        // Verify it's a hard link
        let source_meta = fs::metadata(&full_source).unwrap();
        let link_meta = fs::metadata(&full_link).unwrap();
        assert_eq!(source_meta.ino(), link_meta.ino());
    }
    
    #[test]
    fn test_create_hard_link_source_not_found() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Try to create a hard link to a non-existent file
        let source_path = Path::new("/nonexistent.txt");
        let link_path = Path::new("/link.txt");
        
        let result = file_manager.create_hard_link(source_path, link_path);
        assert!(result.is_err());
        // Should return NoBranchesAvailable since the file doesn't exist
        assert!(matches!(result, Err(crate::policy::PolicyError::NoBranchesAvailable)));
    }
    
    #[test]
    fn test_create_hard_link_to_directory_fails() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a directory
        let dir_path = Path::new("/testdir");
        let full_dir = branch.full_path(dir_path);
        fs::create_dir(&full_dir).unwrap();
        
        // Try to create a hard link to the directory
        let link_path = Path::new("/dirlink");
        let result = file_manager.create_hard_link(dir_path, link_path);
        
        // Should fail - hard links to directories are not allowed
        assert!(result.is_err());
    }
    
    #[test]
    fn test_create_hard_link_multiple_branches() {
        let temp_dir = TempDir::new().unwrap();
        let branch1_path = temp_dir.path().join("branch1");
        let branch2_path = temp_dir.path().join("branch2");
        
        fs::create_dir(&branch1_path).unwrap();
        fs::create_dir(&branch2_path).unwrap();
        
        let branch1 = Arc::new(Branch::new(branch1_path.clone(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(branch2_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch1.clone(), branch2.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create source file on branch1
        let source_path = Path::new("/source.txt");
        let full_source = branch1.full_path(source_path);
        fs::write(&full_source, b"Branch1 content").unwrap();
        
        // Create hard link - should be created on the same branch as source
        let link_path = Path::new("/link.txt");
        file_manager.create_hard_link(source_path, link_path).unwrap();
        
        // Verify link exists on branch1 (same branch as source)
        let full_link1 = branch1.full_path(link_path);
        assert!(full_link1.exists());
        
        // Verify link does NOT exist on branch2
        let full_link2 = branch2.full_path(link_path);
        assert!(!full_link2.exists());
        
        // Verify it's a hard link on branch1
        let source_meta = fs::metadata(&full_source).unwrap();
        let link_meta = fs::metadata(&full_link1).unwrap();
        assert_eq!(source_meta.ino(), link_meta.ino());
    }
    
    #[test]
    fn test_create_hard_link_readonly_branch() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        // Create source file while branch is writable
        let source_path = Path::new("/source.txt");
        fs::write(branch_path.join("source.txt"), b"Content").unwrap();
        
        // Create branch as read-only
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadOnly));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Try to create a hard link on read-only branch
        let link_path = Path::new("/link.txt");
        let result = file_manager.create_hard_link(source_path, link_path);
        
        // Should fail with permission error
        assert!(result.is_err());
        match result {
            Err(crate::policy::PolicyError::IoError(e)) => {
                assert_eq!(e.kind(), std::io::ErrorKind::PermissionDenied);
            }
            _ => panic!("Expected permission denied error"),
        }
    }
    
    #[test]
    fn test_create_multiple_hard_links() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a source file
        let source_path = Path::new("/source.txt");
        let full_source = branch.full_path(source_path);
        fs::write(&full_source, b"Original content").unwrap();
        
        // Create first hard link
        let link1_path = Path::new("/link1.txt");
        file_manager.create_hard_link(source_path, link1_path).unwrap();
        
        // Create second hard link
        let link2_path = Path::new("/link2.txt");
        file_manager.create_hard_link(source_path, link2_path).unwrap();
        
        // Verify all three files have the same inode and link count of 3
        let source_meta = fs::metadata(&full_source).unwrap();
        let link1_meta = fs::metadata(&branch.full_path(link1_path)).unwrap();
        let link2_meta = fs::metadata(&branch.full_path(link2_path)).unwrap();
        
        assert_eq!(source_meta.ino(), link1_meta.ino());
        assert_eq!(source_meta.ino(), link2_meta.ino());
        assert_eq!(source_meta.nlink(), 3);
        assert_eq!(link1_meta.nlink(), 3);
        assert_eq!(link2_meta.nlink(), 3);
    }
    
    #[test]
    fn test_create_hard_link_preserves_permissions() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a source file with specific permissions
        let source_path = Path::new("/source.txt");
        let full_source = branch.full_path(source_path);
        fs::write(&full_source, b"Test content").unwrap();
        
        // Set specific permissions
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&full_source).unwrap().permissions();
        perms.set_mode(0o644);
        fs::set_permissions(&full_source, perms).unwrap();
        
        // Create hard link
        let link_path = Path::new("/link.txt");
        file_manager.create_hard_link(source_path, link_path).unwrap();
        
        // Verify permissions are the same
        let source_meta = fs::metadata(&full_source).unwrap();
        let link_meta = fs::metadata(&branch.full_path(link_path)).unwrap();
        assert_eq!(source_meta.mode() & 0o777, 0o644);
        assert_eq!(link_meta.mode() & 0o777, 0o644);
    }
}