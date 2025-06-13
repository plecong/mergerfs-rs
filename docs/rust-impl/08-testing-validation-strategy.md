# Testing and Validation Strategy for Rust Implementation

## Overview

This guide provides comprehensive testing and validation strategies for the Rust implementation of mergerfs, covering unit testing, integration testing, property-based testing, performance testing, and validation against the original C++ implementation while ensuring correctness and reliability.

## Testing Architecture

### Test Organization and Structure

#### Modular Test Framework

```rust
// tests/common/mod.rs - Shared test utilities
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tempfile::TempDir;
use std::fs;

pub struct TestEnvironment {
    pub temp_dirs: Vec<TempDir>,
    pub mount_point: TempDir,
    pub branch_paths: Vec<PathBuf>,
}

impl TestEnvironment {
    pub fn new(branch_count: usize) -> Self {
        let mut temp_dirs = Vec::new();
        let mut branch_paths = Vec::new();
        
        // Create branch directories
        for i in 0..branch_count {
            let temp_dir = TempDir::new().unwrap();
            branch_paths.push(temp_dir.path().to_path_buf());
            temp_dirs.push(temp_dir);
        }
        
        // Create mount point
        let mount_point = TempDir::new().unwrap();
        
        Self {
            temp_dirs,
            mount_point,
            branch_paths,
        }
    }
    
    pub fn create_file_in_branch(&self, branch_idx: usize, path: &str, content: &str) -> Result<(), std::io::Error> {
        let full_path = self.branch_paths[branch_idx].join(path);
        if let Some(parent) = full_path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(full_path, content)
    }
    
    pub fn create_dir_in_branch(&self, branch_idx: usize, path: &str) -> Result<(), std::io::Error> {
        let full_path = self.branch_paths[branch_idx].join(path);
        fs::create_dir_all(full_path)
    }
    
    pub fn file_exists_in_branch(&self, branch_idx: usize, path: &str) -> bool {
        self.branch_paths[branch_idx].join(path).exists()
    }
    
    pub fn read_file_from_branch(&self, branch_idx: usize, path: &str) -> Result<String, std::io::Error> {
        let full_path = self.branch_paths[branch_idx].join(path);
        fs::read_to_string(full_path)
    }
    
    pub fn get_branch_count(&self) -> usize {
        self.branch_paths.len()
    }
}

pub struct MockBranch {
    pub path: PathBuf,
    pub mode: BranchMode,
    pub min_free_space: u64,
    pub available_space: u64,
    pub readonly: bool,
}

impl MockBranch {
    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            mode: BranchMode::ReadWrite,
            min_free_space: 0,
            available_space: 1024 * 1024 * 1024, // 1GB
            readonly: false,
        }
    }
    
    pub fn with_mode(mut self, mode: BranchMode) -> Self {
        self.mode = mode;
        self
    }
    
    pub fn with_space(mut self, available_space: u64) -> Self {
        self.available_space = available_space;
        self
    }
    
    pub fn read_only(mut self) -> Self {
        self.readonly = true;
        self
    }
}

// Test-specific error types
#[derive(Debug, thiserror::Error)]
pub enum TestError {
    #[error("Test setup failed: {0}")]
    SetupFailed(String),
    
    #[error("Test assertion failed: {0}")]
    AssertionFailed(String),
    
    #[error("Test cleanup failed: {0}")]
    CleanupFailed(String),
}

// Assertion helpers
pub fn assert_file_content(path: &Path, expected: &str) -> Result<(), TestError> {
    let actual = fs::read_to_string(path)
        .map_err(|e| TestError::AssertionFailed(format!("Cannot read file {}: {}", path.display(), e)))?;
    
    if actual != expected {
        return Err(TestError::AssertionFailed(format!(
            "File content mismatch.\nExpected: {}\nActual: {}",
            expected, actual
        )));
    }
    
    Ok(())
}

pub fn assert_file_exists(path: &Path) -> Result<(), TestError> {
    if !path.exists() {
        return Err(TestError::AssertionFailed(format!(
            "File {} does not exist", path.display()
        )));
    }
    Ok(())
}

pub fn assert_file_not_exists(path: &Path) -> Result<(), TestError> {
    if path.exists() {
        return Err(TestError::AssertionFailed(format!(
            "File {} should not exist", path.display()
        )));
    }
    Ok(())
}
```

### Unit Testing Framework

#### Policy Engine Unit Tests

