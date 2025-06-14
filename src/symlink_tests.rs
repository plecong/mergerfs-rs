#[cfg(test)]
mod tests {
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::FirstFoundCreatePolicy;
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[test]
    fn test_create_symlink_basic() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a symlink
        let link_path = Path::new("/test_link");
        let target = Path::new("/target/file.txt");
        
        file_manager.create_symlink(link_path, target).unwrap();
        
        // Verify symlink exists
        // Need to match how Branch::full_path works - it strips leading /
        let full_link_path = branch.full_path(link_path);
        
        // Use symlink_metadata to check if symlink exists (even if broken)
        assert!(fs::symlink_metadata(&full_link_path).is_ok(), "Symlink not found at {:?}", full_link_path);
        
        // Verify it's a symlink and points to the correct target
        let metadata = fs::symlink_metadata(&full_link_path).unwrap();
        assert!(metadata.file_type().is_symlink());
        
        let read_target = fs::read_link(&full_link_path).unwrap();
        assert_eq!(read_target, target);
    }
    
    #[test]
    fn test_create_symlink_with_parent_dirs() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a symlink in a nested directory
        let link_path = Path::new("/dir1/dir2/test_link");
        let target = Path::new("../../../target/file.txt");
        
        file_manager.create_symlink(link_path, target).unwrap();
        
        // Verify parent directories were created
        assert!(fs::metadata(&branch.full_path(Path::new("/dir1"))).is_ok());
        assert!(fs::metadata(&branch.full_path(Path::new("/dir1/dir2"))).is_ok());
        
        // Verify symlink exists
        let full_link_path = branch.full_path(link_path);
        assert!(fs::symlink_metadata(&full_link_path).is_ok());
        
        let metadata = fs::symlink_metadata(&full_link_path).unwrap();
        assert!(metadata.file_type().is_symlink());
        
        let read_target = fs::read_link(&full_link_path).unwrap();
        assert_eq!(read_target, target);
    }
    
    #[test]
    fn test_create_symlink_with_clone_path() {
        let temp_dir = TempDir::new().unwrap();
        let branch1_path = temp_dir.path().join("branch1");
        let branch2_path = temp_dir.path().join("branch2");
        
        fs::create_dir(&branch1_path).unwrap();
        fs::create_dir(&branch2_path).unwrap();
        
        // Create parent directory structure in branch1 with specific permissions
        let parent_dir = branch1_path.join("parent/subdir");
        fs::create_dir_all(&parent_dir).unwrap();
        
        // Set specific permissions on parent directories
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&branch1_path.join("parent")).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&branch1_path.join("parent"), perms).unwrap();
        
        // Create branches - branch1 has the parent structure, branch2 doesn't
        let branch1 = Arc::new(Branch::new(branch1_path.clone(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(branch2_path.clone(), BranchMode::ReadWrite));
        // Put branch2 first so FirstFound policy will select it
        let branches = vec![branch2.clone(), branch1.clone()];
        
        // Use FirstFound policy which will select branch2 (which doesn't have the parent structure)
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Create a symlink in branch2 (which doesn't have the parent structure)
        let link_path = Path::new("/parent/subdir/test_link");
        let target = Path::new("/target");
        
        file_manager.create_symlink(link_path, target).unwrap();
        
        // Verify parent directories were cloned to branch2
        assert!(fs::metadata(&branch2.full_path(Path::new("/parent"))).is_ok());
        assert!(fs::metadata(&branch2.full_path(Path::new("/parent/subdir"))).is_ok());
        
        // Verify permissions were preserved
        let cloned_perms = fs::metadata(&branch2.full_path(Path::new("/parent"))).unwrap().permissions();
        assert_eq!(cloned_perms.mode() & 0o777, 0o755);
        
        // Verify symlink exists in branch2
        let full_link_path = branch2.full_path(link_path);
        assert!(fs::symlink_metadata(&full_link_path).is_ok());
        
        let metadata = fs::symlink_metadata(&full_link_path).unwrap();
        assert!(metadata.file_type().is_symlink());
    }
    
    #[test] 
    fn test_create_symlink_readonly_branch() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        // Create a read-only branch
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadOnly));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Try to create a symlink - should fail
        let link_path = Path::new("/test_link");
        let target = Path::new("/target/file.txt");
        
        let result = file_manager.create_symlink(link_path, target);
        assert!(result.is_err());
    }
    
    #[test]
    fn test_create_symlink_absolute_relative_targets() {
        let temp_dir = TempDir::new().unwrap();
        let branch_path = temp_dir.path().to_path_buf();
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        let branches = vec![branch.clone()];
        
        let create_policy = Box::new(FirstFoundCreatePolicy::new());
        let file_manager = FileManager::new(branches, create_policy);
        
        // Test with absolute target
        let abs_link = Path::new("/abs_link");
        let abs_target = Path::new("/absolute/path/to/target");
        file_manager.create_symlink(abs_link, abs_target).unwrap();
        
        let full_abs_link = branch.full_path(abs_link);
        assert_eq!(fs::read_link(&full_abs_link).unwrap(), abs_target);
        
        // Test with relative target
        let rel_link = Path::new("/rel_link");
        let rel_target = Path::new("relative/path");
        file_manager.create_symlink(rel_link, rel_target).unwrap();
        
        let full_rel_link = branch.full_path(rel_link);
        assert_eq!(fs::read_link(&full_rel_link).unwrap(), rel_target);
    }
}