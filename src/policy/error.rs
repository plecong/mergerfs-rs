use thiserror::Error;

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