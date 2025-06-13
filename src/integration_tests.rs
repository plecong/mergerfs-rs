#[cfg(test)]
mod integration_tests {
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::FirstFoundCreatePolicy;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;
    use serial_test::serial;

    #[test]
    #[serial]
    fn test_end_to_end_file_operations() {
        // Setup: Create three branch directories
        let branch1_dir = TempDir::new().unwrap();
        let branch2_dir = TempDir::new().unwrap();
        let branch3_dir = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(
            branch1_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            branch2_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch3 = Arc::new(Branch::new(
            branch3_dir.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));

        let branches = vec![branch1.clone(), branch2, branch3];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        // Test 1: Create a file - should go to first writable branch (branch1)
        let file_content = b"Hello from mergerfs-rs!";
        let file_path = Path::new("test_file.txt");
        
        let create_result = file_manager.create_file(file_path, file_content);
        assert!(create_result.is_ok(), "Failed to create file: {:?}", create_result);

        // Verify file exists in branch1 only
        let branch1_file_path = branch1.full_path(file_path);
        assert!(branch1_file_path.exists(), "File should exist in branch1");

        // Test 2: Read the file back - should find it and return correct content
        let read_result = file_manager.read_file(file_path);
        assert!(read_result.is_ok(), "Failed to read file: {:?}", read_result);
        
        let read_content = read_result.unwrap();
        assert_eq!(read_content, file_content, "Read content doesn't match written content");

        // Test 3: Check file existence
        assert!(file_manager.file_exists(file_path), "File should be reported as existing");
        assert!(!file_manager.file_exists(Path::new("nonexistent.txt")), "Nonexistent file should not be reported as existing");

        // Test 4: Create nested directory structure
        let nested_path = Path::new("dir1/subdir/nested_file.txt");
        let nested_content = b"Nested file content";
        
        let nested_create_result = file_manager.create_file(nested_path, nested_content);
        assert!(nested_create_result.is_ok(), "Failed to create nested file: {:?}", nested_create_result);

        // Verify nested file can be read back
        let nested_read_result = file_manager.read_file(nested_path);
        assert!(nested_read_result.is_ok(), "Failed to read nested file: {:?}", nested_read_result);
        
        let nested_read_content = nested_read_result.unwrap();
        assert_eq!(nested_read_content, nested_content, "Nested file content doesn't match");

        // Test 5: Verify directory structure was created correctly
        let nested_file_path = branch1.full_path(nested_path);
        assert!(nested_file_path.exists(), "Nested file should exist in branch1");
        assert!(nested_file_path.parent().unwrap().exists(), "Parent directory should exist");
    }

    #[test]
    #[serial]
    fn test_multiple_files_distribution() {
        // Setup: Create two writable branches
        let branch1_dir = TempDir::new().unwrap();
        let branch2_dir = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(
            branch1_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            branch2_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));

        let branches = vec![branch1.clone(), branch2.clone()];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        // Create multiple files - all should go to first branch with FirstFound policy
        let files = vec![
            ("file1.txt", b"Content 1"),
            ("file2.txt", b"Content 2"),
            ("file3.txt", b"Content 3"),
        ];

        for (filename, content) in &files {
            let result = file_manager.create_file(Path::new(filename), *content);
            assert!(result.is_ok(), "Failed to create {}: {:?}", filename, result);
        }

        // Verify all files are in branch1 (first found policy)
        for (filename, _) in &files {
            let path1 = branch1.full_path(Path::new(filename));
            let path2 = branch2.full_path(Path::new(filename));
            
            assert!(path1.exists(), "File {} should exist in branch1", filename);
            assert!(!path2.exists(), "File {} should NOT exist in branch2", filename);
        }

        // Verify we can read all files back with correct content
        for (filename, expected_content) in &files {
            let read_result = file_manager.read_file(Path::new(filename));
            assert!(read_result.is_ok(), "Failed to read {}: {:?}", filename, read_result);
            
            let actual_content = read_result.unwrap();
            assert_eq!(&actual_content, *expected_content, "Content mismatch for {}", filename);
        }
    }

    #[test]
    #[serial]
    fn test_readonly_branch_handling() {
        // Setup: First branch is readonly, second is writable
        let branch1_dir = TempDir::new().unwrap();
        let branch2_dir = TempDir::new().unwrap();

        let branch1 = Arc::new(Branch::new(
            branch1_dir.path().to_path_buf(),
            BranchMode::ReadOnly,
        ));
        let branch2 = Arc::new(Branch::new(
            branch2_dir.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));

        let branches = vec![branch1.clone(), branch2.clone()];
        let policy = Box::new(FirstFoundCreatePolicy);
        let file_manager = FileManager::new(branches, policy);

        // Create file - should skip readonly branch1 and use branch2
        let file_content = b"Should go to branch2";
        let file_path = Path::new("readonly_test.txt");
        
        let create_result = file_manager.create_file(file_path, file_content);
        assert!(create_result.is_ok(), "Failed to create file: {:?}", create_result);

        // Verify file is in branch2, not branch1
        let path1 = branch1.full_path(file_path);
        let path2 = branch2.full_path(file_path);
        
        assert!(!path1.exists(), "File should NOT exist in readonly branch1");
        assert!(path2.exists(), "File should exist in writable branch2");

        // Verify we can read the file back
        let read_result = file_manager.read_file(file_path);
        assert!(read_result.is_ok(), "Failed to read file: {:?}", read_result);
        
        let read_content = read_result.unwrap();
        assert_eq!(read_content, file_content, "Read content doesn't match");
    }
}