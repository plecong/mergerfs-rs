use super::{XattrError, XattrFlags, PolicyRV};
use crate::branch::Branch;
use crate::policy::{ActionPolicy, SearchPolicy};
use std::path::Path;
use std::sync::Arc;
use xattr;
use tracing;

pub trait XattrOperations {
    fn get_xattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, XattrError>;
    fn set_xattr(&self, path: &Path, name: &str, value: &[u8], flags: XattrFlags) -> Result<(), XattrError>;
    fn list_xattr(&self, path: &Path) -> Result<Vec<String>, XattrError>;
    fn remove_xattr(&self, path: &Path, name: &str) -> Result<(), XattrError>;
}

pub struct XattrManager {
    pub branches: Vec<Arc<Branch>>,
    pub getxattr_policy: Box<dyn SearchPolicy>,
    pub setxattr_policy: Box<dyn ActionPolicy>,
    pub listxattr_policy: Box<dyn SearchPolicy>,
    pub removexattr_policy: Box<dyn ActionPolicy>,
}

impl XattrManager {
    pub fn new(
        branches: Vec<Arc<Branch>>,
        getxattr_policy: Box<dyn SearchPolicy>,
        setxattr_policy: Box<dyn ActionPolicy>,
        listxattr_policy: Box<dyn SearchPolicy>,
        removexattr_policy: Box<dyn ActionPolicy>,
    ) -> Self {
        Self {
            branches,
            getxattr_policy,
            setxattr_policy,
            listxattr_policy,
            removexattr_policy,
        }
    }
    
    pub fn get_xattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, XattrError> {
        let _span = tracing::info_span!("xattr::get_xattr", path = ?path, name).entered();
        
        // Use search policy to find file
        tracing::debug!("Searching for file using getxattr policy");
        let branches = match self.getxattr_policy.search_branches(&self.branches, path) {
            Ok(branches) => branches,
            Err(_) => return Err(XattrError::NotFound),
        };
        
        if branches.is_empty() {
            return Err(XattrError::NotFound);
        }
        
        // Get xattr from first found branch
        let full_path = branches[0].full_path(path);
        tracing::debug!("Getting xattr from branch {:?}", branches[0].path);
        match self.get_xattr_from_path(&full_path, name) {
            Ok(value) => {
                tracing::info!("Successfully retrieved xattr {} ({} bytes)", name, value.len());
                Ok(value)
            }
            Err(e) => {
                tracing::warn!("Failed to get xattr {}: {:?}", name, e);
                Err(e)
            }
        }
    }
    
    pub fn set_xattr(&self, path: &Path, name: &str, value: &[u8], flags: XattrFlags) -> Result<(), XattrError> {
        // Block setting mergerfs special attributes
        if name.starts_with("user.mergerfs.") {
            return Err(XattrError::PermissionDenied);
        }
        
        // Use action policy to get target branches
        let branches = match self.setxattr_policy.select_branches(&self.branches, path) {
            Ok(branches) => branches,
            Err(_) => return Err(XattrError::NotFound),
        };
        
        let mut rv = PolicyRV::default();
        
        for branch in &branches {
            let full_path = branch.full_path(path);
            match self.set_xattr_on_path(&full_path, name, value, flags) {
                Ok(_) => rv.add_success(),
                Err(e) => rv.add_error(branch.path.to_string_lossy().to_string(), e),
            }
        }
        
        self.process_policy_rv(rv, path)
    }
    
    pub fn list_xattr(&self, path: &Path) -> Result<Vec<String>, XattrError> {
        // Use search policy to find file
        let branches = match self.listxattr_policy.search_branches(&self.branches, path) {
            Ok(branches) => branches,
            Err(_) => return Err(XattrError::NotFound),
        };
        
        if branches.is_empty() {
            return Err(XattrError::NotFound);
        }
        
        // List from first found branch
        let full_path = branches[0].full_path(path);
        self.list_xattr_from_path(&full_path)
    }
    
