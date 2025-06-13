use super::*;
use crate::branch::{Branch, BranchMode};
use crate::policy::{FirstFoundSearchPolicy, AllActionPolicy, ExistingPathAllActionPolicy};
use tempfile::TempDir;
use std::fs;
use std::sync::Arc;
use std::path::Path;

fn create_test_manager_with_policies() -> (Vec<TempDir>, XattrManager) {
    let temp1 = TempDir::new().unwrap();
    let temp2 = TempDir::new().unwrap();
    let temp3 = TempDir::new().unwrap();
    
    let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
    let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
    let branch3 = Arc::new(Branch::new(temp3.path().to_path_buf(), BranchMode::ReadOnly));
    
    let branches = vec![branch1, branch2, branch3];
    
    let manager = XattrManager::new(
        branches,
        Box::new(FirstFoundSearchPolicy),
        Box::new(AllActionPolicy::new()),
        Box::new(FirstFoundSearchPolicy),
        Box::new(AllActionPolicy::new()),
    );
    
    (vec![temp1, temp2, temp3], manager)
}

#[test]
fn test_xattr_create_replace_flags() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create test file in first branch
    let test_path = Path::new("test.txt");
    let full_path = manager.branches[0].full_path(test_path);
    fs::write(&full_path, b"test content").unwrap();
    
    let attr_name = "user.test_attr";
    let attr_value1 = b"value1";
    let attr_value2 = b"value2";
    
    // Set initial attribute
    manager.set_xattr(test_path, attr_name, attr_value1, XattrFlags::None).unwrap();
    
    // Try to create when it already exists - should fail
    let result = manager.set_xattr(test_path, attr_name, attr_value2, XattrFlags::Create);
    assert!(matches!(result, Err(XattrError::InvalidArgument)));
    
    // Verify value hasn't changed
    let value = manager.get_xattr(test_path, attr_name).unwrap();
    assert_eq!(value, attr_value1);
    
    // Replace should work
    manager.set_xattr(test_path, attr_name, attr_value2, XattrFlags::Replace).unwrap();
    let value = manager.get_xattr(test_path, attr_name).unwrap();
    assert_eq!(value, attr_value2);
    
    // Try to replace non-existent attribute - should fail
    let result = manager.set_xattr(test_path, "user.nonexistent", b"data", XattrFlags::Replace);
    assert!(matches!(result, Err(XattrError::NotFound)));
}

#[test]
fn test_xattr_all_action_policy() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create test file in multiple branches
    let test_path = Path::new("test.txt");
    for i in 0..2 {  // Only writable branches
        let full_path = manager.branches[i].full_path(test_path);
        fs::write(&full_path, format!("content{}", i)).unwrap();
    }
    
    // Set xattr - should set on all writable branches
    let attr_name = "user.test_attr";
    let attr_value = b"shared value";
    manager.set_xattr(test_path, attr_name, attr_value, XattrFlags::None).unwrap();
    
    // Verify xattr exists on both writable branches
    for i in 0..2 {
        let full_path = manager.branches[i].full_path(test_path);
        let value = xattr::get(&full_path, attr_name).unwrap().unwrap();
        assert_eq!(value, attr_value);
    }
    
    // Verify readonly branch doesn't have it
    let readonly_path = manager.branches[2].full_path(test_path);
    assert!(!readonly_path.exists());
}

#[test]
fn test_xattr_nonexistent_file() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    let test_path = Path::new("nonexistent.txt");
    
    // All operations should fail with NotFound
    assert!(matches!(
        manager.get_xattr(test_path, "user.attr"),
        Err(XattrError::NotFound)
    ));
    
    assert!(matches!(
        manager.set_xattr(test_path, "user.attr", b"value", XattrFlags::None),
        Err(XattrError::NotFound)
    ));
    
    assert!(matches!(
        manager.list_xattr(test_path),
        Err(XattrError::NotFound)
    ));
    
    assert!(matches!(
        manager.remove_xattr(test_path, "user.attr"),
        Err(XattrError::NotFound)
    ));
}

