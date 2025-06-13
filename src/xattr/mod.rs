use thiserror::Error;

pub mod operations;
pub mod special_attrs;

#[cfg(test)]
mod xattr_tests;

pub use operations::XattrManager;

#[derive(Debug, Error)]
pub enum XattrError {
    #[error("Attribute not found")]
    NotFound,
    #[error("Permission denied")]
    PermissionDenied,
    #[error("Attribute name too long")]
    NameTooLong,
    #[error("Value too large")]
    ValueTooLarge,
    #[error("Not supported")]
    NotSupported,
    #[error("Invalid argument")]
    InvalidArgument,
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

impl XattrError {
    pub fn errno(&self) -> i32 {
        // Standard errno constants compatible with MUSL
        const ENOATTR: i32 = 61;  // No such attribute (Linux)
        const ENODATA: i32 = 61;  // No data available (alias for ENOATTR)
        const EPERM: i32 = 1;     // Operation not permitted
        const ENAMETOOLONG: i32 = 36; // File name too long
        const E2BIG: i32 = 7;     // Argument list too long
        const ENOTSUP: i32 = 95;  // Not supported
        const EINVAL: i32 = 22;   // Invalid argument
        const EIO: i32 = 5;       // I/O error
        
        match self {
            XattrError::NotFound => ENOATTR,
            XattrError::PermissionDenied => EPERM,
            XattrError::NameTooLong => ENAMETOOLONG,
            XattrError::ValueTooLarge => E2BIG,
            XattrError::NotSupported => ENOTSUP,
            XattrError::InvalidArgument => EINVAL,
            XattrError::Io(_) => EIO,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub enum XattrFlags {
    Create,  // XATTR_CREATE - fail if exists
    Replace, // XATTR_REPLACE - fail if doesn't exist
    None,    // Default - create or replace
}

// Policy return value for tracking multi-branch operations
#[derive(Debug, Default)]
pub struct PolicyRV {
    pub successes: usize,
    pub errors: Vec<(String, XattrError)>, // (branch_path, error)
}

impl PolicyRV {
    pub fn add_success(&mut self) {
        self.successes += 1;
    }
    
    pub fn add_error(&mut self, branch_path: String, error: XattrError) {
        self.errors.push((branch_path, error));
    }
    
    pub fn all_failed(&self) -> bool {
        self.successes == 0 && !self.errors.is_empty()
    }
    
    pub fn all_succeeded(&self) -> bool {
        self.errors.is_empty()
    }
    
    pub fn first_error(&self) -> Option<&XattrError> {
        self.errors.first().map(|(_, e)| e)
    }
}