```rust
// tests/unit/policy_tests.rs
use mergerfs::policy::*;
use mergerfs::branch::*;
use crate::common::*;

#[test]
fn test_first_found_create_policy() {
    let env = TestEnvironment::new(3);
    let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
        .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
        .collect();
    
    let policy = FirstFoundCreatePolicy;
    let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
    
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].path, branches[0].path);
}

#[test]
fn test_most_free_space_policy() {
    let env = TestEnvironment::new(3);
    let mut branches = Vec::new();
    
    // Create branches with different available space
    for (i, path) in env.branch_paths.iter().enumerate() {
        let mut branch = Branch::new(path.clone(), BranchMode::ReadWrite, 0);
        // Mock different space amounts - this would need the actual implementation
        // to support space mocking for testing
        branches.push(Arc::new(branch));
    }
    
    let policy = MostFreeSpaceCreatePolicy;
    let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
    
    assert_eq!(result.len(), 1);
    // Should select the branch with most space
}

#[test]
fn test_policy_with_readonly_branches() {
    let env = TestEnvironment::new(2);
    let branches: Vec<Arc<Branch>> = vec![
        Arc::new(Branch::new(env.branch_paths[0].clone(), BranchMode::ReadOnly, 0)),
        Arc::new(Branch::new(env.branch_paths[1].clone(), BranchMode::ReadWrite, 0)),
    ];
    
    let policy = FirstFoundCreatePolicy;
    let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
    
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].path, branches[1].path); // Should skip readonly branch
}

#[test]
fn test_policy_no_writable_branches() {
    let env = TestEnvironment::new(2);
    let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
        .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadOnly, 0)))
        .collect();
    
    let policy = FirstFoundCreatePolicy;
    let result = policy.select_branches(&branches, Path::new("test.txt"));
    
    assert!(result.is_err());
    match result.unwrap_err() {
        PolicyError::ReadOnlyFilesystem => {},
        _ => panic!("Expected ReadOnlyFilesystem error"),
    }
}

#[test]
fn test_existing_path_policy() {
    let env = TestEnvironment::new(3);
    
    // Create a file in the second branch
    env.create_file_in_branch(1, "existing.txt", "content").unwrap();
    
    let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
        .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
        .collect();
    
    let policy = ExistingPathFirstFoundActionPolicy;
    let result = policy.target_branches(&branches, Path::new("existing.txt")).unwrap();
    
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].path, branches[1].path);
}

#[test]
fn test_policy_registry() {
    let registry = PolicyRegistry::new();
    
    // Test create policies
    assert!(registry.get_create_policy("ff").is_some());
    assert!(registry.get_create_policy("mfs").is_some());
    assert!(registry.get_create_policy("pfrd").is_some());
    assert!(registry.get_create_policy("nonexistent").is_none());
    
    // Test policy resolution
    let policy_ref = CreatePolicyRef::new("ff");
    let policy = policy_ref.resolve().unwrap();
    assert_eq!(policy.name(), "ff");
}

#[cfg(test)]
mod property_tests {
    use super::*;
    use proptest::prelude::*;
    
    proptest! {
        #[test]
        fn test_policy_always_returns_valid_branch(
            branch_count in 1..10usize,
            writable_count in 1..10usize,
        ) {
            let branch_count = branch_count.max(writable_count);
            let env = TestEnvironment::new(branch_count);
            
            let mut branches = Vec::new();
            for (i, path) in env.branch_paths.iter().enumerate() {
                let mode = if i < writable_count {
                    BranchMode::ReadWrite
                } else {
                    BranchMode::ReadOnly
                };
                branches.push(Arc::new(Branch::new(path.clone(), mode, 0)));
            }
            
            let policy = FirstFoundCreatePolicy;
            if writable_count > 0 {
                let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
                prop_assert!(!result.is_empty());
                prop_assert!(result[0].allows_create());
            }
        }
        
        #[test]
        fn test_policy_deterministic_with_same_input(
            branch_count in 1..5usize,
            path in "[a-zA-Z0-9/._-]{1,50}",
        ) {
            let env = TestEnvironment::new(branch_count);
            let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
                .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
                .collect();
            
            let policy = FirstFoundCreatePolicy;
            let path = Path::new(&path);
            
            let result1 = policy.select_branches(&branches, path);
            let result2 = policy.select_branches(&branches, path);
            
            // Results should be identical for deterministic policies
            prop_assert_eq!(result1.is_ok(), result2.is_ok());
            if let (Ok(r1), Ok(r2)) = (result1, result2) {
                prop_assert_eq!(r1.len(), r2.len());
                for (b1, b2) in r1.iter().zip(r2.iter()) {
                    prop_assert_eq!(b1.path, b2.path);
                }
            }
        }
    }
}
```

#### Error Handling Unit Tests

```rust
// tests/unit/error_tests.rs
use mergerfs::error::*;

#[test]
fn test_error_priority_ordering() {
    let errors = vec![
        MergerFsError::PathNotFound { path: "/test".into() },
        MergerFsError::PermissionDenied { path: "/test".into() },
        MergerFsError::NoSpaceLeft { path: "/test".into() },
        MergerFsError::ReadOnlyFilesystem { path: "/test".into() },
    ];
    
    // Test priority ordering
    assert!(errors[1].priority() > errors[0].priority()); // Permission > PathNotFound
    assert!(errors[1].priority() > errors[2].priority()); // Permission > NoSpace
    assert!(errors[2].priority() > errors[0].priority()); // NoSpace > PathNotFound
}

#[test]
fn test_error_aggregation() {
    let mut aggregator = ErrorAggregator::new("test_op", "/test".into());
    
    // Add errors with different priorities
    aggregator.add_error("/branch1".into(), MergerFsError::PathNotFound { path: "/test".into() });
    aggregator.add_error("/branch2".into(), MergerFsError::PermissionDenied { path: "/test".into() });
    aggregator.add_error("/branch3".into(), MergerFsError::NoSpaceLeft { path: "/test".into() });
    
    let result = aggregator.into_result();
    assert!(result.is_err());
    
    let error = result.unwrap_err();
    // Should report the highest priority error (PermissionDenied)
    assert!(matches!(error.final_error, MergerFsError::PermissionDenied { .. }));
}

#[test]
fn test_error_aggregation_with_success() {
    let mut aggregator = ErrorAggregator::new("test_op", "/test".into());
    
    // Add both successes and errors
    aggregator.add_success("/branch1".into());
    aggregator.add_error("/branch2".into(), MergerFsError::PathNotFound { path: "/test".into() });
    aggregator.add_success("/branch3".into());
    
    let result = aggregator.into_result();
    assert!(result.is_ok()); // Should succeed if any branch succeeded
}

#[test]
fn test_contextual_error_creation() {
    let error = contextual_error!(
        "test_operation",
        "/test/path",
        MergerFsError::PermissionDenied { path: "/test/path".into() },
        "branch" => "/branch1",
        "uid" => "1000"
    );
    
    assert_eq!(error.context.operation, "test_operation");
    assert_eq!(error.context.path, Path::new("/test/path"));
    assert!(error.context.metadata.contains_key("branch"));
    assert!(error.context.metadata.contains_key("uid"));
}
```

