pub mod action;
pub mod create;
pub mod error;
pub mod traits;
pub mod utils;

// Re-export commonly used items
pub use error::PolicyError;
pub use traits::{ActionPolicy, CreatePolicy, SearchPolicy};
pub use utils::DiskSpace;

// Re-export all policy implementations
pub use action::{
    AllActionPolicy,
    ExistingPathAllActionPolicy,
    ExistingPathFirstFoundActionPolicy,
};

pub use create::{
    FirstFoundCreatePolicy,
    LeastFreeSpaceCreatePolicy,
    MostFreeSpaceCreatePolicy,
};