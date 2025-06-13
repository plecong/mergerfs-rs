use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

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

#[derive(Debug, Error)]
pub enum PolicyError {
    #[error("No suitable branches found")]
    NoBranchesAvailable,
    #[error("All branches are read-only")]
    ReadOnlyFilesystem,
    #[error("I/O error: {0}")]
    IoError(#[from] std::io::Error),
}

impl PolicyError {
    pub fn errno(&self) -> i32 {
        // Standard errno constants compatible with MUSL
        const ENOENT: i32 = 2;
        const EROFS: i32 = 30;
        const EIO: i32 = 5;
        
        match self {
            PolicyError::NoBranchesAvailable => ENOENT,
            PolicyError::ReadOnlyFilesystem => EROFS,
            PolicyError::IoError(e) => e.raw_os_error().unwrap_or(EIO),
        }
    }
}

pub trait CreatePolicy: Send + Sync {
    fn name(&self) -> &'static str;
    fn select_branch(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Arc<Branch>, PolicyError>;
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