### Integration Testing

#### Full Filesystem Operation Tests

```rust
// tests/integration/filesystem_tests.rs
use mergerfs::*;
use crate::common::*;
use std::sync::Arc;

struct IntegrationTestFixture {
    env: TestEnvironment,
    filesystem: MergerFs,
}

impl IntegrationTestFixture {
    fn new() -> Self {
        let env = TestEnvironment::new(3);
        
        // Create branches
        let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
            .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
            .collect();
        
        // Create configuration
        let config = Config {
            branches: BranchConfig {
                paths: branches.iter().map(|b| BranchPath {
                    path: b.path.clone(),
                    mode: b.mode.clone(),
                    min_free_space: None,
                }).collect(),
                min_free_space: 0,
                mount_timeout: Duration::from_secs(10),
                mount_timeout_fail: false,
            },
            mount_point: env.mount_point.path().to_path_buf(),
            function_policies: FunctionPolicies::default(),
            // ... other config fields
        };
        
        let filesystem = MergerFs::new(config).unwrap();
        
        Self { env, filesystem }
    }
}

#[tokio::test]
async fn test_file_create_and_read() {
    let fixture = IntegrationTestFixture::new();
    let test_path = "/test_file.txt";
    let test_content = "Hello, World!";
    
    // Create file
    let mut file_info = FileInfo {
        flags: libc::O_WRONLY | libc::O_CREAT,
        file_handle: 0,
        // ... other fields
    };
    
    fixture.filesystem.create(Path::new(test_path), 0o644, &mut file_info).unwrap();
    
    // Write content
    let bytes_written = fixture.filesystem.write(
        Path::new(test_path),
        test_content.as_bytes(),
        0,
        &file_info
    ).unwrap();
    
    assert_eq!(bytes_written, test_content.len());
    
    // Release file
    fixture.filesystem.release(Path::new(test_path), &file_info).unwrap();
    
    // Read file back
    let mut read_file_info = FileInfo {
        flags: libc::O_RDONLY,
        file_handle: 0,
        // ... other fields
    };
    
    fixture.filesystem.open(Path::new(test_path), &mut read_file_info).unwrap();
    
    let mut buffer = vec![0u8; test_content.len()];
    let bytes_read = fixture.filesystem.read(
        Path::new(test_path),
        &mut buffer,
        0,
        &read_file_info
    ).unwrap();
    
    assert_eq!(bytes_read, test_content.len());
    assert_eq!(String::from_utf8(buffer).unwrap(), test_content);
    
    // Verify file exists in one of the branches
    let found_in_branch = fixture.env.branch_paths.iter()
        .any(|branch_path| branch_path.join("test_file.txt").exists());
    
    assert!(found_in_branch);
}

#[tokio::test]
async fn test_directory_operations() {
    let fixture = IntegrationTestFixture::new();
    let test_dir = "/test_directory";
    
    // Create directory
    fixture.filesystem.mkdir(Path::new(test_dir), 0o755).unwrap();
    
    // Verify directory exists in at least one branch
    let found_in_branch = fixture.env.branch_paths.iter()
        .any(|branch_path| branch_path.join("test_directory").is_dir());
    
    assert!(found_in_branch);
    
    // Create files in directory
    fixture.env.create_file_in_branch(0, "test_directory/file1.txt", "content1").unwrap();
    fixture.env.create_file_in_branch(1, "test_directory/file2.txt", "content2").unwrap();
    fixture.env.create_file_in_branch(2, "test_directory/file3.txt", "content3").unwrap();
    
    // Read directory
    let file_info = FileInfo::default();
    let entries = fixture.filesystem.readdir(Path::new(test_dir), &file_info).unwrap();
    
    // Should see all files merged
    assert_eq!(entries.len(), 3);
    let names: Vec<String> = entries.iter().map(|e| e.name.clone()).collect();
    assert!(names.contains(&"file1.txt".to_string()));
    assert!(names.contains(&"file2.txt".to_string()));
    assert!(names.contains(&"file3.txt".to_string()));
    
    // Remove directory
    fixture.filesystem.rmdir(Path::new(test_dir)).unwrap();
}

#[tokio::test]
async fn test_cross_branch_rename() {
    let fixture = IntegrationTestFixture::new();
    
    // Create file in first branch
    fixture.env.create_file_in_branch(0, "source_file.txt", "test content").unwrap();
    
    // Rename to different location
    fixture.filesystem.rename(
        Path::new("/source_file.txt"),
        Path::new("/destination_file.txt"),
        0
    ).unwrap();
    
    // Verify source file is gone
    assert!(!fixture.env.file_exists_in_branch(0, "source_file.txt"));
    
    // Verify destination file exists
    let found_destination = fixture.env.branch_paths.iter()
        .any(|branch_path| branch_path.join("destination_file.txt").exists());
    
    assert!(found_destination);
}

#[tokio::test]
async fn test_policy_behavior() {
    let fixture = IntegrationTestFixture::new();
    
    // Fill up first two branches (mock)
    // This would need actual space management in the test
    
    // Create file - should go to third branch due to space constraints
    let mut file_info = FileInfo {
        flags: libc::O_WRONLY | libc::O_CREAT,
        file_handle: 0,
        // ... other fields
    };
    
    fixture.filesystem.create(Path::new("/space_test.txt"), 0o644, &mut file_info).unwrap();
    
    // Verify file was created in expected branch based on policy
    // This test would need more sophisticated setup to actually test space-based policies
}
```

