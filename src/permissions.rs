use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;
use tracing::debug;

// Access mode constants compatible with POSIX
pub const F_OK: i32 = 0;  // Test for existence
pub const X_OK: i32 = 1;  // Test for execute permission
pub const W_OK: i32 = 2;  // Test for write permission
pub const R_OK: i32 = 4;  // Test for read permission

// Standard errno constants
const EACCES: i32 = 13;

#[derive(Debug)]
pub struct AccessError(pub i32);

impl AccessError {
    pub fn to_errno(&self) -> i32 {
        self.0
    }
}

/// Check if a user has the requested access permissions for a file
/// 
/// This implements POSIX access() semantics:
/// - Root (uid 0) can access any file (except execute requires at least one x bit)
/// - Otherwise, check user/group/other permissions based on file ownership
/// 
/// # Arguments
/// * `uid` - User ID of the process checking access
/// * `gid` - Group ID of the process checking access
/// * `metadata` - File metadata containing ownership and permission information
/// * `mask` - Bitwise OR of F_OK, R_OK, W_OK, X_OK
/// 
/// # Returns
/// * `Ok(())` if access is allowed
/// * `Err(AccessError)` with appropriate errno if access is denied
pub fn check_access(uid: u32, gid: u32, metadata: &Metadata, mask: i32) -> Result<(), AccessError> {
    debug!("check_access: uid={}, gid={}, file_uid={}, file_gid={}, mode={:o}, mask={}", 
        uid, gid, metadata.uid(), metadata.gid(), metadata.mode(), mask);

    // F_OK just checks existence, which we already know
    if mask == F_OK {
        return Ok(());
    }

    // Root can access anything (except execute without any x bit)
    if uid == 0 {
        if mask & X_OK != 0 {
            // Check if any execute bit is set
            let mode = metadata.mode();
            if (mode & 0o111) == 0 {
                debug!("Root denied execute: no execute bits set");
                return Err(AccessError(EACCES));
            }
        }
        debug!("Root access allowed");
        return Ok(());
    }

    let file_uid = metadata.uid();
    let file_gid = metadata.gid();
    let mode = metadata.mode();

    // Determine which permission bits to check
    let perm_bits = if uid == file_uid {
        // User permissions (bits 6-8)
        debug!("Checking user permissions");
        (mode >> 6) & 0o7
    } else if gid == file_gid {
        // Group permissions (bits 3-5)
        debug!("Checking group permissions");
        (mode >> 3) & 0o7
    } else {
        // Other permissions (bits 0-2)
        debug!("Checking other permissions");
        mode & 0o7
    };

    debug!("Permission bits: {:o}", perm_bits);

    // Check each requested permission
    if mask & R_OK != 0 && perm_bits & 0o4 == 0 {
        debug!("Read permission denied");
        return Err(AccessError(EACCES));
    }
    if mask & W_OK != 0 && perm_bits & 0o2 == 0 {
        debug!("Write permission denied");
        return Err(AccessError(EACCES));
    }
    if mask & X_OK != 0 && perm_bits & 0o1 == 0 {
        debug!("Execute permission denied");
        return Err(AccessError(EACCES));
    }

    debug!("Access allowed");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{File, set_permissions};
    use std::os::unix::fs::PermissionsExt;
    use tempfile::TempDir;

    #[test]
    fn test_check_access_root() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        let file = File::create(&file_path).unwrap();
        
        // Set restrictive permissions
        let mut perms = file.metadata().unwrap().permissions();
        perms.set_mode(0o000);
        set_permissions(&file_path, perms).unwrap();
        
        let metadata = std::fs::metadata(&file_path).unwrap();
        
        // Root can read/write even with no permissions
        assert!(check_access(0, 0, &metadata, R_OK).is_ok());
        assert!(check_access(0, 0, &metadata, W_OK).is_ok());
        
        // But not execute without any x bit
        assert!(check_access(0, 0, &metadata, X_OK).is_err());
    }

    #[test]
    fn test_check_access_owner() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        File::create(&file_path).unwrap();
        
        // Set user read/write permissions
        let mut perms = std::fs::metadata(&file_path).unwrap().permissions();
        perms.set_mode(0o600);
        set_permissions(&file_path, perms).unwrap();
        
        let metadata = std::fs::metadata(&file_path).unwrap();
        let uid = metadata.uid();
        let gid = metadata.gid();
        
        // Owner can read/write
        assert!(check_access(uid, gid, &metadata, R_OK).is_ok());
        assert!(check_access(uid, gid, &metadata, W_OK).is_ok());
        
        // But not execute
        assert!(check_access(uid, gid, &metadata, X_OK).is_err());
        
        // Other users cannot access
        assert!(check_access(uid + 1, gid + 1, &metadata, R_OK).is_err());
    }

    #[test]
    fn test_check_access_group() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        File::create(&file_path).unwrap();
        
        // Set group read permission only
        let mut perms = std::fs::metadata(&file_path).unwrap().permissions();
        perms.set_mode(0o040);
        set_permissions(&file_path, perms).unwrap();
        
        let metadata = std::fs::metadata(&file_path).unwrap();
        let uid = metadata.uid();
        let gid = metadata.gid();
        
        // Group member can read
        assert!(check_access(uid + 1, gid, &metadata, R_OK).is_ok());
        
        // But not write or execute
        assert!(check_access(uid + 1, gid, &metadata, W_OK).is_err());
        assert!(check_access(uid + 1, gid, &metadata, X_OK).is_err());
    }

    #[test]
    fn test_check_access_other() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        File::create(&file_path).unwrap();
        
        // Set other execute permission only
        let mut perms = std::fs::metadata(&file_path).unwrap().permissions();
        perms.set_mode(0o001);
        set_permissions(&file_path, perms).unwrap();
        
        let metadata = std::fs::metadata(&file_path).unwrap();
        let uid = metadata.uid();
        let gid = metadata.gid();
        
        // Other users can execute
        assert!(check_access(uid + 1, gid + 1, &metadata, X_OK).is_ok());
        
        // But not read or write
        assert!(check_access(uid + 1, gid + 1, &metadata, R_OK).is_err());
        assert!(check_access(uid + 1, gid + 1, &metadata, W_OK).is_err());
    }

    #[test]
    fn test_check_access_multiple_permissions() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        File::create(&file_path).unwrap();
        
        // Set user rwx permissions
        let mut perms = std::fs::metadata(&file_path).unwrap().permissions();
        perms.set_mode(0o700);
        set_permissions(&file_path, perms).unwrap();
        
        let metadata = std::fs::metadata(&file_path).unwrap();
        let uid = metadata.uid();
        let gid = metadata.gid();
        
        // Owner can do all operations
        assert!(check_access(uid, gid, &metadata, R_OK | W_OK).is_ok());
        assert!(check_access(uid, gid, &metadata, R_OK | X_OK).is_ok());
        assert!(check_access(uid, gid, &metadata, R_OK | W_OK | X_OK).is_ok());
        
        // F_OK always succeeds for existing files
        assert!(check_access(uid + 1, gid + 1, &metadata, F_OK).is_ok());
    }
}