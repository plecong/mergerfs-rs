# Configuration System Implementation in Rust

## Overview

This guide provides a comprehensive approach to implementing mergerfs's sophisticated configuration system in Rust, leveraging `serde`, type safety, runtime validation, and safe concurrent access patterns while maintaining compatibility with the original configuration API.

## Core Configuration Architecture

### Type-Safe Configuration Structure

```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergerFsConfig {
    // Core filesystem settings
    pub branches: BranchConfig,
    pub mount_point: PathBuf,
    pub fs_name: Option<String>,
    
    // Policy configuration
    pub function_policies: FunctionPolicies,
    pub category_policies: CategoryPolicies, // Legacy support
    
    // Caching configuration
    pub cache: CacheConfig,
    
    // I/O and performance settings
    pub io: IoConfig,
    
    // FUSE-specific settings
    pub fuse: FuseConfig,
    
    // Advanced features
    pub advanced: AdvancedConfig,
    
    // Internal settings (not user-configurable)
    #[serde(skip)]
    pub internal: InternalConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchConfig {
    pub paths: Vec<BranchPath>,
    pub min_free_space: u64,
    pub mount_timeout: Duration,
    pub mount_timeout_fail: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchPath {
    pub path: PathBuf,
    pub mode: BranchMode,
    pub min_free_space: Option<u64>, // Override global setting
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BranchMode {
    #[serde(rename = "rw")]
    ReadWrite,
    #[serde(rename = "ro")]
    ReadOnly,
    #[serde(rename = "nc")]
    NoCreate,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheConfig {
    pub files: CacheFilesMode,
    pub files_process_names: Vec<String>,
    pub attr_timeout: Duration,
    pub entry_timeout: Duration,
    pub negative_timeout: Duration,
    pub readdir: bool,
    pub statfs_timeout: Duration,
    pub symlinks: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum CacheFilesMode {
    #[serde(rename = "off")]
    Off,
    #[serde(rename = "partial")]
    Partial,
    #[serde(rename = "full")]
    Full,
    #[serde(rename = "auto-full")]
    AutoFull,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IoConfig {
    pub async_read: bool,
    pub direct_io: bool,
    pub direct_io_allow_mmap: bool,
    pub writeback_cache: bool,
    pub kernel_cache: bool,
    pub readahead: Option<u64>,
    pub parallel_direct_writes: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FuseConfig {
    pub read_thread_count: Option<u32>,
    pub process_thread_count: Option<u32>,
    pub process_thread_queue_depth: Option<u32>,
    pub pin_threads: String,
    pub msg_size: Option<u64>,
    pub export_support: bool,
    pub handle_killpriv: bool,
    pub handle_killpriv_v2: bool,
    pub kernel_permissions_check: bool,
    pub posix_acl: bool,
    pub readdirplus: bool,
    pub security_capability: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdvancedConfig {
    pub flush_on_close: FlushOnCloseMode,
    pub follow_symlinks: FollowSymlinksMode,
    pub inode_calc: InodeCalcMode,
    pub link_cow: bool,
    pub link_exdev: LinkExdevMode,
    pub move_on_enospc: MoveOnEnospaceMode,
    pub nfs_open_hack: NfsOpenHackMode,
    pub passthrough: PassthroughMode,
    pub rename_exdev: RenameExdevMode,
    pub statfs: StatfsMode,
    pub statfs_ignore: StatfsIgnoreMode,
    pub xattr: XattrMode,
    pub symlinkify: bool,
    pub symlinkify_timeout: Duration,
    pub nullrw: bool,
}

#[derive(Debug, Clone)]
pub struct InternalConfig {
    pub pid: Option<u32>,
    pub version: String,
    pub scheduling_priority: i32,
    pub srcmounts: Vec<String>,
}
```

### Validation Traits and Implementation