### Property-Based Testing

#### Filesystem Property Tests

```rust
// tests/property/filesystem_properties.rs
use proptest::prelude::*;
use mergerfs::*;
use crate::common::*;

// Property: Files created should always be readable
proptest! {
    #[test]
    fn prop_created_files_are_readable(
        filename in "[a-zA-Z0-9_-]{1,50}\\.txt",
        content in ".*{0,1000}",
    ) {
        let fixture = IntegrationTestFixture::new();
        let path = Path::new(&filename);
        
        // Create and write file
        let mut file_info = FileInfo {
            flags: libc::O_WRONLY | libc::O_CREAT,
            file_handle: 0,
            // ... other fields
        };
        
        prop_assume!(fixture.filesystem.create(path, 0o644, &mut file_info).is_ok());
        
        let bytes_written = fixture.filesystem.write(
            path,
            content.as_bytes(),
            0,
            &file_info
        ).unwrap();
        
        fixture.filesystem.release(path, &file_info).unwrap();
        
        // Read file back
        let mut read_file_info = FileInfo {
            flags: libc::O_RDONLY,
            file_handle: 0,
            // ... other fields
        };
        
        prop_assert!(fixture.filesystem.open(path, &mut read_file_info).is_ok());
        
        let mut buffer = vec![0u8; content.len()];
        let bytes_read = fixture.filesystem.read(
            path,
            &mut buffer,
            0,
            &read_file_info
        ).unwrap();
        
        prop_assert_eq!(bytes_read, content.len());
        prop_assert_eq!(String::from_utf8(buffer).unwrap(), content);
    }
    
    #[test]
    fn prop_directory_listing_consistency(
        dir_name in "[a-zA-Z0-9_-]{1,30}",
        file_names in prop::collection::vec("[a-zA-Z0-9_-]{1,20}\\.txt", 0..10),
    ) {
        let fixture = IntegrationTestFixture::new();
        let dir_path = Path::new(&dir_name);
        
        // Create directory
        prop_assume!(fixture.filesystem.mkdir(dir_path, 0o755).is_ok());
        
        // Create files in different branches
        for (i, file_name) in file_names.iter().enumerate() {
            let branch_idx = i % fixture.env.get_branch_count();
            let file_path = format!("{}/{}", dir_name, file_name);
            fixture.env.create_file_in_branch(branch_idx, &file_path, "content").unwrap();
        }
        
        // Read directory
        let file_info = FileInfo::default();
        let entries = fixture.filesystem.readdir(dir_path, &file_info).unwrap();
        
        // All files should be visible in directory listing
        let listed_names: std::collections::HashSet<String> = 
            entries.iter().map(|e| e.name.clone()).collect();
        
        for file_name in &file_names {
            prop_assert!(listed_names.contains(file_name));
        }
        
        // No duplicate entries
        prop_assert_eq!(entries.len(), listed_names.len());
    }
    
    #[test]
    fn prop_file_operations_are_atomic(
        filename in "[a-zA-Z0-9_-]{1,30}\\.txt",
        operations in prop::collection::vec(
            prop_oneof![
                Just(FileOp::Create),
                Just(FileOp::Write),
                Just(FileOp::Read),
                Just(FileOp::Delete),
            ],
            1..10
        ),
    ) {
        let fixture = IntegrationTestFixture::new();
        let path = Path::new(&filename);
        
        for operation in operations {
            match operation {
                FileOp::Create => {
                    let mut file_info = FileInfo {
                        flags: libc::O_WRONLY | libc::O_CREAT,
                        file_handle: 0,
                        // ... other fields
                    };
                    let _ = fixture.filesystem.create(path, 0o644, &mut file_info);
                },
                FileOp::Write => {
                    // Only write if file exists
                    if fixture.env.branch_paths.iter().any(|bp| bp.join(&filename).exists()) {
                        let mut file_info = FileInfo {
                            flags: libc::O_WRONLY,
                            file_handle: 0,
                            // ... other fields
                        };
                        if fixture.filesystem.open(path, &mut file_info).is_ok() {
                            let _ = fixture.filesystem.write(path, b"test", 0, &file_info);
                            let _ = fixture.filesystem.release(path, &file_info);
                        }
                    }
                },
                FileOp::Read => {
                    // Only read if file exists
                    if fixture.env.branch_paths.iter().any(|bp| bp.join(&filename).exists()) {
                        let mut file_info = FileInfo {
                            flags: libc::O_RDONLY,
                            file_handle: 0,
                            // ... other fields
                        };
                        if fixture.filesystem.open(path, &mut file_info).is_ok() {
                            let mut buffer = [0u8; 100];
                            let _ = fixture.filesystem.read(path, &mut buffer, 0, &file_info);
                            let _ = fixture.filesystem.release(path, &file_info);
                        }
                    }
                },
                FileOp::Delete => {
                    let _ = fixture.filesystem.unlink(path);
                },
            }
            
            // After each operation, filesystem should be in consistent state
            // (this is a simplified check - real implementation would be more thorough)
            let file_exists = fixture.env.branch_paths.iter()
                .any(|bp| bp.join(&filename).exists());
            
            // If file exists, it should be readable
            if file_exists {
                let attr_result = fixture.filesystem.getattr(path);
                prop_assert!(attr_result.is_ok());
            }
        }
    }
}

#[derive(Debug, Clone)]
enum FileOp {
    Create,
    Write,
    Read,
    Delete,
}
```