    pub fn remove_xattr(&self, path: &Path, name: &str) -> Result<(), XattrError> {
        // Block removing mergerfs special attributes
        if name.starts_with("user.mergerfs.") {
            return Err(XattrError::PermissionDenied);
        }
        
        // Use action policy
        let branches = match self.removexattr_policy.select_branches(&self.branches, path) {
            Ok(branches) => branches,
            Err(_) => return Err(XattrError::NotFound),
        };
        
        let mut rv = PolicyRV::default();
        
        for branch in &branches {
            let full_path = branch.full_path(path);
            match self.remove_xattr_from_path(&full_path, name) {
                Ok(_) => rv.add_success(),
                Err(e) => rv.add_error(branch.path.to_string_lossy().to_string(), e),
            }
        }
        
        self.process_policy_rv(rv, path)
    }
    
    // Helper methods for actual xattr operations
    fn get_xattr_from_path(&self, path: &Path, name: &str) -> Result<Vec<u8>, XattrError> {
        match xattr::get(path, name) {
            Ok(Some(value)) => Ok(value),
            Ok(None) => Err(XattrError::NotFound),
            Err(e) => self.map_io_error(e),
        }
    }
    
    fn set_xattr_on_path(&self, path: &Path, name: &str, value: &[u8], flags: XattrFlags) -> Result<(), XattrError> {
        // Note: xattr crate doesn't directly support flags, so we need to check existence first
        let exists = xattr::get(path, name).map(|v| v.is_some()).unwrap_or(false);
        
        match flags {
            XattrFlags::Create if exists => return Err(XattrError::InvalidArgument),
            XattrFlags::Replace if !exists => return Err(XattrError::NotFound),
            _ => {}
        }
        
        match xattr::set(path, name, value) {
            Ok(_) => Ok(()),
            Err(e) => self.map_io_error(e),
        }
    }
    
    fn list_xattr_from_path(&self, path: &Path) -> Result<Vec<String>, XattrError> {
        match xattr::list(path) {
            Ok(attrs) => {
                Ok(attrs
                    .filter_map(|attr| attr.into_string().ok())
                    .collect())
            }
            Err(e) => self.map_io_error(e),
        }
    }
    
    fn remove_xattr_from_path(&self, path: &Path, name: &str) -> Result<(), XattrError> {
        match xattr::remove(path, name) {
            Ok(_) => Ok(()),
            Err(e) => self.map_io_error(e),
        }
    }
    
    fn map_io_error<T>(&self, error: std::io::Error) -> Result<T, XattrError> {
        use std::io::ErrorKind;
        
        match error.kind() {
            ErrorKind::NotFound => Err(XattrError::NotFound),
            ErrorKind::PermissionDenied => Err(XattrError::PermissionDenied),
            _ => {
                // Check raw OS error for more specific errors
                if let Some(errno) = error.raw_os_error() {
                    match errno {
                        61 => Err(XattrError::NotFound), // ENOATTR/ENODATA
                        36 => Err(XattrError::NameTooLong), // ENAMETOOLONG
                        7 => Err(XattrError::ValueTooLarge), // E2BIG
                        95 => Err(XattrError::NotSupported), // ENOTSUP
                        _ => Err(XattrError::Io(error)),
                    }
                } else {
                    Err(XattrError::Io(error))
                }
            }
        }
    }
    