```rust
use std::fmt;

pub trait Validate {
    type Error: std::error::Error + Send + Sync + 'static;
    
    fn validate(&self) -> Result<(), Self::Error>;
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigValidationError {
    #[error("Invalid branch path: {path}")]
    InvalidBranchPath { path: String },
    
    #[error("Branch path does not exist: {path}")]
    BranchPathNotExists { path: String },
    
    #[error("Invalid mount point: {path}")]
    InvalidMountPoint { path: String },
    
    #[error("Invalid policy name: {policy} for function: {function}")]
    InvalidPolicy { policy: String, function: String },
    
    #[error("Cache timeout must be non-negative, got: {timeout:?}")]
    InvalidCacheTimeout { timeout: Duration },
    
    #[error("Thread count must be positive, got: {count}")]
    InvalidThreadCount { count: u32 },
    
    #[error("Min free space too large: {size}")]
    InvalidMinFreeSpace { size: u64 },
    
    #[error("Conflicting configuration: {message}")]
    ConflictingConfig { message: String },
    
    #[error("Required field missing: {field}")]
    RequiredFieldMissing { field: String },
}

impl Validate for MergerFsConfig {
    type Error = ConfigValidationError;
    
    fn validate(&self) -> Result<(), Self::Error> {
        // Validate branches
        self.branches.validate()?;
        
        // Validate mount point
        if !self.mount_point.is_absolute() {
            return Err(ConfigValidationError::InvalidMountPoint {
                path: self.mount_point.display().to_string(),
            });
        }
        
        // Validate policies
        self.function_policies.validate()?;
        
        // Validate cache config
        self.cache.validate()?;
        
        // Validate FUSE config
        self.fuse.validate()?;
        
        // Cross-validation
        self.validate_cross_dependencies()?;
        
        Ok(())
    }
}

impl MergerFsConfig {
    fn validate_cross_dependencies(&self) -> Result<(), ConfigValidationError> {
        // Example: writeback cache and direct I/O are incompatible
        if self.io.writeback_cache && self.io.direct_io {
            return Err(ConfigValidationError::ConflictingConfig {
                message: "writeback_cache and direct_io cannot both be enabled".to_string(),
            });
        }
        
        // Example: ensure at least one writable branch exists
        let has_writable = self.branches.paths.iter()
            .any(|bp| matches!(bp.mode, BranchMode::ReadWrite));
        
        if !has_writable {
            return Err(ConfigValidationError::ConflictingConfig {
                message: "At least one branch must be writable".to_string(),
            });
        }
        
        Ok(())
    }
}

impl Validate for BranchConfig {
    type Error = ConfigValidationError;
    
    fn validate(&self) -> Result<(), Self::Error> {
        if self.paths.is_empty() {
            return Err(ConfigValidationError::RequiredFieldMissing {
                field: "branches.paths".to_string(),
            });
        }
        
        for branch_path in &self.paths {
            branch_path.validate()?;
        }
        
        Ok(())
    }
}

impl Validate for BranchPath {
    type Error = ConfigValidationError;
    
    fn validate(&self) -> Result<(), Self::Error> {
        if !self.path.is_absolute() {
            return Err(ConfigValidationError::InvalidBranchPath {
                path: self.path.display().to_string(),
            });
        }
        
        if !self.path.exists() {
            return Err(ConfigValidationError::BranchPathNotExists {
                path: self.path.display().to_string(),
            });
        }
        
        if let Some(min_free) = self.min_free_space {
            if min_free > 1024 * 1024 * 1024 * 1024 { // 1TB sanity check
                return Err(ConfigValidationError::InvalidMinFreeSpace { size: min_free });
            }
        }
        
        Ok(())
    }
}
```

### Configuration Parsing and Serialization

```rust
use std::str::FromStr;

// Custom deserializers for complex types
impl FromStr for BranchPath {
    type Err = ConfigValidationError;
    
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        // Parse format: "/path/to/branch=mode:min_free_space"
        let parts: Vec<&str> = s.split('=').collect();
        let path = PathBuf::from(parts[0]);
        
        let (mode, min_free_space) = if parts.len() > 1 {
            let mode_parts: Vec<&str> = parts[1].split(':').collect();
            let mode = BranchMode::from_str(mode_parts[0])?;
            let min_free = if mode_parts.len() > 1 {
                Some(mode_parts[1].parse().map_err(|_| {
                    ConfigValidationError::InvalidMinFreeSpace {
                        size: 0,
                    }
                })?)
            } else {
                None
            };
            (mode, min_free)
        } else {
            (BranchMode::ReadWrite, None)
        };
        
        Ok(BranchPath {
            path,
            mode,
            min_free_space,
        })
    }
}

impl FromStr for BranchMode {
    type Err = ConfigValidationError;
    
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "rw" | "readwrite" => Ok(BranchMode::ReadWrite),
            "ro" | "readonly" => Ok(BranchMode::ReadOnly),
            "nc" | "nocreate" => Ok(BranchMode::NoCreate),
            _ => Err(ConfigValidationError::InvalidBranchPath {
                path: format!("Invalid mode: {}", s),
            }),
        }
    }
}

// Duration parsing for human-readable formats
pub fn parse_duration(s: &str) -> Result<Duration, std::num::ParseIntError> {
    if s.ends_with("ms") {
        Ok(Duration::from_millis(s.trim_end_matches("ms").parse()?))
    } else if s.ends_with('s') {
        Ok(Duration::from_secs(s.trim_end_matches('s').parse()?))
    } else if s.ends_with('m') {
        Ok(Duration::from_secs(s.trim_end_matches('m').parse::<u64>()? * 60))
    } else if s.ends_with('h') {
        Ok(Duration::from_secs(s.trim_end_matches('h').parse::<u64>()? * 3600))
    } else {
        // Default to seconds
        Ok(Duration::from_secs(s.parse()?))
    }
}

// Custom serializer for Duration to human-readable format
mod duration_serde {
    use super::*;
    use serde::{Deserializer, Serializer};
    
    pub fn serialize<S>(duration: &Duration, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let secs = duration.as_secs();
        if secs >= 3600 && secs % 3600 == 0 {
            serializer.serialize_str(&format!("{}h", secs / 3600))
        } else if secs >= 60 && secs % 60 == 0 {
            serializer.serialize_str(&format!("{}m", secs / 60))
        } else {
            serializer.serialize_str(&format!("{}s", secs))
        }
    }
    
    pub fn deserialize<'de, D>(deserializer: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        parse_duration(&s).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheConfig {
    pub files: CacheFilesMode,
    pub files_process_names: Vec<String>,
    
    #[serde(with = "duration_serde")]
    pub attr_timeout: Duration,
    
    #[serde(with = "duration_serde")]
    pub entry_timeout: Duration,
    
    #[serde(with = "duration_serde")]
    pub negative_timeout: Duration,
    
    pub readdir: bool,
    
    #[serde(with = "duration_serde")]
    pub statfs_timeout: Duration,
    
    pub symlinks: bool,
}
```

