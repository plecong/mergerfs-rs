use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub enum BranchMode {
    ReadWrite,
    ReadOnly,
}

#[derive(Debug)]
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

    pub fn full_path(&self, relative_path: &Path) -> PathBuf {
        self.path.join(relative_path.strip_prefix("/").unwrap_or(relative_path))
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