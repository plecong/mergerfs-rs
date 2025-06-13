pub mod first_found;
pub mod least_free_space;
pub mod most_free_space;
pub mod random;

pub use first_found::FirstFoundCreatePolicy;
pub use least_free_space::LeastFreeSpaceCreatePolicy;
pub use most_free_space::MostFreeSpaceCreatePolicy;
pub use random::RandomCreatePolicy;