## Configuration Loading and Management

### Configuration Sources

```rust
use std::fs;
use std::env;

#[derive(Debug, Clone)]
pub enum ConfigSource {
    File(PathBuf),
    Environment,
    CommandLine(Vec<String>),
    Default,
}

pub struct ConfigLoader {
    sources: Vec<ConfigSource>,
}

impl ConfigLoader {
    pub fn new() -> Self {
        Self {
            sources: vec![ConfigSource::Default],
        }
    }
    
    pub fn add_file<P: Into<PathBuf>>(mut self, path: P) -> Self {
        self.sources.push(ConfigSource::File(path.into()));
        self
    }
    
    pub fn add_environment(mut self) -> Self {
        self.sources.push(ConfigSource::Environment);
        self
    }
    
    pub fn add_command_line(mut self, args: Vec<String>) -> Self {
        self.sources.push(ConfigSource::CommandLine(args));
        self
    }
    
    pub fn load(&self) -> Result<MergerFsConfig, ConfigLoadError> {
        let mut config = MergerFsConfig::default();
        
        for source in &self.sources {
            match source {
                ConfigSource::Default => {
                    // Already loaded
                }
                ConfigSource::File(path) => {
                    let file_config = self.load_from_file(path)?;
                    config = self.merge_configs(config, file_config)?;
                }
                ConfigSource::Environment => {
                    let env_config = self.load_from_environment()?;
                    config = self.merge_configs(config, env_config)?;
                }
                ConfigSource::CommandLine(args) => {
                    let cli_config = self.load_from_command_line(args)?;
                    config = self.merge_configs(config, cli_config)?;
                }
            }
        }
        
        config.validate().map_err(ConfigLoadError::Validation)?;
        Ok(config)
    }
    
    fn load_from_file(&self, path: &PathBuf) -> Result<MergerFsConfig, ConfigLoadError> {
        let content = fs::read_to_string(path)
            .map_err(|e| ConfigLoadError::FileRead { 
                path: path.clone(), 
                error: e 
            })?;
        
        match path.extension().and_then(|s| s.to_str()) {
            Some("json") => {
                serde_json::from_str(&content)
                    .map_err(|e| ConfigLoadError::JsonParse { 
                        path: path.clone(), 
                        error: e 
                    })
            }
            Some("yaml") | Some("yml") => {
                serde_yaml::from_str(&content)
                    .map_err(|e| ConfigLoadError::YamlParse { 
                        path: path.clone(), 
                        error: e 
                    })
            }
            Some("toml") => {
                toml::from_str(&content)
                    .map_err(|e| ConfigLoadError::TomlParse { 
                        path: path.clone(), 
                        error: e 
                    })
            }
            _ => {
                // Try to auto-detect format
                if let Ok(config) = serde_json::from_str(&content) {
                    Ok(config)
                } else if let Ok(config) = serde_yaml::from_str(&content) {
                    Ok(config)
                } else if let Ok(config) = toml::from_str(&content) {
                    Ok(config)
                } else {
                    Err(ConfigLoadError::UnknownFormat { path: path.clone() })
                }
            }
        }
    }
    
    fn load_from_environment(&self) -> Result<MergerFsConfig, ConfigLoadError> {
        let mut config = MergerFsConfig::default();
        
        // Map environment variables to config fields
        let env_mappings = [
            ("MERGERFS_BRANCHES", |config: &mut MergerFsConfig, value: String| {
                config.branches.paths = value.split(':')
                    .map(|s| BranchPath::from_str(s))
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(())
            }),
            ("MERGERFS_MOUNT_POINT", |config: &mut MergerFsConfig, value: String| {
                config.mount_point = PathBuf::from(value);
                Ok(())
            }),
            ("MERGERFS_CACHE_ATTR_TIMEOUT", |config: &mut MergerFsConfig, value: String| {
                config.cache.attr_timeout = parse_duration(&value)
                    .map_err(|_| ConfigValidationError::InvalidCacheTimeout { 
                        timeout: Duration::ZERO 
                    })?;
                Ok(())
            }),
            // Add more mappings as needed
        ];
        
        for (env_var, setter) in env_mappings.iter() {
            if let Ok(value) = env::var(env_var) {
                setter(&mut config, value)
                    .map_err(ConfigLoadError::Validation)?;
            }
        }
        
        Ok(config)
    }
    
    fn load_from_command_line(&self, args: &[String]) -> Result<MergerFsConfig, ConfigLoadError> {
        let mut config = MergerFsConfig::default();
        
        // Parse mount options format: -o key=value,key2=value2
        let mut i = 0;
        while i < args.len() {
            if args[i] == "-o" && i + 1 < args.len() {
                let options = &args[i + 1];
                for option in options.split(',') {
                    let parts: Vec<&str> = option.splitn(2, '=').collect();
                    if parts.len() == 2 {
                        self.apply_option(&mut config, parts[0], parts[1])?;
                    }
                }
                i += 2;
            } else {
                i += 1;
            }
        }
        
        Ok(config)
    }
    
    fn apply_option(
        &self,
        config: &mut MergerFsConfig,
        key: &str,
        value: &str,
    ) -> Result<(), ConfigLoadError> {
        match key {
            "branches" => {
                config.branches.paths = value.split(':')
                    .map(|s| BranchPath::from_str(s))
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(ConfigLoadError::Validation)?;
            }
            "func.create" => {
                config.function_policies.create = PolicyRef::new(value);
            }
            "func.search" => {
                config.function_policies.open = PolicyRef::new(value);
            }
            "cache.attr" => {
                config.cache.attr_timeout = parse_duration(value)
                    .map_err(|_| ConfigLoadError::Validation(
                        ConfigValidationError::InvalidCacheTimeout { 
                            timeout: Duration::ZERO 
                        }
                    ))?;
            }
            "async_read" => {
                config.io.async_read = value.parse()
                    .map_err(|_| ConfigLoadError::InvalidBoolValue { 
                        key: key.to_string(), 
                        value: value.to_string() 
                    })?;
            }
            _ => {
                return Err(ConfigLoadError::UnknownOption { 
                    key: key.to_string() 
                });
            }
        }
        Ok(())
    }
    
    fn merge_configs(
        &self,
        mut base: MergerFsConfig,
        overlay: MergerFsConfig,
    ) -> Result<MergerFsConfig, ConfigLoadError> {
        // Implement configuration merging logic
        // Later values override earlier ones
        
        if !overlay.branches.paths.is_empty() {
            base.branches = overlay.branches;
        }
        
        if overlay.mount_point != PathBuf::new() {
            base.mount_point = overlay.mount_point;
        }
        
        // Merge cache config
        if overlay.cache.attr_timeout != Duration::ZERO {
            base.cache.attr_timeout = overlay.cache.attr_timeout;
        }
        
        // Add more merging logic as needed
        
        Ok(base)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigLoadError {
    #[error("Failed to read config file {path}: {error}")]
    FileRead { path: PathBuf, error: std::io::Error },
    
    #[error("Failed to parse JSON config file {path}: {error}")]
    JsonParse { path: PathBuf, error: serde_json::Error },
    
    #[error("Failed to parse YAML config file {path}: {error}")]
    YamlParse { path: PathBuf, error: serde_yaml::Error },
    
    #[error("Failed to parse TOML config file {path}: {error}")]
    TomlParse { path: PathBuf, error: toml::de::Error },
    
    #[error("Unknown config format for file: {path}")]
    UnknownFormat { path: PathBuf },
    
    #[error("Unknown option: {key}")]
    UnknownOption { key: String },
    
    #[error("Invalid boolean value for {key}: {value}")]
    InvalidBoolValue { key: String, value: String },
    
    #[error("Validation error: {0}")]
    Validation(#[from] ConfigValidationError),
}
```

