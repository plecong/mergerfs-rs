use super::XattrError;
use crate::file_ops::FileManager;
use std::path::Path;
use std::sync::Arc;

pub struct MergerfsXattrHandler {
    pub file_manager: Arc<FileManager>,
}

impl MergerfsXattrHandler {
    pub fn new(file_manager: Arc<FileManager>) -> Self {
        Self { file_manager }
    }
    
    pub fn handle_special_attr(&self, path: &Path, name: &str) -> Option<Result<Vec<u8>, XattrError>> {
        match name {
            "user.mergerfs.basepath" => Some(self.get_basepath(path)),
            "user.mergerfs.relpath" => Some(self.get_relpath(path)),
            "user.mergerfs.fullpath" => Some(self.get_fullpath(path)),
            "user.mergerfs.allpaths" => Some(self.get_allpaths(path)),
            _ => None,
        }
    }
    
    fn get_basepath(&self, path: &Path) -> Result<Vec<u8>, XattrError> {
        // Find which branch contains the file
        for branch in &self.file_manager.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                return Ok(branch.path.to_string_lossy().as_bytes().to_vec());
            }
        }
        Err(XattrError::NotFound)
    }
    
    fn get_relpath(&self, path: &Path) -> Result<Vec<u8>, XattrError> {
        // The relative path is just the path itself
        Ok(path.to_string_lossy().as_bytes().to_vec())
    }
    
    fn get_fullpath(&self, path: &Path) -> Result<Vec<u8>, XattrError> {
        // Find the full path to the actual file
        for branch in &self.file_manager.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                return Ok(full_path.to_string_lossy().as_bytes().to_vec());
            }
        }
        Err(XattrError::NotFound)
    }
    
    fn get_allpaths(&self, path: &Path) -> Result<Vec<u8>, XattrError> {
        let mut all_paths = Vec::new();
        let mut found_any = false;
        
        for branch in &self.file_manager.branches {
            let full_path = branch.full_path(path);
            if full_path.exists() {
                if found_any {
                    all_paths.push(0); // Null separator
                }
                all_paths.extend_from_slice(full_path.to_string_lossy().as_bytes());
                found_any = true;
            }
        }
        
        if found_any {
            Ok(all_paths)
        } else {
            Err(XattrError::NotFound)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::branch::{Branch, BranchMode};
    use crate::policy::FirstFoundCreatePolicy;
    use tempfile::TempDir;
    use std::fs;
    
    #[test]
    fn test_special_attrs() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        
        let branch1 = Arc::new(Branch::new(temp1.path().to_path_buf(), BranchMode::ReadWrite));
        let branch2 = Arc::new(Branch::new(temp2.path().to_path_buf(), BranchMode::ReadWrite));
        
        let branches = vec![branch1.clone(), branch2.clone()];
        let file_manager = Arc::new(FileManager::new(branches, Box::new(FirstFoundCreatePolicy)));
        
        let handler = MergerfsXattrHandler::new(file_manager);
        
        // Create test file in first branch
        let test_path = Path::new("test.txt");
        let full_path1 = branch1.full_path(test_path);
        fs::write(&full_path1, b"content").unwrap();
        
        // Test basepath
        let result = handler.get_basepath(test_path).unwrap();
        assert_eq!(result, temp1.path().to_string_lossy().as_bytes());
        
        // Test relpath
        let result = handler.get_relpath(test_path).unwrap();
        assert_eq!(result, b"test.txt");
        
        // Test fullpath
        let result = handler.get_fullpath(test_path).unwrap();
        assert_eq!(result, full_path1.to_string_lossy().as_bytes());
        
        // Create same file in second branch
        let full_path2 = branch2.full_path(test_path);
        fs::write(&full_path2, b"content2").unwrap();
        
        // Test allpaths
        let result = handler.get_allpaths(test_path).unwrap();
        let result_str = String::from_utf8_lossy(&result);
        assert!(result_str.contains(&full_path1.to_string_lossy().to_string()));
        assert!(result_str.contains(&full_path2.to_string_lossy().to_string()));
        assert!(result.contains(&0)); // Null separator
    }
}