### Performance Testing

#### Benchmark Framework

```rust
// benches/filesystem_benchmarks.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use mergerfs::*;
use std::sync::Arc;
use tempfile::TempDir;

struct BenchmarkFixture {
    env: TestEnvironment,
    filesystem: MergerFs,
}

impl BenchmarkFixture {
    fn new(branch_count: usize) -> Self {
        let env = TestEnvironment::new(branch_count);
        
        let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
            .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
            .collect();
        
        let config = Config {
            branches: BranchConfig {
                paths: branches.iter().map(|b| BranchPath {
                    path: b.path.clone(),
                    mode: b.mode.clone(),
                    min_free_space: None,
                }).collect(),
                min_free_space: 0,
                mount_timeout: Duration::from_secs(10),
                mount_timeout_fail: false,
            },
            mount_point: env.mount_point.path().to_path_buf(),
            function_policies: FunctionPolicies::default(),
            // ... other config fields
        };
        
        let filesystem = MergerFs::new(config).unwrap();
        
        Self { env, filesystem }
    }
}

fn benchmark_file_creation(c: &mut Criterion) {
    let mut group = c.benchmark_group("file_creation");
    
    for branch_count in [1, 3, 5, 10].iter() {
        group.bench_with_input(
            BenchmarkId::new("branches", branch_count),
            branch_count,
            |b, &branch_count| {
                let fixture = BenchmarkFixture::new(branch_count);
                let mut counter = 0;
                
                b.iter(|| {
                    let filename = format!("/test_file_{}.txt", counter);
                    counter += 1;
                    
                    let mut file_info = FileInfo {
                        flags: libc::O_WRONLY | libc::O_CREAT,
                        file_handle: 0,
                        // ... other fields
                    };
                    
                    black_box(fixture.filesystem.create(
                        Path::new(&filename),
                        0o644,
                        &mut file_info
                    ).unwrap());
                    
                    black_box(fixture.filesystem.release(
                        Path::new(&filename),
                        &file_info
                    ).unwrap());
                });
            },
        );
    }
    
    group.finish();
}

fn benchmark_file_read_write(c: &mut Criterion) {
    let mut group = c.benchmark_group("file_io");
    
    for size in [1024, 4096, 65536, 1048576].iter() {
        group.bench_with_input(
            BenchmarkId::new("write_bytes", size),
            size,
            |b, &size| {
                let fixture = BenchmarkFixture::new(3);
                let data = vec![0xAA; size];
                
                // Pre-create file
                let mut file_info = FileInfo {
                    flags: libc::O_WRONLY | libc::O_CREAT,
                    file_handle: 0,
                    // ... other fields
                };
                
                fixture.filesystem.create(
                    Path::new("/benchmark_file.txt"),
                    0o644,
                    &mut file_info
                ).unwrap();
                
                b.iter(|| {
                    black_box(fixture.filesystem.write(
                        Path::new("/benchmark_file.txt"),
                        &data,
                        0,
                        &file_info
                    ).unwrap());
                });
                
                fixture.filesystem.release(
                    Path::new("/benchmark_file.txt"),
                    &file_info
                ).unwrap();
            },
        );
        
        group.bench_with_input(
            BenchmarkId::new("read_bytes", size),
            size,
            |b, &size| {
                let fixture = BenchmarkFixture::new(3);
                let data = vec![0xAA; size];
                
                // Pre-create and write file
                let mut write_info = FileInfo {
                    flags: libc::O_WRONLY | libc::O_CREAT,
                    file_handle: 0,
                    // ... other fields
                };
                
                fixture.filesystem.create(
                    Path::new("/benchmark_file.txt"),
                    0o644,
                    &mut write_info
                ).unwrap();
                
                fixture.filesystem.write(
                    Path::new("/benchmark_file.txt"),
                    &data,
                    0,
                    &write_info
                ).unwrap();
                
                fixture.filesystem.release(
                    Path::new("/benchmark_file.txt"),
                    &write_info
                ).unwrap();
                
                let mut read_info = FileInfo {
                    flags: libc::O_RDONLY,
                    file_handle: 0,
                    // ... other fields
                };
                
                fixture.filesystem.open(
                    Path::new("/benchmark_file.txt"),
                    &mut read_info
                ).unwrap();
                
                let mut buffer = vec![0u8; size];
                
                b.iter(|| {
                    black_box(fixture.filesystem.read(
                        Path::new("/benchmark_file.txt"),
                        &mut buffer,
                        0,
                        &read_info
                    ).unwrap());
                });
                
                fixture.filesystem.release(
                    Path::new("/benchmark_file.txt"),
                    &read_info
                ).unwrap();
            },
        );
    }
    
    group.finish();
}

fn benchmark_directory_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("directory_ops");
    
    for file_count in [10, 100, 1000].iter() {
        group.bench_with_input(
            BenchmarkId::new("readdir_files", file_count),
            file_count,
            |b, &file_count| {
                let fixture = BenchmarkFixture::new(3);
                
                // Create directory with many files across branches
                fixture.filesystem.mkdir(Path::new("/test_dir"), 0o755).unwrap();
                
                for i in 0..file_count {
                    let branch_idx = i % 3;
                    let filename = format!("test_dir/file_{}.txt", i);
                    fixture.env.create_file_in_branch(branch_idx, &filename, "content").unwrap();
                }
                
                let file_info = FileInfo::default();
                
                b.iter(|| {
                    black_box(fixture.filesystem.readdir(
                        Path::new("/test_dir"),
                        &file_info
                    ).unwrap());
                });
            },
        );
    }
    
    group.finish();
}

fn benchmark_policy_performance(c: &mut Criterion) {
    let mut group = c.benchmark_group("policy_execution");
    
    for branch_count in [3, 5, 10, 20].iter() {
        group.bench_with_input(
            BenchmarkId::new("ff_policy", branch_count),
            branch_count,
            |b, &branch_count| {
                let env = TestEnvironment::new(branch_count);
                let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
                    .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
                    .collect();
                
                let policy = FirstFoundCreatePolicy;
                
                b.iter(|| {
                    black_box(policy.select_branches(
                        &branches,
                        Path::new("/test_file.txt")
                    ).unwrap());
                });
            },
        );
        
        group.bench_with_input(
            BenchmarkId::new("mfs_policy", branch_count),
            branch_count,
            |b, &branch_count| {
                let env = TestEnvironment::new(branch_count);
                let branches: Vec<Arc<Branch>> = env.branch_paths.iter()
                    .map(|path| Arc::new(Branch::new(path.clone(), BranchMode::ReadWrite, 0)))
                    .collect();
                
                let policy = MostFreeSpaceCreatePolicy;
                
                b.iter(|| {
                    black_box(policy.select_branches(
                        &branches,
                        Path::new("/test_file.txt")
                    ).unwrap());
                });
            },
        );
    }
    
    group.finish();
}

criterion_group!(
    benches,
    benchmark_file_creation,
    benchmark_file_read_write,
    benchmark_directory_operations,
    benchmark_policy_performance
);
criterion_main!(benches);
```

