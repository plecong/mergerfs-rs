#[cfg(test)]
mod directory_ops_tests {
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::FirstFoundCreatePolicy;
    use serial_test::serial;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;

    fn setup_test_dirs() -> (Vec<TempDir>, FileManager) {
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

        let branches = vec![branch1, branch2, branch3];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        (vec![temp1, temp2, temp3], file_manager)
    }

    #[test]
    #[serial]
    fn test_mkdir_creates_directory_in_first_writable_branch() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Test creating a directory
        let dir_path = Path::new("test_directory");
        let result = file_manager.create_directory(dir_path);
        assert!(result.is_ok(), "Should be able to create directory: {:?}", result);

        // Verify directory was created in first writable branch (branch1)
        let expected_path = temp_dirs[0].path().join("test_directory");
        assert!(expected_path.exists(), "Directory should exist in first branch");
        assert!(expected_path.is_dir(), "Path should be a directory");

        // Verify directory was NOT created in other branches
        let path2 = temp_dirs[1].path().join("test_directory");
        let path3 = temp_dirs[2].path().join("test_directory");
        assert!(!path2.exists(), "Directory should NOT exist in second branch");
        assert!(!path3.exists(), "Directory should NOT exist in readonly branch");
    }

    #[test]
    #[serial]
    fn test_mkdir_nested_directories() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Test creating nested directories
        let nested_path = Path::new("parent/child/grandchild");
        let result = file_manager.create_directory(nested_path);
        assert!(result.is_ok(), "Should be able to create nested directories: {:?}", result);

        // Verify all levels were created in first branch
        let branch1_path = temp_dirs[0].path();
        assert!(branch1_path.join("parent").is_dir());
        assert!(branch1_path.join("parent/child").is_dir());
        assert!(branch1_path.join("parent/child/grandchild").is_dir());
    }

    #[test]
    #[serial]
    fn test_mkdir_skips_readonly_branches() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();

        // First branch is readonly, second is writable
        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));

        let branches = vec![branch1, branch2.clone()];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        // Create directory - should skip readonly branch1 and use branch2
        let dir_path = Path::new("writable_dir");
        let result = file_manager.create_directory(dir_path);
        assert!(result.is_ok(), "Should create directory in writable branch");

        // Verify directory is in second branch only
        let path1 = temp1.path().join("writable_dir");
        let path2 = temp2.path().join("writable_dir");
        assert!(!path1.exists(), "Directory should NOT be in readonly branch");
        assert!(path2.exists() && path2.is_dir(), "Directory should be in writable branch");
    }

    #[test]
    #[serial]
    fn test_directory_exists_check() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Initially, directory should not exist
        let dir_path = Path::new("existence_test");
        assert!(!file_manager.directory_exists(dir_path), "Directory should not exist initially");

        // Create directory
        file_manager.create_directory(dir_path).unwrap();

        // Now it should exist
        assert!(file_manager.directory_exists(dir_path), "Directory should exist after creation");
    }

    #[test]
    #[serial]
    fn test_list_directory_contents_union() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Create different files in different branches manually
        let branch1_path = temp_dirs[0].path();
        let branch2_path = temp_dirs[1].path();

        // Create files in branch1
        std::fs::write(branch1_path.join("file1.txt"), "content1").unwrap();
        std::fs::write(branch1_path.join("shared.txt"), "from branch1").unwrap();
        std::fs::create_dir(branch1_path.join("dir1")).unwrap();

        // Create files in branch2
        std::fs::write(branch2_path.join("file2.txt"), "content2").unwrap();
        std::fs::write(branch2_path.join("shared.txt"), "from branch2").unwrap();
        std::fs::create_dir(branch2_path.join("dir2")).unwrap();

        // List directory contents - should show union of all branches
        let contents = file_manager.list_directory(Path::new("."));
        assert!(contents.is_ok(), "Should be able to list directory contents");

        let entries = contents.unwrap();
        let entry_names: Vec<&str> = entries.iter().map(|e| e.as_str()).collect();

        // Should contain files from both branches
        assert!(entry_names.contains(&"file1.txt"), "Should contain file1.txt from branch1");
        assert!(entry_names.contains(&"file2.txt"), "Should contain file2.txt from branch2");
        assert!(entry_names.contains(&"dir1"), "Should contain dir1 from branch1");
        assert!(entry_names.contains(&"dir2"), "Should contain dir2 from branch2");

        // Should only contain one instance of shared.txt (first found)
        let shared_count = entry_names.iter().filter(|&&name| name == "shared.txt").count();
        assert_eq!(shared_count, 1, "Should only show one instance of shared.txt");
    }

    #[test]
    #[serial]
    fn test_rmdir_removes_empty_directory() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Create a directory first
        let dir_path = Path::new("to_remove");
        file_manager.create_directory(dir_path).unwrap();

        // Verify it exists
        let branch1_path = temp_dirs[0].path().join("to_remove");
        assert!(branch1_path.exists() && branch1_path.is_dir());

        // Remove the directory
        let result = file_manager.remove_directory(dir_path);
        assert!(result.is_ok(), "Should be able to remove empty directory: {:?}", result);

        // Verify it's gone
        assert!(!branch1_path.exists(), "Directory should be removed");
        assert!(!file_manager.directory_exists(dir_path), "Directory should not exist after removal");
    }

    #[test]
    #[serial]
    fn test_rmdir_fails_on_non_empty_directory() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Create a directory with a file in it
        let dir_path = Path::new("non_empty");
        file_manager.create_directory(dir_path).unwrap();
        
        let file_path = Path::new("non_empty/file.txt");
        file_manager.create_file(file_path, b"content").unwrap();

        // Try to remove the non-empty directory - should fail
        let result = file_manager.remove_directory(dir_path);
        assert!(result.is_err(), "Should not be able to remove non-empty directory");

        // Directory should still exist
        let branch1_path = temp_dirs[0].path().join("non_empty");
        assert!(branch1_path.exists() && branch1_path.is_dir(), "Directory should still exist");
    }

    #[test]
    #[serial]
    fn test_unlink_removes_file() {
        let (temp_dirs, file_manager) = setup_test_dirs();

        // Create a file first
        let file_path = Path::new("to_delete.txt");
        file_manager.create_file(file_path, b"content to delete").unwrap();

        // Verify it exists
        let branch1_path = temp_dirs[0].path().join("to_delete.txt");
        assert!(branch1_path.exists() && branch1_path.is_file());
        assert!(file_manager.file_exists(file_path));

        // Remove the file
        let result = file_manager.remove_file(file_path);
        assert!(result.is_ok(), "Should be able to remove file: {:?}", result);

        // Verify it's gone
        assert!(!branch1_path.exists(), "File should be removed");
        assert!(!file_manager.file_exists(file_path), "File should not exist after removal");
    }

    #[test]
    #[serial]
    fn test_unlink_removes_from_all_branches_where_present() {
        let (temp_dirs, _) = setup_test_dirs();

        // Manually create the same file in multiple branches
        let file_content = b"duplicate content";
        std::fs::write(temp_dirs[0].path().join("duplicate.txt"), file_content).unwrap();
        std::fs::write(temp_dirs[1].path().join("duplicate.txt"), file_content).unwrap();

        // Create file manager after files exist
        let branch1 = Arc::new(Branch::new(
            temp_dirs[0].path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp_dirs[1].path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch3 = Arc::new(Branch::new(
            temp_dirs[2].path().to_path_buf(),
            BranchMode::ReadOnly,
        ));

        let branches = vec![branch1, branch2, branch3];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        // Verify file exists in union view
        let file_path = Path::new("duplicate.txt");
        assert!(file_manager.file_exists(file_path));

        // Remove the file - should remove from all writable branches
        let result = file_manager.remove_file(file_path);
        assert!(result.is_ok(), "Should be able to remove file from multiple branches");

        // Verify it's gone from all branches
        assert!(!temp_dirs[0].path().join("duplicate.txt").exists());
        assert!(!temp_dirs[1].path().join("duplicate.txt").exists());
        assert!(!file_manager.file_exists(file_path));
    }
}