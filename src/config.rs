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

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum RenameEXDEV {
    Passthrough, // Return EXDEV error to caller
    RelSymlink,  // Create relative symlinks
    AbsSymlink,  // Create absolute symlinks
}

impl Default for RenameEXDEV {
    fn default() -> Self {
        RenameEXDEV::Passthrough
    }
}

#[derive(Debug, Clone)]
pub struct MoveOnENOSPC {
    pub enabled: bool,
    pub policy_name: String,  // Store policy name, will be resolved at runtime
}

impl Default for MoveOnENOSPC {
    fn default() -> Self {
        Self {
            enabled: true,
            policy_name: "pfrd".to_string(),  // Default to pfrd (proportional fill random distribution)
        }
    }
}

#[derive(Debug, Clone)]
pub struct Config {
    pub statfs_mode: StatFSMode,
    pub statfs_ignore: StatFSIgnore,
    pub mountpoint: PathBuf,
    pub ignore_path_preserving_on_rename: bool,
    pub rename_exdev: RenameEXDEV,
    pub moveonenospc: MoveOnENOSPC,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            statfs_mode: StatFSMode::default(),
            statfs_ignore: StatFSIgnore::default(),
            mountpoint: PathBuf::from("/mnt/mergerfs"),
            ignore_path_preserving_on_rename: false,
            rename_exdev: RenameEXDEV::default(),
            moveonenospc: MoveOnENOSPC::default(),
        }
    }
}

pub fn create_config() -> ConfigRef {
    Arc::new(RwLock::new(Config::default()))
}