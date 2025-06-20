use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BranchMode {
    ReadWrite,
    ReadOnly,
    NoCreate,  // Branch can be read and modified but not used for new file creation
}

#[derive(Debug, PartialEq)]
pub struct Branch {
    pub path: PathBuf,
    pub mode: BranchMode,
}

impl Branch {
    pub fn new(path: PathBuf, mode: BranchMode) -> Self {
        Self { path, mode }
    }

    pub fn allows_create(&self) -> bool {
        matches!(self.mode, BranchMode::ReadWrite)
    }
    
    pub fn is_readonly(&self) -> bool {
        matches!(self.mode, BranchMode::ReadOnly)
    }
    
    pub fn is_no_create(&self) -> bool {
        matches!(self.mode, BranchMode::NoCreate)
    }
    
    pub fn is_readonly_or_no_create(&self) -> bool {
        matches!(self.mode, BranchMode::ReadOnly | BranchMode::NoCreate)
    }

    pub fn full_path(&self, relative_path: &Path) -> PathBuf {
        self.path.join(relative_path.strip_prefix("/").unwrap_or(relative_path))
    }
    
    pub fn free_space(&self) -> Result<u64, std::io::Error> {
        use nix::sys::statvfs::statvfs;
        
        let stat = statvfs(&self.path).map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::Other, e)
        })?;
        
        // Calculate free space in bytes
        // Use blocks_available (f_bavail - blocks available to unprivileged users)
        let free_bytes = stat.blocks_available() as u64 * stat.fragment_size() as u64;
        Ok(free_bytes)
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_branch_creation() {
        let temp_dir = TempDir::new().unwrap();
        let branch = Branch::new(temp_dir.path().to_path_buf(), BranchMode::ReadWrite);
        
        assert!(branch.allows_create());
        assert_eq!(branch.path, temp_dir.path());
    }

    #[test]
    fn test_branch_readonly() {
        let temp_dir = TempDir::new().unwrap();
        let branch = Branch::new(temp_dir.path().to_path_buf(), BranchMode::ReadOnly);
        
        assert!(!branch.allows_create());
    }

    #[test]
    fn test_full_path() {
        let temp_dir = TempDir::new().unwrap();
        let branch = Branch::new(temp_dir.path().to_path_buf(), BranchMode::ReadWrite);
        
        let full_path = branch.full_path(Path::new("test.txt"));
        assert_eq!(full_path, temp_dir.path().join("test.txt"));
        
        let full_path_abs = branch.full_path(Path::new("/test.txt"));
        assert_eq!(full_path_abs, temp_dir.path().join("test.txt"));
    }
}