## Thread-Safe Configuration Management

### Runtime Configuration Updates

```rust
use std::sync::Arc;
use parking_lot::RwLock;
use tokio::sync::watch;

pub struct ConfigManager {
    config: Arc<RwLock<MergerFsConfig>>,
    update_sender: watch::Sender<ConfigUpdate>,
    update_receiver: watch::Receiver<ConfigUpdate>,
}

#[derive(Debug, Clone)]
pub struct ConfigUpdate {
    pub timestamp: std::time::SystemTime,
    pub changes: Vec<ConfigChange>,
}

#[derive(Debug, Clone)]
pub enum ConfigChange {
    BranchAdded(BranchPath),
    BranchRemoved(PathBuf),
    BranchModeChanged(PathBuf, BranchMode),
    PolicyChanged(String, String),
    CacheSettingChanged(String, String),
}

impl ConfigManager {
    pub fn new(config: MergerFsConfig) -> Self {
        let (update_sender, update_receiver) = watch::channel(ConfigUpdate {
            timestamp: std::time::SystemTime::now(),
            changes: vec![],
        });
        
        Self {
            config: Arc::new(RwLock::new(config)),
            update_sender,
            update_receiver,
        }
    }
    
    pub fn get_config(&self) -> ConfigReadGuard {
        ConfigReadGuard::new(self.config.clone())
    }
    
    pub fn update_config<F>(&self, updater: F) -> Result<(), ConfigUpdateError>
    where
        F: FnOnce(&mut MergerFsConfig) -> Result<Vec<ConfigChange>, ConfigUpdateError>,
    {
        let mut config = self.config.write();
        let changes = updater(&mut *config)?;
        
        // Validate the updated configuration
        config.validate()
            .map_err(ConfigUpdateError::Validation)?;
        
        // Notify subscribers of the update
        if !changes.is_empty() {
            let update = ConfigUpdate {
                timestamp: std::time::SystemTime::now(),
                changes,
            };
            
            let _ = self.update_sender.send(update);
        }
        
        Ok(())
    }
    
    pub fn subscribe_to_updates(&self) -> ConfigUpdateSubscriber {
        ConfigUpdateSubscriber {
            receiver: self.update_receiver.clone(),
        }
    }
    
    // Convenience methods for common updates
    pub fn add_branch(&self, branch: BranchPath) -> Result<(), ConfigUpdateError> {
        self.update_config(|config| {
            branch.validate().map_err(ConfigUpdateError::Validation)?;
            config.branches.paths.push(branch.clone());
            Ok(vec![ConfigChange::BranchAdded(branch)])
        })
    }
    
    pub fn remove_branch(&self, path: &PathBuf) -> Result<(), ConfigUpdateError> {
        self.update_config(|config| {
            let initial_len = config.branches.paths.len();
            config.branches.paths.retain(|bp| &bp.path != path);
            
            if config.branches.paths.len() == initial_len {
                return Err(ConfigUpdateError::BranchNotFound(path.clone()));
            }
            
            Ok(vec![ConfigChange::BranchRemoved(path.clone())])
        })
    }
    
    pub fn update_policy(
        &self,
        function: &str,
        policy: &str,
    ) -> Result<(), ConfigUpdateError> {
        self.update_config(|config| {
            match function {
                "create" => config.function_policies.create = PolicyRef::new(policy),
                "open" => config.function_policies.open = PolicyRef::new(policy),
                "mkdir" => config.function_policies.mkdir = PolicyRef::new(policy),
                // Add more functions as needed
                _ => return Err(ConfigUpdateError::UnknownFunction(function.to_string())),
            }
            
            Ok(vec![ConfigChange::PolicyChanged(
                function.to_string(),
                policy.to_string(),
            )])
        })
    }
}

pub struct ConfigReadGuard {
    config: Arc<RwLock<MergerFsConfig>>,
    _guard: parking_lot::RwLockReadGuard<'static, MergerFsConfig>,
}

impl ConfigReadGuard {
    fn new(config: Arc<RwLock<MergerFsConfig>>) -> Self {
        // SAFETY: We're extending the lifetime of the guard to 'static
        // This is safe because we hold an Arc to the config, ensuring it won't be dropped
        let guard = unsafe {
            std::mem::transmute::<
                parking_lot::RwLockReadGuard<'_, MergerFsConfig>,
                parking_lot::RwLockReadGuard<'static, MergerFsConfig>,
            >(config.read())
        };
        
        Self {
            config,
            _guard: guard,
        }
    }
    
    pub fn get(&self) -> &MergerFsConfig {
        &*self._guard
    }
}

pub struct ConfigUpdateSubscriber {
    receiver: watch::Receiver<ConfigUpdate>,
}

impl ConfigUpdateSubscriber {
    pub async fn wait_for_update(&mut self) -> Result<ConfigUpdate, ConfigUpdateError> {
        self.receiver.changed().await
            .map_err(|_| ConfigUpdateError::SubscriptionClosed)?;
        
        Ok(self.receiver.borrow().clone())
    }
    
    pub fn try_get_update(&mut self) -> Option<ConfigUpdate> {
        if self.receiver.has_changed().unwrap_or(false) {
            Some(self.receiver.borrow().clone())
        } else {
            None
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigUpdateError {
    #[error("Validation error: {0}")]
    Validation(#[from] ConfigValidationError),
    
    #[error("Branch not found: {0}")]
    BranchNotFound(PathBuf),
    
    #[error("Unknown function: {0}")]
    UnknownFunction(String),
    
    #[error("Subscription closed")]
    SubscriptionClosed,
    
    #[error("Update rejected: {reason}")]
    UpdateRejected { reason: String },
}
```