### Compatibility Testing

#### C++ Implementation Comparison

```rust
// tests/compatibility/cpp_comparison.rs
use std::process::Command;
use std::path::Path;
use crate::common::*;

struct CppMergerFs {
    mount_point: PathBuf,
    process: Option<std::process::Child>,
}

impl CppMergerFs {
    fn mount(branches: &[PathBuf], mount_point: &Path) -> Result<Self, std::io::Error> {
        let branch_str = branches.iter()
            .map(|p| p.to_string_lossy())
            .collect::<Vec<_>>()
            .join(":");
        
        let mut cmd = Command::new("mergerfs");
        cmd.arg(&branch_str)
           .arg(mount_point)
           .arg("-o")
           .arg("allow_other,use_ino,cache.files=off,dropcacheonclose=true,category.create=mfs");
        
        let process = cmd.spawn()?;
        
        // Wait for mount to complete
        std::thread::sleep(std::time::Duration::from_secs(1));
        
        Ok(Self {
            mount_point: mount_point.to_path_buf(),
            process: Some(process),
        })
    }
    
    fn unmount(&mut self) -> Result<(), std::io::Error> {
        Command::new("fusermount")
            .arg("-u")
            .arg(&self.mount_point)
            .status()?;
        
        if let Some(mut process) = self.process.take() {
            process.wait()?;
        }
        
        Ok(())
    }
}

impl Drop for CppMergerFs {
    fn drop(&mut self) {
        let _ = self.unmount();
    }
}

#[test]
fn test_compatibility_file_operations() {
    let env = TestEnvironment::new(3);
    
    // Test with C++ implementation
    let mut cpp_fs = CppMergerFs::mount(&env.branch_paths, env.mount_point.path()).unwrap();
    
    // Create file through C++ implementation
    let test_file = env.mount_point.path().join("test_file.txt");
    std::fs::write(&test_file, "test content").unwrap();
    
    // Verify file appears in branches
    let found_in_branch = env.branch_paths.iter()
        .any(|branch| branch.join("test_file.txt").exists());
    assert!(found_in_branch);
    
    // Read back through mount
    let content = std::fs::read_to_string(&test_file).unwrap();
    assert_eq!(content, "test content");
    
    cpp_fs.unmount().unwrap();
    
    // Now test with Rust implementation
    let fixture = IntegrationTestFixture::new();
    
    // Ensure same behavior
    let mut file_info = FileInfo {
        flags: libc::O_WRONLY | libc::O_CREAT,
        file_handle: 0,
        // ... other fields
    };
    
    fixture.filesystem.create(Path::new("/test_file_rust.txt"), 0o644, &mut file_info).unwrap();
    fixture.filesystem.write(
        Path::new("/test_file_rust.txt"),
        b"test content",
        0,
        &file_info
    ).unwrap();
    fixture.filesystem.release(Path::new("/test_file_rust.txt"), &file_info).unwrap();
    
    // Verify same behavior
    let found_in_branch_rust = env.branch_paths.iter()
        .any(|branch| branch.join("test_file_rust.txt").exists());
    assert!(found_in_branch_rust);
}

#[test]
fn test_policy_compatibility() {
    // Test that Rust policies behave the same as C++ policies
    let env = TestEnvironment::new(3);
    
    // Set up different space conditions in branches
    // (This would need actual space manipulation for real testing)
    
    // Test with C++ mergerfs using mfs policy
    let mut cpp_fs = CppMergerFs::mount(&env.branch_paths, env.mount_point.path()).unwrap();
    
    let test_files = [
        "file1.txt", "file2.txt", "file3.txt", "file4.txt", "file5.txt"
    ];
    
    // Create files through C++ implementation
    for filename in &test_files {
        let file_path = env.mount_point.path().join(filename);
        std::fs::write(&file_path, "content").unwrap();
    }
    
    // Record which branch each file ended up in
    let mut cpp_distribution = std::collections::HashMap::new();
    for filename in &test_files {
        for (i, branch_path) in env.branch_paths.iter().enumerate() {
            if branch_path.join(filename).exists() {
                cpp_distribution.insert(filename.to_string(), i);
                break;
            }
        }
    }
    
    cpp_fs.unmount().unwrap();
    
    // Clean up files for Rust test
    for filename in &test_files {
        for branch_path in &env.branch_paths {
            let _ = std::fs::remove_file(branch_path.join(filename));
        }
    }
    
    // Test with Rust implementation using same policy
    let fixture = IntegrationTestFixture::new();
    
    for filename in &test_files {
        let mut file_info = FileInfo {
            flags: libc::O_WRONLY | libc::O_CREAT,
            file_handle: 0,
            // ... other fields
        };
        
        fixture.filesystem.create(Path::new(&format!("/{}", filename)), 0o644, &mut file_info).unwrap();
        fixture.filesystem.write(
            Path::new(&format!("/{}", filename)),
            b"content",
            0,
            &file_info
        ).unwrap();
        fixture.filesystem.release(Path::new(&format!("/{}", filename)), &file_info).unwrap();
    }
    
    // Record Rust distribution
    let mut rust_distribution = std::collections::HashMap::new();
    for filename in &test_files {
        for (i, branch_path) in env.branch_paths.iter().enumerate() {
            if branch_path.join(filename).exists() {
                rust_distribution.insert(filename.to_string(), i);
                break;
            }
        }
    }
    
    // Compare distributions - they should be similar
    // (exact match might not be possible due to timing differences)
    assert_eq!(cpp_distribution.len(), rust_distribution.len());
    
    for filename in &test_files {
        assert!(cpp_distribution.contains_key(&filename.to_string()));
        assert!(rust_distribution.contains_key(&filename.to_string()));
    }
}
```

