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
pub use action::AllActionPolicy;
pub use action::existing_path_all::ExistingPathAllActionPolicy;
pub use action::existing_path_first_found::ExistingPathFirstFoundActionPolicy;

pub use create::{
    FirstFoundCreatePolicy,
    LeastFreeSpaceCreatePolicy,
    MostFreeSpaceCreatePolicy,
    RandomCreatePolicy,
    ExistingPathMostFreeSpaceCreatePolicy,
    ProportionalFillRandomDistributionCreatePolicy,
};

pub use search::{
    FirstFoundSearchPolicy,
};
pub use search::all::AllSearchPolicy;
pub use search::newest::NewestSearchPolicy;

/// Create a policy instance from its name
pub fn create_policy_from_name(name: &str) -> Option<Box<dyn CreatePolicy>> {
    match name {
        "ff" => Some(Box::new(FirstFoundCreatePolicy::new())),
        "mfs" => Some(Box::new(MostFreeSpaceCreatePolicy::new())),
        "lfs" => Some(Box::new(LeastFreeSpaceCreatePolicy::new())),
        "rand" => Some(Box::new(RandomCreatePolicy::new())),
        "epmfs" => Some(Box::new(ExistingPathMostFreeSpaceCreatePolicy::new())),
        "pfrd" => Some(Box::new(ProportionalFillRandomDistributionCreatePolicy::new())),
        _ => None,
    }
}