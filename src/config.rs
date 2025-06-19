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

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CacheFiles {
    Libfuse,    // Use libfuse default (always cache)
    Off,        // Disable caching (direct_io)
    Partial,    // Cache writes but not reads
    Full,       // Enable full caching
    AutoFull,   // Like full but disables cache for specific processes
    PerProcess, // Process-specific caching
}

impl Default for CacheFiles {
    fn default() -> Self {
        CacheFiles::Libfuse
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
    pub cache_files: CacheFiles,
    pub direct_io_allow_mmap: bool,
    pub parallel_direct_writes: bool,
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
            cache_files: CacheFiles::default(),
            direct_io_allow_mmap: false,
            parallel_direct_writes: false,
        }
    }
}

impl Config {
    /// Determine if direct I/O should be used based on cache.files setting
    pub fn should_use_direct_io(&self) -> bool {
        matches!(self.cache_files, CacheFiles::Off)
    }
    
    /// Determine if kernel cache should be enabled
    pub fn should_enable_kernel_cache(&self) -> bool {
        matches!(self.cache_files, CacheFiles::Full | CacheFiles::AutoFull | CacheFiles::PerProcess)
    }
}

pub fn create_config() -> ConfigRef {
    Arc::new(RwLock::new(Config::default()))
}