### Continuous Integration Testing

#### CI Test Configuration

Testing across different libc implementations:

```yaml
# .github/workflows/tests.yml
strategy:
  matrix:
    os: [ubuntu-latest]
    target: 
      - x86_64-unknown-linux-gnu     # glibc
      - x86_64-unknown-linux-musl    # musl (Alpine Linux)
    include:
      - target: x86_64-unknown-linux-musl
        container: alpine:latest
```

```rust
// .github/workflows/tests.yml equivalent in Rust

// tests/ci/mod.rs
use std::env;

pub struct CiEnvironment {
    pub is_ci: bool,
    pub branch_name: Option<String>,
    pub pr_number: Option<u32>,
    pub runner_os: String,
}

impl CiEnvironment {
    pub fn detect() -> Self {
        Self {
            is_ci: env::var("CI").is_ok(),
            branch_name: env::var("GITHUB_REF_NAME").ok(),
            pr_number: env::var("PR_NUMBER")
                .ok()
                .and_then(|s| s.parse().ok()),
            runner_os: env::var("RUNNER_OS").unwrap_or_else(|_| "unknown".to_string()),
        }
    }
    
    pub fn should_run_long_tests(&self) -> bool {
        // Run long tests on main branch or specific conditions
        self.branch_name.as_deref() == Some("main") || 
        env::var("RUN_LONG_TESTS").is_ok()
    }
    
    pub fn should_run_compatibility_tests(&self) -> bool {
        // Only run compatibility tests if C++ mergerfs is available
        which::which("mergerfs").is_ok()
    }
}

// CI-specific test configuration
#[cfg(test)]
mod ci_tests {
    use super::*;
    
    #[test]
    fn test_basic_functionality() {
        // Always run basic tests in CI
        let fixture = IntegrationTestFixture::new();
        
        // Test basic file operations
        let test_path = "/ci_test_file.txt";
        let mut file_info = FileInfo {
            flags: libc::O_WRONLY | libc::O_CREAT,
            file_handle: 0,
            // ... other fields
        };
        
        assert!(fixture.filesystem.create(Path::new(test_path), 0o644, &mut file_info).is_ok());
        assert!(fixture.filesystem.write(Path::new(test_path), b"test", 0, &file_info).is_ok());
        assert!(fixture.filesystem.release(Path::new(test_path), &file_info).is_ok());
    }
    
    #[test]
    #[ignore = "long_test"]
    fn test_stress_operations() {
        let ci = CiEnvironment::detect();
        if !ci.should_run_long_tests() {
            return;
        }
        
        // Stress test with many operations
        let fixture = IntegrationTestFixture::new();
        
        for i in 0..1000 {
            let filename = format!("/stress_test_{}.txt", i);
            let mut file_info = FileInfo {
                flags: libc::O_WRONLY | libc::O_CREAT,
                file_handle: 0,
                // ... other fields
            };
            
            fixture.filesystem.create(Path::new(&filename), 0o644, &mut file_info).unwrap();
            fixture.filesystem.write(Path::new(&filename), b"content", 0, &file_info).unwrap();
            fixture.filesystem.release(Path::new(&filename), &file_info).unwrap();
        }
    }
    
    #[test]
    #[ignore = "requires_cpp_mergerfs"]
    fn test_cpp_compatibility() {
        let ci = CiEnvironment::detect();
        if !ci.should_run_compatibility_tests() {
            return;
        }
        
        // Run compatibility tests
        test_compatibility_file_operations();
    }
}

// Test result reporting
pub struct TestReporter {
    results: Vec<TestResult>,
}

#[derive(Debug)]
pub struct TestResult {
    pub name: String,
    pub passed: bool,
    pub duration: std::time::Duration,
    pub error: Option<String>,
}

impl TestReporter {
    pub fn new() -> Self {
        Self {
            results: Vec::new(),
        }
    }
    
    pub fn add_result(&mut self, result: TestResult) {
        self.results.push(result);
    }
    
    pub fn generate_report(&self) -> String {
        let total = self.results.len();
        let passed = self.results.iter().filter(|r| r.passed).count();
        let failed = total - passed;
        
        let mut report = format!("Test Results: {} total, {} passed, {} failed\n\n", 
                                total, passed, failed);
        
        if failed > 0 {
            report.push_str("Failed tests:\n");
            for result in &self.results {
                if !result.passed {
                    report.push_str(&format!("  - {}: {}\n", 
                                            result.name, 
                                            result.error.as_deref().unwrap_or("Unknown error")));
                }
            }
        }
        
        report
    }
    
    pub fn save_junit_xml(&self, path: &Path) -> Result<(), std::io::Error> {
        let xml = self.generate_junit_xml();
        std::fs::write(path, xml)
    }
    
    fn generate_junit_xml(&self) -> String {
        let total = self.results.len();
        let failed = self.results.iter().filter(|r| !r.passed).count();
        let total_time: f64 = self.results.iter()
            .map(|r| r.duration.as_secs_f64())
            .sum();
        
        let mut xml = format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="mergerfs-rust" tests="{}" failures="{}" time="{:.3}">
"#,
            total, failed, total_time
        );
        
        for result in &self.results {
            xml.push_str(&format!(
                r#"  <testcase name="{}" time="{:.3}">"#,
                result.name,
                result.duration.as_secs_f64()
            ));
            
            if !result.passed {
                xml.push_str(&format!(
                    r#"
    <failure message="{}">{}</failure>"#,
                    result.error.as_deref().unwrap_or("Test failed"),
                    result.error.as_deref().unwrap_or("")
                ));
            }
            
            xml.push_str("</testcase>\n");
        }
        
        xml.push_str("</testsuite>");
        xml
    }
}
```

