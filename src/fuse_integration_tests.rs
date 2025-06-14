#[cfg(test)]
mod fuse_integration_tests {
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::fuse_fs::MergerFS;
    use crate::policy::{FirstFoundCreatePolicy, MostFreeSpaceCreatePolicy, LeastFreeSpaceCreatePolicy};
    use serial_test::serial;
    use std::path::Path;
    use std::sync::Arc;
    use std::time::SystemTime;
    use tempfile::TempDir;

    fn setup_test_mergerfs() -> (Vec<TempDir>, MergerFS) {
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
        let fs = MergerFS::new(file_manager);

        (vec![temp1, temp2, temp3], fs)
    }

    #[test]
    #[serial]
    fn test_end_to_end_fuse_file_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Test 1: Root directory should exist and be accessible
        let root_data = fs.get_inode_data(1);
        assert!(root_data.is_some());
        
        let root = root_data.unwrap();
        assert_eq!(root.path, "/");
        assert_eq!(root.attr.ino, 1);

        // Test 2: Create files through the underlying file manager
        // (simulating what would happen when FUSE create operation is called)
        let files_to_create: Vec<(&str, &[u8])> = vec![
            ("document.txt", b"This is a document"),
            ("data.csv", b"name,age,city\nJohn,30,NYC\nJane,25,LA"),
            ("config.json", b"{\"setting\": \"value\", \"enabled\": true}"),
        ];

        for (filename, content) in &files_to_create {
            let path = Path::new(filename);
            let result = fs.file_manager.create_file(path, content);
            assert!(result.is_ok(), "Failed to create {}: {:?}", filename, result);
            
            // Verify file exists
            assert!(fs.file_manager.file_exists(path), "File {} should exist", filename);
        }

        // Test 3: Read files back (simulating FUSE read operations)
        for (filename, expected_content) in &files_to_create {
            let path = Path::new(filename);
            let read_result = fs.file_manager.read_file(path);
            assert!(read_result.is_ok(), "Failed to read {}: {:?}", filename, read_result);
            
            let actual_content = read_result.unwrap();
            assert_eq!(&actual_content, *expected_content, "Content mismatch for {}", filename);
        }

