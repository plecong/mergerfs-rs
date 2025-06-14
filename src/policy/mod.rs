pub mod action;
pub mod create;
pub mod search;
pub mod error;
pub mod traits;
pub mod utils;

// Re-export commonly used items
pub use error::PolicyError;
pub use traits::{ActionPolicy, CreatePolicy, SearchPolicy};

// Re-export all policy implementations
pub use action::{
    AllActionPolicy,
    existing_path_all::ExistingPathAllActionPolicy,
    existing_path_first_found::ExistingPathFirstFoundActionPolicy,
};

pub use create::{
    FirstFoundCreatePolicy,
    LeastFreeSpaceCreatePolicy,
    MostFreeSpaceCreatePolicy,
    RandomCreatePolicy,
};

pub use search::{
    AllSearchPolicy,
    FirstFoundSearchPolicy,
    NewestSearchPolicy,
};