## Control File Interface

### Runtime Configuration via Control File

```rust
use std::collections::VecDeque;
use tokio::fs;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

pub struct ControlFileHandler {
    config_manager: Arc<ConfigManager>,
    command_history: Arc<RwLock<VecDeque<ControlCommand>>>,
}

#[derive(Debug, Clone)]
pub struct ControlCommand {
    pub timestamp: std::time::SystemTime,
    pub command: String,
    pub result: Result<String, String>,
}

impl ControlFileHandler {
    pub fn new(config_manager: Arc<ConfigManager>) -> Self {
        Self {
            config_manager,
            command_history: Arc::new(RwLock::new(VecDeque::with_capacity(100))),
        }
    }
    
    pub async fn handle_read(&self) -> Result<String, std::io::Error> {
        let config = self.config_manager.get_config();
        let mut output = String::new();
        
        // Output current configuration in key=value format
        output.push_str(&format!("branches={}\n", self.format_branches(&config.get().branches)));
        output.push_str(&format!("func.create={}\n", config.get().function_policies.create.name()));
        output.push_str(&format!("func.open={}\n", config.get().function_policies.open.name()));
        output.push_str(&format!("cache.attr={}\n", self.format_duration(&config.get().cache.attr_timeout)));
        output.push_str(&format!("cache.entry={}\n", self.format_duration(&config.get().cache.entry_timeout)));
        output.push_str(&format!("async_read={}\n", config.get().io.async_read));
        output.push_str(&format!("direct_io={}\n", config.get().io.direct_io));
        
        // Add command history
        output.push_str("\n# Recent commands:\n");
        let history = self.command_history.read();
        for cmd in history.iter().take(10) {
            output.push_str(&format!("# {} -> {:?}\n", cmd.command, cmd.result));
        }
        
        Ok(output)
    }
    
    pub async fn handle_write(&self, content: &str) -> Result<String, std::io::Error> {
        let mut responses = Vec::new();
        
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            
            let response = self.process_command(line).await;
            responses.push(format!("{}: {:?}", line, response));
            
            // Add to history
            let command = ControlCommand {
                timestamp: std::time::SystemTime::now(),
                command: line.to_string(),
                result: response.clone(),
            };
            
            let mut history = self.command_history.write();
            history.push_front(command);
            if history.len() > 100 {
                history.pop_back();
            }
        }
        
        Ok(responses.join("\n"))
    }
    
    async fn process_command(&self, command: &str) -> Result<String, String> {
        let parts: Vec<&str> = command.splitn(2, '=').collect();
        if parts.len() != 2 {
            return Err("Invalid command format. Use key=value".to_string());
        }
        
        let key = parts[0].trim();
        let value = parts[1].trim();
        
        match key {
            "branches" => {
                let branch_paths: Result<Vec<BranchPath>, _> = value
                    .split(':')
                    .map(|s| BranchPath::from_str(s.trim()))
                    .collect();
                
                match branch_paths {
                    Ok(paths) => {
                        self.config_manager
                            .update_config(|config| {
                                config.branches.paths = paths;
                                Ok(vec![ConfigChange::BranchRemoved(PathBuf::new())]) // Simplified
                            })
                            .map_err(|e| e.to_string())?;
                        Ok("Branches updated".to_string())
                    }
                    Err(e) => Err(format!("Invalid branch format: {}", e)),
                }
            }
            key if key.starts_with("func.") => {
                let function = &key[5..]; // Remove "func." prefix
                self.config_manager
                    .update_policy(function, value)
                    .map_err(|e| e.to_string())?;
                Ok(format!("Policy {} updated to {}", function, value))
            }
            "cache.attr" => {
                let duration = parse_duration(value)
                    .map_err(|e| format!("Invalid duration: {}", e))?;
                
                self.config_manager
                    .update_config(|config| {
                        config.cache.attr_timeout = duration;
                        Ok(vec![ConfigChange::CacheSettingChanged(
                            "attr_timeout".to_string(),
                            value.to_string(),
                        )])
                    })
                    .map_err(|e| e.to_string())?;
                Ok("Cache attribute timeout updated".to_string())
            }
            "async_read" => {
                let enabled = value.parse::<bool>()
                    .map_err(|_| "Invalid boolean value")?;
                
                self.config_manager
                    .update_config(|config| {
                        config.io.async_read = enabled;
                        Ok(vec![])
                    })
                    .map_err(|e| e.to_string())?;
                Ok(format!("Async read set to {}", enabled))
            }
            _ => Err(format!("Unknown configuration key: {}", key)),
        }
    }
    
    fn format_branches(&self, branches: &BranchConfig) -> String {
        branches
            .paths
            .iter()
            .map(|bp| {
                let mode_str = match bp.mode {
                    BranchMode::ReadWrite => "rw",
                    BranchMode::ReadOnly => "ro",
                    BranchMode::NoCreate => "nc",
                };
                
                if let Some(min_free) = bp.min_free_space {
                    format!("{}={}:{}", bp.path.display(), mode_str, min_free)
                } else {
                    format!("{}={}", bp.path.display(), mode_str)
                }
            })
            .collect::<Vec<_>>()
            .join(":")
    }
    
    fn format_duration(&self, duration: &Duration) -> String {
        let secs = duration.as_secs();
        if secs >= 3600 && secs % 3600 == 0 {
            format!("{}h", secs / 3600)
        } else if secs >= 60 && secs % 60 == 0 {
            format!("{}m", secs / 60)
        } else {
            format!("{}s", secs)
        }
    }
}
```