        // Test 4: File attributes should be correct
        for (filename, content) in &files_to_create {
            let path = Path::new(filename);
            let attr = fs.create_file_attr(path);
            assert!(attr.is_some(), "Should be able to create attributes for {}", filename);
            
            let attr = attr.unwrap();
            assert_eq!(attr.size, content.len() as u64, "Size mismatch for {}", filename);
            assert_eq!(attr.kind, fuser::FileType::RegularFile);
            assert_eq!(attr.nlink, 1);
            assert_eq!(attr.perm, 0o644);
        }
    }

    #[test]
    #[serial]
    fn test_fuse_policy_distribution() {
        let (temp_dirs, fs) = setup_test_mergerfs();

        // Create several files - they should all go to first writable branch with FirstFound policy
        let test_files = vec![
            "policy_test1.txt",
            "policy_test2.txt", 
            "policy_test3.txt",
        ];

        for filename in &test_files {
            let path = Path::new(filename);
            let content = format!("Content for {}", filename);
            let result = fs.file_manager.create_file(path, content.as_bytes());
            assert!(result.is_ok(), "Failed to create {}", filename);
        }

        // Verify all files are in the first branch (index 0)
        let first_branch_path = &temp_dirs[0].path();
        let second_branch_path = &temp_dirs[1].path();

        for filename in &test_files {
            let path_in_first = first_branch_path.join(filename);
            let path_in_second = second_branch_path.join(filename);
            
            assert!(path_in_first.exists(), "File {} should exist in first branch", filename);
            assert!(!path_in_second.exists(), "File {} should NOT exist in second branch", filename);
        }

        // Test that we can still read all files through the union filesystem
        for filename in &test_files {
            let path = Path::new(filename);
            let read_result = fs.file_manager.read_file(path);
            assert!(read_result.is_ok(), "Should be able to read {}", filename);
            
            let content = read_result.unwrap();
            let expected = format!("Content for {}", filename);
            assert_eq!(content, expected.as_bytes());
        }
    }

    #[test]
    #[serial]
    fn test_fuse_nested_directory_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Test creating files in nested directories
        let nested_files = vec![
            "dir1/file1.txt",
            "dir1/subdir/file2.txt",
            "dir2/another_subdir/deep/file3.txt",
        ];

        for file_path in &nested_files {
            let path = Path::new(file_path);
            let content = format!("Content for {}", file_path);
            let result = fs.file_manager.create_file(path, content.as_bytes());
            assert!(result.is_ok(), "Failed to create nested file {}: {:?}", file_path, result);
            
            // Verify file exists
            assert!(fs.file_manager.file_exists(path), "Nested file {} should exist", file_path);
        }

        // Test reading nested files
        for file_path in &nested_files {
            let path = Path::new(file_path);
            let read_result = fs.file_manager.read_file(path);
            assert!(read_result.is_ok(), "Failed to read nested file {}: {:?}", file_path, read_result);
            
            let content = read_result.unwrap();
            let expected = format!("Content for {}", file_path);
            assert_eq!(content, expected.as_bytes(), "Content mismatch for nested file {}", file_path);
        }

        // Test file attributes for nested files
        for file_path in &nested_files {
            let path = Path::new(file_path);
            let attr = fs.create_file_attr(path);
            assert!(attr.is_some(), "Should be able to create attributes for nested file {}", file_path);
            
            let attr = attr.unwrap();
            assert_eq!(attr.kind, fuser::FileType::RegularFile);
            assert!(attr.size > 0, "Nested file {} should have non-zero size", file_path);
        }
    }

    #[test]
    #[serial]
    fn test_fuse_readonly_branch_behavior() {
        let (temp_dirs, fs) = setup_test_mergerfs();

        // Manually create a file in the readonly branch (third branch, index 2)
        let readonly_file = "readonly_existing.txt";
        let readonly_content = b"This file exists in readonly branch";
        let readonly_branch_path = temp_dirs[2].path().join(readonly_file);
        
        std::fs::write(&readonly_branch_path, readonly_content).unwrap();

        // Verify the file can be read through the union filesystem
        let path = Path::new(readonly_file);
        assert!(fs.file_manager.file_exists(path), "File in readonly branch should be visible");
        
        let read_result = fs.file_manager.read_file(path);
        assert!(read_result.is_ok(), "Should be able to read file from readonly branch");
        
        let content = read_result.unwrap();
        assert_eq!(content, readonly_content, "Content from readonly branch should match");

        // Test that we can create attributes for the readonly file
        let attr = fs.create_file_attr(path);
        assert!(attr.is_some(), "Should be able to create attributes for readonly file");
        
        let attr = attr.unwrap();
        assert_eq!(attr.size, readonly_content.len() as u64);
        assert_eq!(attr.kind, fuser::FileType::RegularFile);

        // Verify new files still go to writable branches
        let new_file = "new_file.txt";
        let new_content = b"This should go to writable branch";
        let new_path = Path::new(new_file);
        
        let create_result = fs.file_manager.create_file(new_path, new_content);
        assert!(create_result.is_ok(), "Should be able to create new file");
        
        // Check that new file is NOT in readonly branch
        let new_file_in_readonly = temp_dirs[2].path().join(new_file);
        assert!(!new_file_in_readonly.exists(), "New file should NOT be in readonly branch");
        
        // Check that new file IS in first writable branch
        let new_file_in_writable = temp_dirs[0].path().join(new_file);
        assert!(new_file_in_writable.exists(), "New file should be in first writable branch");
    }

    #[test]
    #[serial]
    fn test_fuse_inode_management() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create several files and verify inode management
        let files = vec!["inode1.txt", "inode2.txt", "inode3.txt"];
        
        for filename in &files {
            let path = Path::new(filename);
            let content = format!("Inode test for {}", filename);
            fs.file_manager.create_file(path, content.as_bytes()).unwrap();
        }

        // Test inode allocation
        let ino1 = fs.allocate_inode();
        let ino2 = fs.allocate_inode();
        let ino3 = fs.allocate_inode();
        
        // Inodes should be unique and sequential (starting from 2, since 1 is root)
        assert!(ino1 >= 2);
        assert_eq!(ino2, ino1 + 1);
        assert_eq!(ino3, ino2 + 1);

        // Test path to inode lookup for root
        let root_ino = fs.path_to_inode("/");
        assert_eq!(root_ino, Some(1), "Root should always have inode 1");

        // Test getting inode data
        let root_data = fs.get_inode_data(1);
        assert!(root_data.is_some(), "Root inode data should exist");
        
        let root = root_data.unwrap();
        assert_eq!(root.path, "/");
        assert_eq!(root.attr.kind, fuser::FileType::Directory);

        // Test non-existent inode
        let missing_data = fs.get_inode_data(9999);
        assert!(missing_data.is_none(), "Non-existent inode should return None");
    }

    #[test]
    #[serial]
    fn test_fuse_large_file_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create a larger file to test handling of bigger content
        let large_content = "A".repeat(10000); // 10KB of 'A's
        let large_file = "large_file.txt";
        let path = Path::new(large_file);
        
        let create_result = fs.file_manager.create_file(path, large_content.as_bytes());
        assert!(create_result.is_ok(), "Should be able to create large file");

        // Read the large file back
        let read_result = fs.file_manager.read_file(path);
        assert!(read_result.is_ok(), "Should be able to read large file");
        
        let read_content = read_result.unwrap();
        assert_eq!(read_content.len(), 10000, "Large file should maintain size");
        assert_eq!(read_content, large_content.as_bytes(), "Large file content should match");

        // Test file attributes for large file
        let attr = fs.create_file_attr(path);
        assert!(attr.is_some(), "Should be able to create attributes for large file");
        
        let attr = attr.unwrap();
        assert_eq!(attr.size, 10000, "Large file size should be correct");
        assert_eq!(attr.blocks, (10000 + 511) / 512, "Block count should be calculated correctly");

        // Test partial reads (simulating FUSE read with offset)
        let partial_start = 1000;
        let partial_length = 500;
        let partial_content = &read_content[partial_start..partial_start + partial_length];
        
        // All should be 'A's
        assert_eq!(partial_content.len(), partial_length);
        assert!(partial_content.iter().all(|&b| b == b'A'), "Partial content should be all A's");
    }

    #[test]
    #[serial]
    fn test_fuse_directory_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Test directory creation
        let dir_path = Path::new("test_directory");
        let create_result = fs.file_manager.create_directory(dir_path);
        assert!(create_result.is_ok(), "Should be able to create directory");
        assert!(fs.file_manager.directory_exists(dir_path), "Directory should exist after creation");

        // Test nested directory creation
        let nested_path = Path::new("parent/child/grandchild");
        let nested_result = fs.file_manager.create_directory(nested_path);
        assert!(nested_result.is_ok(), "Should be able to create nested directories");
        assert!(fs.file_manager.directory_exists(nested_path), "Nested directory should exist");

        // Test directory listing
        let list_result = fs.file_manager.list_directory(Path::new("."));
        assert!(list_result.is_ok(), "Should be able to list root directory");
        
        let entries = list_result.unwrap();
        assert!(entries.contains(&"test_directory".to_string()), "Should list created directory");
        assert!(entries.contains(&"parent".to_string()), "Should list parent directory");

        // Test directory removal
        let remove_result = fs.file_manager.remove_directory(dir_path);
        assert!(remove_result.is_ok(), "Should be able to remove empty directory");
        assert!(!fs.file_manager.directory_exists(dir_path), "Directory should not exist after removal");
    }

    #[test]
    #[serial]
    fn test_fuse_file_deletion() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create a file first
        let file_path = Path::new("file_to_delete.txt");
        let content = b"This file will be deleted";
        fs.file_manager.create_file(file_path, content).unwrap();
        assert!(fs.file_manager.file_exists(file_path), "File should exist after creation");

        // Delete the file
        let delete_result = fs.file_manager.remove_file(file_path);
        assert!(delete_result.is_ok(), "Should be able to delete file: {:?}", delete_result);
        assert!(!fs.file_manager.file_exists(file_path), "File should not exist after deletion");
    }

    #[test]
    #[serial]
    fn test_fuse_directory_union_listing() {
        let (temp_dirs, fs) = setup_test_mergerfs();

        // Create different files and directories in different branches manually
        let branch1_path = &temp_dirs[0].path();
        let branch2_path = &temp_dirs[1].path();

        // Create items in branch1
        std::fs::write(branch1_path.join("file1.txt"), "content1").unwrap();
        std::fs::create_dir(branch1_path.join("dir1")).unwrap();
        std::fs::write(branch1_path.join("shared.txt"), "from branch1").unwrap();

        // Create items in branch2  
        std::fs::write(branch2_path.join("file2.txt"), "content2").unwrap();
        std::fs::create_dir(branch2_path.join("dir2")).unwrap();
        std::fs::write(branch2_path.join("shared.txt"), "from branch2").unwrap();

        // List directory contents - should show union
        let list_result = fs.file_manager.list_directory(Path::new("."));
        assert!(list_result.is_ok(), "Should be able to list directory");

        let entries = list_result.unwrap();
        
        // Should contain items from both branches
        assert!(entries.contains(&"file1.txt".to_string()), "Should contain file1.txt from branch1");
        assert!(entries.contains(&"file2.txt".to_string()), "Should contain file2.txt from branch2");
        assert!(entries.contains(&"dir1".to_string()), "Should contain dir1 from branch1");
        assert!(entries.contains(&"dir2".to_string()), "Should contain dir2 from branch2");
        
        // Should only contain one instance of shared.txt (union deduplication)
        let shared_count = entries.iter().filter(|&name| name == "shared.txt").count();
        assert_eq!(shared_count, 1, "Should only show one instance of shared.txt");
    }

    #[test]
    #[serial]
    fn test_fuse_mixed_file_directory_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create a complex directory structure with files
        fs.file_manager.create_directory(Path::new("project")).unwrap();
        fs.file_manager.create_directory(Path::new("project/src")).unwrap();
        fs.file_manager.create_directory(Path::new("project/docs")).unwrap();
        
        // Add files to the directories
        fs.file_manager.create_file(Path::new("project/README.md"), b"# Project README").unwrap();
        fs.file_manager.create_file(Path::new("project/src/main.rs"), b"fn main() {}").unwrap();
        fs.file_manager.create_file(Path::new("project/docs/guide.md"), b"# Guide").unwrap();

        // Test listing at different levels
        let root_entries = fs.file_manager.list_directory(Path::new(".")).unwrap();
        assert!(root_entries.contains(&"project".to_string()));

        let project_entries = fs.file_manager.list_directory(Path::new("project")).unwrap();
        assert!(project_entries.contains(&"README.md".to_string()));
        assert!(project_entries.contains(&"src".to_string()));
        assert!(project_entries.contains(&"docs".to_string()));

        let src_entries = fs.file_manager.list_directory(Path::new("project/src")).unwrap();
        assert!(src_entries.contains(&"main.rs".to_string()));

        // Test file operations within directories
        let readme_content = fs.file_manager.read_file(Path::new("project/README.md")).unwrap();
        assert_eq!(readme_content, b"# Project README");

        // Test file deletion within directories
        fs.file_manager.remove_file(Path::new("project/src/main.rs")).unwrap();
        assert!(!fs.file_manager.file_exists(Path::new("project/src/main.rs")));
        
        let updated_src_entries = fs.file_manager.list_directory(Path::new("project/src")).unwrap();
        assert!(!updated_src_entries.contains(&"main.rs".to_string()));

        // Test directory removal (should fail for non-empty directory)
        let remove_project_result = fs.file_manager.remove_directory(Path::new("project"));
        assert!(remove_project_result.is_err(), "Should not be able to remove non-empty directory");

        // Test removing empty directory after cleanup
        fs.file_manager.remove_file(Path::new("project/README.md")).unwrap();
        fs.file_manager.remove_file(Path::new("project/docs/guide.md")).unwrap();
        fs.file_manager.remove_directory(Path::new("project/src")).unwrap();
        fs.file_manager.remove_directory(Path::new("project/docs")).unwrap();
        
        let final_remove_result = fs.file_manager.remove_directory(Path::new("project"));
        assert!(final_remove_result.is_ok(), "Should be able to remove empty directory");
        assert!(!fs.file_manager.directory_exists(Path::new("project")));
    }

    #[test]
    #[serial]
    fn test_fuse_metadata_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create a test file first
        let file_path = Path::new("metadata_test.txt");
        let content = b"File for metadata testing";
        fs.file_manager.create_file(file_path, content).unwrap();
        assert!(fs.file_manager.file_exists(file_path));

        // Test chmod operation
        let chmod_result = fs.metadata_manager.chmod(file_path, 0o755);
        assert!(chmod_result.is_ok(), "chmod should succeed: {:?}", chmod_result);

        // Test getting metadata
        let metadata = fs.metadata_manager.get_metadata(file_path);
        assert!(metadata.is_ok(), "should be able to get metadata");
        
        let meta = metadata.unwrap();
        assert_eq!(meta.size, content.len() as u64);
        
        #[cfg(unix)]
        {
            // On Unix, verify the mode was actually changed
            assert_eq!(meta.mode & 0o777, 0o755);
        }

        // Test chown (setting to current user should always work)
        #[cfg(unix)]
        {
            let current_uid = 1000; // Default uid for tests
            let current_gid = 1000; // Default gid for tests
            
            let chown_result = fs.metadata_manager.chown(file_path, current_uid, current_gid);
            assert!(chown_result.is_ok(), "chown to current user should succeed");
        }

        // Test utimens
        use std::time::{Duration, SystemTime};
        let past_time = SystemTime::now() - Duration::from_secs(3600); // 1 hour ago
        let utimens_result = fs.metadata_manager.utimens(file_path, past_time, past_time);
        assert!(utimens_result.is_ok(), "utimens should succeed: {:?}", utimens_result);
    }

    #[test]
    #[serial]
    fn test_fuse_metadata_cross_branch_consistency() {
        let (temp_dirs, fs) = setup_test_mergerfs();

        // Create the same file in multiple branches manually
        let file_content = b"Cross-branch metadata test";
        std::fs::write(temp_dirs[0].path().join("cross.txt"), file_content).unwrap();
        std::fs::write(temp_dirs[1].path().join("cross.txt"), file_content).unwrap();

        let file_path = Path::new("cross.txt");
        assert!(fs.file_manager.file_exists(file_path));

        // Change permissions - should affect all branches where file exists
        let chmod_result = fs.metadata_manager.chmod(file_path, 0o644);
        assert!(chmod_result.is_ok(), "chmod should succeed on cross-branch file");

        // Verify permissions changed in both branches
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            
            let metadata1 = std::fs::metadata(temp_dirs[0].path().join("cross.txt")).unwrap();
            let metadata2 = std::fs::metadata(temp_dirs[1].path().join("cross.txt")).unwrap();
            
            assert_eq!(metadata1.permissions().mode() & 0o777, 0o644);
            assert_eq!(metadata2.permissions().mode() & 0o777, 0o644);
        }

        // Test timestamp changes across branches
        use std::time::{Duration, SystemTime};
        let test_time = SystemTime::now() - Duration::from_secs(1800); // 30 minutes ago
        
        let utimens_result = fs.metadata_manager.utimens(file_path, test_time, test_time);
        assert!(utimens_result.is_ok(), "utimens should succeed on cross-branch file");

        // Verify timestamps changed in both branches
        let metadata1 = std::fs::metadata(temp_dirs[0].path().join("cross.txt")).unwrap();
        let metadata2 = std::fs::metadata(temp_dirs[1].path().join("cross.txt")).unwrap();
        
        // Times should be close (within a few seconds)
        let mtime1 = metadata1.modified().unwrap();
        let mtime2 = metadata2.modified().unwrap();
        let time_diff = mtime1.duration_since(mtime2).unwrap_or(mtime2.duration_since(mtime1).unwrap());
        assert!(time_diff < Duration::from_secs(5), "Modification times should be synchronized");
    }

    #[test]
    #[serial]
    fn test_fuse_metadata_readonly_branch_handling() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        // Create file in all branches
        let file_content = b"Readonly test content";
        std::fs::write(temp1.path().join("readonly_test.txt"), file_content).unwrap();
        std::fs::write(temp2.path().join("readonly_test.txt"), file_content).unwrap();
        std::fs::write(temp3.path().join("readonly_test.txt"), file_content).unwrap();

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
        let fs = MergerFS::new(file_manager);

        let file_path = Path::new("readonly_test.txt");
        
        // Metadata operations should succeed on writable branches only
        let chmod_result = fs.metadata_manager.chmod(file_path, 0o600);
        assert!(chmod_result.is_ok(), "chmod should succeed on writable branches");

        // Verify changes were applied to writable branches only
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            
            let metadata1 = std::fs::metadata(temp1.path().join("readonly_test.txt")).unwrap();
            let metadata2 = std::fs::metadata(temp2.path().join("readonly_test.txt")).unwrap();
            let metadata3 = std::fs::metadata(temp3.path().join("readonly_test.txt")).unwrap();
            
            // Writable branches should have new permissions
            assert_eq!(metadata1.permissions().mode() & 0o777, 0o600);
            assert_eq!(metadata2.permissions().mode() & 0o777, 0o600);
            
            // Readonly branch should keep original permissions (likely 0o644)
            assert_ne!(metadata3.permissions().mode() & 0o777, 0o600);
        }
    }

    #[test]
    #[serial]
    fn test_fuse_metadata_directory_operations() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Create a test directory
        let dir_path = Path::new("metadata_dir");
        fs.file_manager.create_directory(dir_path).unwrap();
        assert!(fs.file_manager.directory_exists(dir_path));

        // Test chmod on directory
        let chmod_result = fs.metadata_manager.chmod(dir_path, 0o755);
        assert!(chmod_result.is_ok(), "chmod should work on directories");

        // Test directory metadata retrieval
        let metadata = fs.metadata_manager.get_metadata(dir_path);
        assert!(metadata.is_ok(), "should be able to get directory metadata");
        
        let meta = metadata.unwrap();
        #[cfg(unix)]
        {
            assert_eq!(meta.mode & 0o777, 0o755);
        }

        // Test timestamp changes on directory
        use std::time::{Duration, SystemTime};
        let dir_time = SystemTime::now() - Duration::from_secs(900); // 15 minutes ago
        
        let utimens_result = fs.metadata_manager.utimens(dir_path, dir_time, dir_time);
        assert!(utimens_result.is_ok(), "utimens should work on directories");
    }

    #[test]
    #[serial]
    fn test_fuse_metadata_error_handling() {
        let (_temp_dirs, fs) = setup_test_mergerfs();

        // Test operations on nonexistent file
        let missing_path = Path::new("nonexistent.txt");
        
        let chmod_result = fs.metadata_manager.chmod(missing_path, 0o644);
        assert!(chmod_result.is_err(), "chmod should fail on nonexistent file");
        
        let chown_result = fs.metadata_manager.chown(missing_path, 1000, 1000);
        assert!(chown_result.is_err(), "chown should fail on nonexistent file");
        
        let utimens_result = fs.metadata_manager.utimens(
            missing_path, 
            SystemTime::now(), 
            SystemTime::now()
        );
        assert!(utimens_result.is_err(), "utimens should fail on nonexistent file");
        
        let metadata_result = fs.metadata_manager.get_metadata(missing_path);
        assert!(metadata_result.is_err(), "get_metadata should fail on nonexistent file");
    }
    
    #[test]
    #[serial]
    fn test_fuse_most_free_space_policy() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        // Create different amounts of content to simulate different free space
        // temp1: small file (more free space)
        std::fs::write(temp1.path().join("existing_small.txt"), "small").unwrap();
        
        // temp2: large file (less free space)
        std::fs::write(temp2.path().join("existing_large.txt"), "x".repeat(2000)).unwrap();
        
        // temp3: medium file
        std::fs::write(temp3.path().join("existing_medium.txt"), "y".repeat(500)).unwrap();

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
            BranchMode::ReadWrite,
        ));

        let branches = vec![branch2.clone(), branch3.clone(), branch1.clone()]; // Put most used first
        let policy = Box::new(MostFreeSpaceCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        let fs = MergerFS::new(file_manager);

        // Create several test files - they should go to the branch with most free space (temp1)
        let test_files = vec!["mfs_test1.txt", "mfs_test2.txt", "mfs_test3.txt"];
        
        for filename in &test_files {
            let path = Path::new(filename);
            let content = format!("MFS policy test content for {}", filename);
            let result = fs.file_manager.create_file(path, content.as_bytes());
            assert!(result.is_ok(), "Failed to create {} with MFS policy: {:?}", filename, result);
            
            // Verify file exists
            assert!(fs.file_manager.file_exists(path), "File {} should exist after MFS creation", filename);
        }

        // Verify that files were created in temp1 (most free space)
        for filename in &test_files {
            let path_in_temp1 = temp1.path().join(filename);
            let path_in_temp2 = temp2.path().join(filename);
            let path_in_temp3 = temp3.path().join(filename);
            
            assert!(path_in_temp1.exists(), "File {} should exist in temp1 (most free space)", filename);
            assert!(!path_in_temp2.exists(), "File {} should NOT exist in temp2 (less free space)", filename);
            assert!(!path_in_temp3.exists(), "File {} should NOT exist in temp3 (medium space)", filename);
        }

        // Test that we can still read all files through the union filesystem
        for filename in &test_files {
            let path = Path::new(filename);
            let read_result = fs.file_manager.read_file(path);
            assert!(read_result.is_ok(), "Should be able to read {} via MFS policy", filename);
            
            let content = read_result.unwrap();
            let expected = format!("MFS policy test content for {}", filename);
            assert_eq!(content, expected.as_bytes());
        }
    }
    
    #[test]
    #[serial]
    fn test_fuse_policy_comparison() {
        // Test that FF and MFS policies behave differently
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();

        // Create different space usage
        std::fs::write(temp1.path().join("big_file.txt"), "x".repeat(5000)).unwrap(); // Less free space
        std::fs::write(temp2.path().join("small_file.txt"), "small").unwrap(); // More free space

        let branch1 = Arc::new(Branch::new(
            temp1.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));
        let branch2 = Arc::new(Branch::new(
            temp2.path().to_path_buf(),
            BranchMode::ReadWrite,
        ));

        // Test FirstFound policy (should use first branch)
        let ff_branches = vec![branch1.clone(), branch2.clone()];
        let ff_policy = Box::new(FirstFoundCreatePolicy);
        let ff_file_manager = FileManager::new(ff_branches, ff_policy);
        let ff_fs = MergerFS::new(ff_file_manager);
        
        ff_fs.file_manager.create_file(Path::new("ff_test.txt"), b"FF test").unwrap();
        
        // Test MostFreeSpace policy (should use second branch with more space)
        let mfs_branches = vec![branch1.clone(), branch2.clone()];
        let mfs_policy = Box::new(MostFreeSpaceCreatePolicy);
        let mfs_file_manager = FileManager::new(mfs_branches, mfs_policy);
        let mfs_fs = MergerFS::new(mfs_file_manager);
        
        mfs_fs.file_manager.create_file(Path::new("mfs_test.txt"), b"MFS test").unwrap();
        
        // Verify FF file went to first branch
        assert!(temp1.path().join("ff_test.txt").exists(), "FF policy should use first branch");
        assert!(!temp2.path().join("ff_test.txt").exists(), "FF policy should not use second branch");
        
        // Verify MFS file went to second branch (more free space)
        assert!(temp2.path().join("mfs_test.txt").exists(), "MFS policy should use branch with more free space");
        assert!(!temp1.path().join("mfs_test.txt").exists(), "MFS policy should not use branch with less free space");
    }
    
    #[test]
    #[serial]
    fn test_fuse_least_free_space_policy() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        // Create different amounts of content to simulate different free space
        // temp1: small file (more free space)
        std::fs::write(temp1.path().join("existing_small.txt"), "small").unwrap();
        
        // temp2: large file (less free space) - LFS should pick this one
        std::fs::write(temp2.path().join("existing_large.txt"), "x".repeat(3000)).unwrap();
        
        // temp3: medium file
        std::fs::write(temp3.path().join("existing_medium.txt"), "y".repeat(1000)).unwrap();

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
            BranchMode::ReadWrite,
        ));

        let branches = vec![branch1.clone(), branch3.clone(), branch2.clone()]; // Put most free space first
        let policy = Box::new(LeastFreeSpaceCreatePolicy);
        let file_manager = FileManager::new(branches, policy);
        let fs = MergerFS::new(file_manager);

        // Create several test files - they should go to the branch with least free space (temp2)
        let test_files = vec!["lfs_test1.txt", "lfs_test2.txt", "lfs_test3.txt"];
        
        for filename in &test_files {
            let path = Path::new(filename);
            let content = format!("LFS policy test content for {}", filename);
            let result = fs.file_manager.create_file(path, content.as_bytes());
            assert!(result.is_ok(), "Failed to create {} with LFS policy: {:?}", filename, result);
            
            // Verify file exists
            assert!(fs.file_manager.file_exists(path), "File {} should exist after LFS creation", filename);
        }

        // Verify that files were created in temp2 (least free space)
        for filename in &test_files {
            let path_in_temp1 = temp1.path().join(filename);
            let path_in_temp2 = temp2.path().join(filename);
            let path_in_temp3 = temp3.path().join(filename);
            
            assert!(!path_in_temp1.exists(), "File {} should NOT exist in temp1 (most free space)", filename);
            assert!(path_in_temp2.exists(), "File {} should exist in temp2 (least free space)", filename);
            assert!(!path_in_temp3.exists(), "File {} should NOT exist in temp3 (medium space)", filename);
        }

        // Test that we can still read all files through the union filesystem
        for filename in &test_files {
            let path = Path::new(filename);
            let read_result = fs.file_manager.read_file(path);
            assert!(read_result.is_ok(), "Should be able to read {} via LFS policy", filename);
            
            let content = read_result.unwrap();
            let expected = format!("LFS policy test content for {}", filename);
            assert_eq!(content, expected.as_bytes());
        }
    }
    
    #[test]
    #[serial]
    fn test_fuse_all_three_policies_comparison() {
        // Test that FF, MFS, and LFS policies all behave differently
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        let temp3 = TempDir::new().unwrap();

        // Create different space usage patterns
        std::fs::write(temp1.path().join("small.txt"), "tiny").unwrap(); // Most free space
        std::fs::write(temp2.path().join("medium.txt"), "x".repeat(1000)).unwrap(); // Medium space
        std::fs::write(temp3.path().join("large.txt"), "y".repeat(5000)).unwrap(); // Least free space

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
            BranchMode::ReadWrite,
        ));

        // Test FirstFound policy (should use first branch - temp1)
        let ff_branches = vec![branch1.clone(), branch2.clone(), branch3.clone()];
        let ff_policy = Box::new(FirstFoundCreatePolicy);
        let ff_file_manager = FileManager::new(ff_branches, ff_policy);
        let ff_fs = MergerFS::new(ff_file_manager);
        
        ff_fs.file_manager.create_file(Path::new("ff_test.txt"), b"FF test").unwrap();
        
        // Test MostFreeSpace policy (should use temp1 - most free space)
        let mfs_branches = vec![branch1.clone(), branch2.clone(), branch3.clone()];
        let mfs_policy = Box::new(MostFreeSpaceCreatePolicy);
        let mfs_file_manager = FileManager::new(mfs_branches, mfs_policy);
        let mfs_fs = MergerFS::new(mfs_file_manager);
        
        mfs_fs.file_manager.create_file(Path::new("mfs_test.txt"), b"MFS test").unwrap();
        
        // Test LeastFreeSpace policy (should use temp3 - least free space)
        let lfs_branches = vec![branch1.clone(), branch2.clone(), branch3.clone()];
        let lfs_policy = Box::new(LeastFreeSpaceCreatePolicy);
        let lfs_file_manager = FileManager::new(lfs_branches, lfs_policy);
        let lfs_fs = MergerFS::new(lfs_file_manager);
        
        lfs_fs.file_manager.create_file(Path::new("lfs_test.txt"), b"LFS test").unwrap();
        
        // Verify FF and MFS both went to temp1 (first branch and most free space)
        assert!(temp1.path().join("ff_test.txt").exists(), "FF policy should use first branch (temp1)");
        assert!(temp1.path().join("mfs_test.txt").exists(), "MFS policy should use branch with most free space (temp1)");
        
        // Verify LFS went to temp3 (least free space)
        assert!(temp3.path().join("lfs_test.txt").exists(), "LFS policy should use branch with least free space (temp3)");
        
        // Verify the other branches don't have the wrong files
        assert!(!temp2.path().join("ff_test.txt").exists(), "FF should not use temp2");
        assert!(!temp3.path().join("ff_test.txt").exists(), "FF should not use temp3");
        assert!(!temp2.path().join("mfs_test.txt").exists(), "MFS should not use temp2");
        assert!(!temp3.path().join("mfs_test.txt").exists(), "MFS should not use temp3");
        assert!(!temp1.path().join("lfs_test.txt").exists(), "LFS should not use temp1");
        assert!(!temp2.path().join("lfs_test.txt").exists(), "LFS should not use temp2");
    }

    #[test]
    #[serial]
    fn test_fuse_file_handle_tracking() {
        let (_temp_dirs, mut fs) = setup_test_mergerfs();
        
        // Create a test file
        let test_path = Path::new("/test_handles.txt");
        let test_content = b"Test file for handle tracking";
        fs.file_manager.create_file(test_path, test_content).unwrap();
        
        // Simulate opening the file multiple times
        let ino = 2; // Assuming this is the inode for our file
        let flags = 0; // O_RDONLY
        
        // Track file handles
        let initial_count = fs.file_handle_manager.get_handle_count();
        assert_eq!(initial_count, 0, "Should start with no file handles");
        
        // Open file first time
        let fh1 = fs.file_handle_manager.create_handle(
            ino,
            test_path.to_path_buf(),
            flags,
            Some(0) // Branch 0
        );
        assert_eq!(fs.file_handle_manager.get_handle_count(), 1);
        
        // Open file second time
        let fh2 = fs.file_handle_manager.create_handle(
            ino,
            test_path.to_path_buf(),
            flags,
            Some(0) // Same branch
        );
        assert_ne!(fh1, fh2, "Each open should get unique handle");
        assert_eq!(fs.file_handle_manager.get_handle_count(), 2);
        
        // Verify handles contain correct information
        let handle1 = fs.file_handle_manager.get_handle(fh1).unwrap();
        assert_eq!(handle1.ino, ino);
        assert_eq!(handle1.path, test_path);
        assert_eq!(handle1.branch_idx, Some(0));
        
        // Release first handle
        fs.file_handle_manager.remove_handle(fh1);
        assert_eq!(fs.file_handle_manager.get_handle_count(), 1);
        assert!(fs.file_handle_manager.get_handle(fh1).is_none());
        
        // Second handle should still be valid
        assert!(fs.file_handle_manager.get_handle(fh2).is_some());
        
        // Release second handle
        fs.file_handle_manager.remove_handle(fh2);
        assert_eq!(fs.file_handle_manager.get_handle_count(), 0);
    }

    #[test]
    #[serial]
    fn test_fuse_file_handle_branch_affinity() {
        let (_temp_dirs, mut fs) = setup_test_mergerfs();
        
        // Create a file that exists in multiple branches
        let test_path = Path::new("/multi_branch.txt");
        let content1 = b"Content in branch 1";
        let content2 = b"Different content in branch 2";
        
        // Manually create file in both branches
        let branch1 = &fs.file_manager.branches[0];
        let branch2 = &fs.file_manager.branches[1];
        
        std::fs::write(branch1.full_path(test_path), content1).unwrap();
        std::fs::write(branch2.full_path(test_path), content2).unwrap();
        
        // Open from specific branches
        let fh_branch1 = fs.file_handle_manager.create_handle(
            2,
            test_path.to_path_buf(),
            0,
            Some(0) // Branch 0
        );
        
        let fh_branch2 = fs.file_handle_manager.create_handle(
            2,
            test_path.to_path_buf(),
            0,
            Some(1) // Branch 1
        );
        
        // Verify handles track their branches
        let handle1 = fs.file_handle_manager.get_handle(fh_branch1).unwrap();
        assert_eq!(handle1.branch_idx, Some(0));
        
        let handle2 = fs.file_handle_manager.get_handle(fh_branch2).unwrap();
        assert_eq!(handle2.branch_idx, Some(1));
        
        // Clean up
        fs.file_handle_manager.remove_handle(fh_branch1);
        fs.file_handle_manager.remove_handle(fh_branch2);
    }
}