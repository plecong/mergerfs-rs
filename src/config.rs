use std::path::PathBuf;
use std::sync::Arc;
use parking_lot::RwLock;

pub type ConfigRef = Arc<RwLock<Config>>;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StatFSMode {
    Base,  // Use base branch paths
    Full,  // Use full path (branch + fuse path)
}

impl Default for StatFSMode {
    fn default() -> Self {
        StatFSMode::Base
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StatFSIgnore {
    None,      // Don't ignore any branches
    ReadOnly,  // Ignore read-only branches for available space
    NoCreate,  // Ignore no-create branches for available space
}

impl Default for StatFSIgnore {
    fn default() -> Self {
        StatFSIgnore::None
    }
}

#[derive(Debug, Clone)]
pub struct Config {
    pub statfs_mode: StatFSMode,
    pub statfs_ignore: StatFSIgnore,
    pub mountpoint: PathBuf,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            statfs_mode: StatFSMode::default(),
            statfs_ignore: StatFSIgnore::default(),
            mountpoint: PathBuf::from("/mnt/mergerfs"),
        }
    }
}

pub fn create_config() -> ConfigRef {
    Arc::new(RwLock::new(Config::default()))
}