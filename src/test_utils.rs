/// Test utilities for mergerfs-rs
/// Provides helpers for creating controlled test environments

use std::path::{Path, PathBuf};
use std::fs;
use tempfile::TempDir;
use crate::branch::Branch;
use crate::policy::utils::DiskSpace;
use std::sync::Arc;

/// Test setup for space-based policy testing
pub struct SpacePolicyTestSetup {
    pub branches: Vec<(TempDir, u64)>, // (temp_dir, available_mb)
    #[allow(dead_code)]
    mock_space: bool,
}

impl SpacePolicyTestSetup {
    /// Create a test setup with three branches having specific available space
    /// 
    /// # Arguments
    /// * `small_mb` - Available space for small branch in MB
    /// * `medium_mb` - Available space for medium branch in MB  
    /// * `large_mb` - Available space for large branch in MB
    pub fn new(small_mb: u64, medium_mb: u64, large_mb: u64) -> Self {
        let branches = vec![
            (TempDir::new().unwrap(), small_mb),
            (TempDir::new().unwrap(), medium_mb),
            (TempDir::new().unwrap(), large_mb),
        ];
        
        // For now, we'll use mock space calculation
        // In the future, this could try to use tmpfs if available
        SpacePolicyTestSetup {
            branches,
            mock_space: true,
        }
    }
    
    /// Get Arc<Branch> instances for use with policies
    pub fn get_branches(&self) -> Vec<Arc<Branch>> {
        self.branches.iter()
            .map(|(dir, _)| Arc::new(Branch::new(
                dir.path().to_path_buf(),
                crate::branch::BranchMode::ReadWrite
            )))
            .collect()
    }
    
    /// Get the paths of the branches
    pub fn get_paths(&self) -> Vec<PathBuf> {
        self.branches.iter()
            .map(|(dir, _)| dir.path().to_path_buf())
            .collect()
    }
    
    /// Create files to simulate the desired available space
    /// This is a simplified approach that creates marker files
    pub fn setup_space(&self) {
        for (dir, available_mb) in &self.branches {
            let marker_file = dir.path().join(".space_marker");
            fs::write(&marker_file, format!("{}", available_mb)).unwrap();
        }
    }
}

/// Modified DiskSpace calculation for testing
/// Reads from .space_marker files if they exist
pub fn get_test_disk_space(path: &Path) -> std::io::Result<DiskSpace> {
    // Check for space marker file
    let marker_file = path.join(".space_marker");
    if marker_file.exists() {
        let content = fs::read_to_string(&marker_file)?;
        if let Ok(available_mb) = content.trim().parse::<u64>() {
            let total_mb: u64 = 100; // Assume 100MB total for all test branches
            let available = available_mb * 1024 * 1024;
            let total = total_mb * 1024 * 1024;
            let used = total.saturating_sub(available);
            
            return Ok(DiskSpace {
                total,
                available,
                used,
            });
        }
    }
    
    // No marker file found, return an error
    Err(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        "No space marker file found"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_space_policy_setup() {
        let setup = SpacePolicyTestSetup::new(10, 50, 100);
        setup.setup_space();
        
        let branches = setup.get_branches();
        assert_eq!(branches.len(), 3);
        
        // Test that we can read the mock space values
        let space0 = get_test_disk_space(&branches[0].path).unwrap();
        let space1 = get_test_disk_space(&branches[1].path).unwrap();
        let space2 = get_test_disk_space(&branches[2].path).unwrap();
        
        assert_eq!(space0.available, 10 * 1024 * 1024);
        assert_eq!(space1.available, 50 * 1024 * 1024);
        assert_eq!(space2.available, 100 * 1024 * 1024);
    }
}