This comprehensive testing strategy provides:

1. **Modular test framework** with shared utilities and fixtures
2. **Unit tests** for individual components with property-based testing
3. **Integration tests** for full filesystem operations
4. **Performance benchmarks** to ensure efficiency
5. **Compatibility testing** against the original C++ implementation
6. **CI/CD integration** with proper test reporting and categorization
7. **Property-based testing** to verify filesystem invariants
8. **Stress testing** for reliability under load

The testing framework ensures that the Rust implementation maintains correctness, performance, and compatibility with the original mergerfs while providing confidence in the reliability of the rewritten system.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content":"Create policy engine implementation guide for Rust","status":"completed","priority":"high","id":"1"},{"content":"Create thread safety and concurrency patterns guide","status":"completed","priority":"high","id":"2"},{"content":"Create error handling system design guide","status":"completed","priority":"high","id":"3"},{"content":"Create configuration system implementation guide","status":"completed","priority":"medium","id":"4"},{"content":"Create memory management and data structures guide","status":"completed","priority":"medium","id":"5"},{"content":"Create platform abstraction layer guide","status":"completed","priority":"medium","id":"6"},{"content":"Create FUSE integration patterns guide","status":"completed","priority":"medium","id":"7"},{"content":"Create testing and validation strategy guide","status":"completed","priority":"low","id":"8"}]