## Configuration Persistence

### Atomic Configuration Saves

```rust
use tokio::fs;
use std::path::Path;

pub struct ConfigPersister {
    config_path: PathBuf,
    backup_count: usize,
}

impl ConfigPersister {
    pub fn new(config_path: PathBuf, backup_count: usize) -> Self {
        Self {
            config_path,
            backup_count,
        }
    }
    
    pub async fn save_config(&self, config: &MergerFsConfig) -> Result<(), ConfigPersistError> {
        // Create backup of existing config
        if self.config_path.exists() {
            self.rotate_backups().await?;
        }
        
        // Serialize config
        let content = match self.config_path.extension().and_then(|s| s.to_str()) {
            Some("json") => serde_json::to_string_pretty(config)
                .map_err(ConfigPersistError::JsonSerialize)?,
            Some("yaml") | Some("yml") => serde_yaml::to_string(config)
                .map_err(ConfigPersistError::YamlSerialize)?,
            Some("toml") => toml::to_string_pretty(config)
                .map_err(ConfigPersistError::TomlSerialize)?,
            _ => serde_json::to_string_pretty(config)
                .map_err(ConfigPersistError::JsonSerialize)?,
        };
        
        // Atomic write using temporary file
        let temp_path = self.config_path.with_extension("tmp");
        fs::write(&temp_path, content).await
            .map_err(|e| ConfigPersistError::Write { 
                path: temp_path.clone(), 
                error: e 
            })?;
        
        // Atomic rename
        fs::rename(&temp_path, &self.config_path).await
            .map_err(|e| ConfigPersistError::Rename { 
                from: temp_path, 
                to: self.config_path.clone(), 
                error: e 
            })?;
        
        Ok(())
    }
    
    pub async fn load_config(&self) -> Result<MergerFsConfig, ConfigLoadError> {
        ConfigLoader::new()
            .add_file(self.config_path.clone())
            .load()
    }
    
    async fn rotate_backups(&self) -> Result<(), ConfigPersistError> {
        for i in (1..self.backup_count).rev() {
            let src = if i == 1 {
                self.config_path.clone()
            } else {
                self.backup_path(i - 1)
            };
            
            let dst = self.backup_path(i);
            
            if src.exists() {
                if let Some(parent) = dst.parent() {
                    fs::create_dir_all(parent).await
                        .map_err(|e| ConfigPersistError::BackupCreate { 
                            path: parent.to_path_buf(), 
                            error: e 
                        })?;
                }
                
                fs::copy(&src, &dst).await
                    .map_err(|e| ConfigPersistError::BackupCopy { 
                        from: src, 
                        to: dst, 
                        error: e 
                    })?;
            }
        }
        
        Ok(())
    }
    
    fn backup_path(&self, index: usize) -> PathBuf {
        self.config_path.with_extension(format!("bak.{}", index))
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigPersistError {
    #[error("Failed to serialize config as JSON: {0}")]
    JsonSerialize(serde_json::Error),
    
    #[error("Failed to serialize config as YAML: {0}")]
    YamlSerialize(serde_yaml::Error),
    
    #[error("Failed to serialize config as TOML: {0}")]
    TomlSerialize(toml::ser::Error),
    
    #[error("Failed to write config to {path}: {error}")]
    Write { path: PathBuf, error: std::io::Error },
    
    #[error("Failed to rename {from} to {to}: {error}")]
    Rename { from: PathBuf, to: PathBuf, error: std::io::Error },
    
    #[error("Failed to create backup directory {path}: {error}")]
    BackupCreate { path: PathBuf, error: std::io::Error },
    
    #[error("Failed to copy backup from {from} to {to}: {error}")]
    BackupCopy { from: PathBuf, to: PathBuf, error: std::io::Error },
}
```