#[test]
fn test_xattr_multiple_attributes() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create test file
    let test_path = Path::new("test.txt");
    let full_path = manager.branches[0].full_path(test_path);
    fs::write(&full_path, b"test content").unwrap();
    
    // Set multiple attributes
    let attrs = vec![
        ("user.attr1", b"value1"),
        ("user.attr2", b"value2"),
        ("user.attr3", b"value3"),
    ];
    
    for (name, value) in &attrs {
        manager.set_xattr(test_path, name, *value, XattrFlags::None).unwrap();
    }
    
    // List all attributes
    let listed = manager.list_xattr(test_path).unwrap();
    for (name, _) in &attrs {
        assert!(listed.contains(&name.to_string()));
    }
    
    // Get each attribute
    for (name, expected_value) in &attrs {
        let value = manager.get_xattr(test_path, name).unwrap();
        assert_eq!(value, *expected_value);
    }
    
    // Remove one attribute
    manager.remove_xattr(test_path, "user.attr2").unwrap();
    
    // Verify it's gone
    assert!(matches!(
        manager.get_xattr(test_path, "user.attr2"),
        Err(XattrError::NotFound)
    ));
    
    // Other attributes should still exist
    assert!(manager.get_xattr(test_path, "user.attr1").is_ok());
    assert!(manager.get_xattr(test_path, "user.attr3").is_ok());
}

#[test]
fn test_xattr_policy_rv_mixed_results() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create a custom manager with ExistingPathAllActionPolicy
    let manager = XattrManager::new(
        manager.branches.clone(),
        Box::new(FirstFoundSearchPolicy),
        Box::new(ExistingPathAllActionPolicy::new()),
        Box::new(FirstFoundSearchPolicy),
        Box::new(ExistingPathAllActionPolicy::new()),
    );
    
    // Create test file only in first branch
    let test_path = Path::new("test.txt");
    let full_path = manager.branches[0].full_path(test_path);
    fs::write(&full_path, b"test content").unwrap();
    
    // Set xattr - should only succeed on first branch
    let attr_name = "user.test_attr";
    let attr_value = b"value";
    manager.set_xattr(test_path, attr_name, attr_value, XattrFlags::None).unwrap();
    
    // Verify it only exists on first branch
    let value = xattr::get(&full_path, attr_name).unwrap().unwrap();
    assert_eq!(value, attr_value);
    
    // Second branch shouldn't have the file or attribute
    let full_path2 = manager.branches[1].full_path(test_path);
    assert!(!full_path2.exists());
}

#[test]
fn test_xattr_large_values() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create test file
    let test_path = Path::new("test.txt");
    let full_path = manager.branches[0].full_path(test_path);
    fs::write(&full_path, b"test content").unwrap();
    
    // Test with moderately large attribute value (1KB)
    let large_value = vec![0xAB; 1024];
    let attr_name = "user.large_attr";
    
    // Try to set the xattr, but handle disk space errors gracefully
    match manager.set_xattr(test_path, attr_name, &large_value, XattrFlags::None) {
        Ok(_) => {
            let retrieved = manager.get_xattr(test_path, attr_name).unwrap();
            assert_eq!(retrieved.len(), large_value.len());
            assert_eq!(retrieved, large_value);
        }
        Err(XattrError::Io(e)) if e.kind() == std::io::ErrorKind::StorageFull => {
            // Skip test if no disk space
            eprintln!("Skipping large xattr test due to disk space");
        }
        Err(e) => panic!("Unexpected error: {:?}", e),
    }
}

#[test]
fn test_xattr_empty_value() {
    let (_temps, manager) = create_test_manager_with_policies();
    
    // Create test file
    let test_path = Path::new("test.txt");
    let full_path = manager.branches[0].full_path(test_path);
    fs::write(&full_path, b"test content").unwrap();
    
    // Set empty attribute value
    let attr_name = "user.empty_attr";
    manager.set_xattr(test_path, attr_name, b"", XattrFlags::None).unwrap();
    
    // Should be able to retrieve empty value
    let value = manager.get_xattr(test_path, attr_name).unwrap();
    assert_eq!(value.len(), 0);
    
    // Should appear in list
    let attrs = manager.list_xattr(test_path).unwrap();
    assert!(attrs.contains(&attr_name.to_string()));
}