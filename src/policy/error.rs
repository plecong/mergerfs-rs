use thiserror::Error;

#[derive(Debug, Error)]
pub enum PolicyError {
    #[error("No suitable branches found")]
    NoBranchesAvailable,
    #[error("All branches are read-only")]
    ReadOnlyFilesystem,
    #[error("Path not found")]
    PathNotFound,
    #[error("No space left on device")]
    NoSpace,
    #[error("I/O error: {0}")]
    IoError(#[from] std::io::Error),
}

impl Clone for PolicyError {
    fn clone(&self) -> Self {
        match self {
            PolicyError::NoBranchesAvailable => PolicyError::NoBranchesAvailable,
            PolicyError::ReadOnlyFilesystem => PolicyError::ReadOnlyFilesystem,
            PolicyError::PathNotFound => PolicyError::PathNotFound,
            PolicyError::NoSpace => PolicyError::NoSpace,
            PolicyError::IoError(e) => PolicyError::IoError(std::io::Error::new(e.kind(), e.to_string())),
        }
    }
}

impl PolicyError {
    pub fn errno(&self) -> i32 {
        // Standard errno constants compatible with MUSL
        const ENOENT: i32 = 2;
        const EROFS: i32 = 30;
        const EIO: i32 = 5;
        const ENOSPC: i32 = 28;
        
        match self {
            PolicyError::NoBranchesAvailable => ENOENT,
            PolicyError::ReadOnlyFilesystem => EROFS,
            PolicyError::PathNotFound => ENOENT,
            PolicyError::NoSpace => ENOSPC,
            PolicyError::IoError(e) => e.raw_os_error().unwrap_or(EIO),
        }
    }
    
    pub fn from_errno(errno: i32) -> Self {
        // Standard errno constants compatible with MUSL
        const EROFS: i32 = 30;
        
        match errno {
            EROFS => PolicyError::ReadOnlyFilesystem,
            _ => PolicyError::IoError(std::io::Error::from_raw_os_error(errno)),
        }
    }
}