    fn process_policy_rv(&self, rv: PolicyRV, path: &Path) -> Result<(), XattrError> {
        // All succeeded
        if rv.all_succeeded() {
            return Ok(());
        }
        
        // All failed - return first error
        if rv.all_failed() {
            if let Some(err) = rv.first_error() {
                return match err {
                    XattrError::NotFound => Err(XattrError::NotFound),
                    XattrError::PermissionDenied => Err(XattrError::PermissionDenied),
                    XattrError::NameTooLong => Err(XattrError::NameTooLong),
                    XattrError::ValueTooLarge => Err(XattrError::ValueTooLarge),
                    XattrError::NotSupported => Err(XattrError::NotSupported),
                    XattrError::InvalidArgument => Err(XattrError::InvalidArgument),
                    XattrError::Io(io_err) => Err(XattrError::Io(std::io::Error::new(io_err.kind(), io_err.to_string()))),
                };
            }
            return Err(XattrError::NotFound);
        }
        
        // Mixed results - check if target branch had an error
        // Use getxattr policy to find the "authoritative" branch
        if let Ok(branches) = self.getxattr_policy.search_branches(&self.branches, path) {
            if let Some(target_branch) = branches.first() {
                let target_path = target_branch.path.to_string_lossy().to_string();
                
                // Check if target branch had an error
                for (branch_path, error) in &rv.errors {
                    if branch_path == &target_path {
                        return match error {
                            XattrError::NotFound => Err(XattrError::NotFound),
                            XattrError::PermissionDenied => Err(XattrError::PermissionDenied),
                            XattrError::NameTooLong => Err(XattrError::NameTooLong),
                            XattrError::ValueTooLarge => Err(XattrError::ValueTooLarge),
                            XattrError::NotSupported => Err(XattrError::NotSupported),
                            XattrError::InvalidArgument => Err(XattrError::InvalidArgument),
                            XattrError::Io(io_err) => Err(XattrError::Io(std::io::Error::new(io_err.kind(), io_err.to_string()))),
                        };
                    }
                }
            }
        }
        
        // Target branch succeeded or couldn't determine
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::policy::{FirstFoundSearchPolicy, AllActionPolicy};
    use tempfile::TempDir;
    use std::fs;
    
    fn create_test_manager() -> (Vec<TempDir>, XattrManager) {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1, branch2];
        
        let manager = XattrManager::new(
            branches,
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
            Box::new(FirstFoundSearchPolicy),
            Box::new(AllActionPolicy::new()),
        );
        
        (vec![temp1, temp2], manager)
    }
    
    #[test]
    fn test_xattr_basic_operations() {
        let (_temps, manager) = create_test_manager();
        
        // Create a test file
        let test_path = Path::new("test.txt");
        let full_path = manager.branches[0].full_path(test_path);
        fs::write(&full_path, b"test content").unwrap();
        
        // Set an xattr
        let attr_name = "user.test_attr";
        let attr_value = b"test value";
        
        manager.set_xattr(test_path, attr_name, attr_value, XattrFlags::None).unwrap();
        
        // Get the xattr
        let retrieved = manager.get_xattr(test_path, attr_name).unwrap();
        assert_eq!(retrieved, attr_value);
        
        // List xattrs
        let attrs = manager.list_xattr(test_path).unwrap();
        assert!(attrs.contains(&attr_name.to_string()));
        
        // Remove xattr
        manager.remove_xattr(test_path, attr_name).unwrap();
        
        // Verify it's gone
        assert!(manager.get_xattr(test_path, attr_name).is_err());
    }
    
    #[test]
    fn test_mergerfs_special_attrs_blocked() {
        let (_temps, manager) = create_test_manager();
        
        // Create a test file
        let test_path = Path::new("test.txt");
        let full_path = manager.branches[0].full_path(test_path);
        fs::write(&full_path, b"test content").unwrap();
        
        // Try to set a mergerfs special attribute
        let result = manager.set_xattr(
            test_path, 
            "user.mergerfs.basepath", 
            b"should fail", 
            XattrFlags::None
        );
        
        assert!(matches!(result, Err(XattrError::PermissionDenied)));
        
        // Try to remove a mergerfs special attribute
        let result = manager.remove_xattr(test_path, "user.mergerfs.basepath");
        assert!(matches!(result, Err(XattrError::PermissionDenied)));
    }
}