## Testing Configuration System

### Configuration Testing Framework

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    
    struct ConfigTestFixture {
        temp_dir: TempDir,
        config_manager: ConfigManager,
    }
    
    impl ConfigTestFixture {
        fn new() -> Self {
            let temp_dir = TempDir::new().unwrap();
            let config = MergerFsConfig::default();
            let config_manager = ConfigManager::new(config);
            
            Self {
                temp_dir,
                config_manager,
            }
        }
        
        fn create_test_branch(&self, name: &str) -> PathBuf {
            let branch_path = self.temp_dir.path().join(name);
            std::fs::create_dir_all(&branch_path).unwrap();
            branch_path
        }
    }
    
    #[test]
    fn test_config_validation() {
        let mut config = MergerFsConfig::default();
        
        // Empty branches should fail validation
        assert!(config.validate().is_err());
        
        // Add a valid branch
        let temp_dir = TempDir::new().unwrap();
        config.branches.paths.push(BranchPath {
            path: temp_dir.path().to_path_buf(),
            mode: BranchMode::ReadWrite,
            min_free_space: None,
        });
        config.mount_point = PathBuf::from("/tmp/test_mount");
        
        assert!(config.validate().is_ok());
    }
    
    #[test]
    fn test_branch_path_parsing() {
        let tests = vec![
            ("/path/to/branch", BranchMode::ReadWrite, None),
            ("/path/to/branch=ro", BranchMode::ReadOnly, None),
            ("/path/to/branch=rw:1024", BranchMode::ReadWrite, Some(1024)),
            ("/path/to/branch=nc:2048", BranchMode::NoCreate, Some(2048)),
        ];
        
        for (input, expected_mode, expected_min_free) in tests {
            let temp_dir = TempDir::new().unwrap();
            let test_input = input.replace("/path/to/branch", &temp_dir.path().display().to_string());
            
            let branch_path = BranchPath::from_str(&test_input).unwrap();
            assert_eq!(branch_path.mode, expected_mode);
            assert_eq!(branch_path.min_free_space, expected_min_free);
        }
    }
    
    #[tokio::test]
    async fn test_config_updates() {
        let fixture = ConfigTestFixture::new();
        let branch1 = fixture.create_test_branch("branch1");
        let branch2 = fixture.create_test_branch("branch2");
        
        // Add initial branch
        let initial_branch = BranchPath {
            path: branch1,
            mode: BranchMode::ReadWrite,
            min_free_space: None,
        };
        
        fixture.config_manager.add_branch(initial_branch).unwrap();
        
        // Verify branch was added
        {
            let config = fixture.config_manager.get_config();
            assert_eq!(config.get().branches.paths.len(), 1);
        }
        
        // Add second branch
        let second_branch = BranchPath {
            path: branch2.clone(),
            mode: BranchMode::ReadOnly,
            min_free_space: Some(1024),
        };
        
        fixture.config_manager.add_branch(second_branch).unwrap();
        
        // Verify both branches exist
        {
            let config = fixture.config_manager.get_config();
            assert_eq!(config.get().branches.paths.len(), 2);
        }
        
        // Remove branch
        fixture.config_manager.remove_branch(&branch2).unwrap();
        
        // Verify branch was removed
        {
            let config = fixture.config_manager.get_config();
            assert_eq!(config.get().branches.paths.len(), 1);
        }
    }
    
    #[tokio::test]
    async fn test_control_file_handler() {
        let fixture = ConfigTestFixture::new();
        let branch = fixture.create_test_branch("test_branch");
        
        // Set up initial config
        fixture.config_manager.update_config(|config| {
            config.branches.paths.push(BranchPath {
                path: branch,
                mode: BranchMode::ReadWrite,
                min_free_space: None,
            });
            config.mount_point = PathBuf::from("/tmp/test");
            Ok(vec![])
        }).unwrap();
        
        let handler = ControlFileHandler::new(Arc::new(fixture.config_manager));
        
        // Test read operation
        let read_result = handler.handle_read().await.unwrap();
        assert!(read_result.contains("branches="));
        assert!(read_result.contains("func.create="));
        
        // Test write operation
        let write_content = "func.create=mfs\ncache.attr=5s";
        let write_result = handler.handle_write(write_content).await.unwrap();
        assert!(write_result.contains("Policy create updated to mfs"));
    }
    
    #[test]
    fn test_duration_parsing() {
        let tests = vec![
            ("1s", Duration::from_secs(1)),
            ("30s", Duration::from_secs(30)),
            ("2m", Duration::from_secs(120)),
            ("1h", Duration::from_secs(3600)),
            ("500ms", Duration::from_millis(500)),
        ];
        
        for (input, expected) in tests {
            let parsed = parse_duration(input).unwrap();
            assert_eq!(parsed, expected);
        }
    }
    
    #[tokio::test]
    async fn test_config_persistence() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("config.json");
        let persister = ConfigPersister::new(config_path, 3);
        
        let mut config = MergerFsConfig::default();
        config.mount_point = PathBuf::from("/tmp/test");
        config.branches.paths.push(BranchPath {
            path: temp_dir.path().join("branch1"),
            mode: BranchMode::ReadWrite,
            min_free_space: None,
        });
        
        // Create branch directory
        std::fs::create_dir_all(&config.branches.paths[0].path).unwrap();
        
        // Save config
        persister.save_config(&config).await.unwrap();
        
        // Load config
        let loaded_config = persister.load_config().await.unwrap();
        assert_eq!(loaded_config.mount_point, config.mount_point);
        assert_eq!(loaded_config.branches.paths.len(), 1);
    }
}
```

This comprehensive configuration system provides:

1. **Type-safe configuration structure** with validation
2. **Multiple configuration sources** (files, environment, command line)
3. **Runtime configuration updates** with change notifications
4. **Control file interface** for live reconfiguration
5. **Configuration persistence** with atomic saves and backups
6. **Comprehensive testing framework** for validation

The design leverages Rust's type system and ownership model to prevent configuration errors while providing the flexibility and runtime reconfiguration capabilities required for a production filesystem.