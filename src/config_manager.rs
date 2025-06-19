use crate::config::ConfigRef;
use crate::file_ops::FileManager;
use crate::policy::create_policy_from_name;
use std::collections::HashMap;
use std::sync::{Arc, Weak};
use std::any::Any;
use parking_lot::RwLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("Option not found")]
    NotFound,
    #[error("Invalid value: {0}")]
    InvalidValue(String),
    #[error("Read-only option")]
    ReadOnly,
    #[error("Operation not supported")]
    NotSupported,
}

impl ConfigError {
    pub fn errno(&self) -> i32 {
        match self {
            ConfigError::NotFound => 61,      // ENOATTR
            ConfigError::InvalidValue(_) => 22, // EINVAL
            ConfigError::ReadOnly => 30,       // EROFS
            ConfigError::NotSupported => 95,   // ENOTSUP
        }
    }
}

/// Trait for configuration options that can be get/set at runtime
pub trait ConfigOption: Send + Sync + Any {
    /// Get the option name (e.g., "moveonenospc")
    fn name(&self) -> &str;
    
    /// Get the current value as a string
    fn get_value(&self) -> String;
    
    /// Set the value from a string
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError>;
    
    /// Check if this option is read-only
    fn is_readonly(&self) -> bool {
        false
    }
    
    /// Get help text for this option
    fn help(&self) -> &str;
}

/// Manages runtime configuration through xattr interface
pub struct ConfigManager {
    options: Arc<RwLock<HashMap<String, Box<dyn ConfigOption>>>>,
    #[allow(dead_code)]
    config: ConfigRef,
    file_manager: Weak<FileManager>,
}

impl ConfigManager {
    pub fn new(config: ConfigRef) -> Self {
        Self::new_without_file_manager(config)
    }
    
    pub fn new_without_file_manager(config: ConfigRef) -> Self {
        let mut options: HashMap<String, Box<dyn ConfigOption>> = HashMap::new();
        
        // Register all configuration options
        // Phase 1: Core options
        options.insert(
            "func.create".to_string(),
            Box::new(CreatePolicyOption::new(config.clone())),
        );
        
        options.insert(
            "moveonenospc".to_string(),
            Box::new(MoveOnENOSPCOption::new(config.clone())),
        );
        
        options.insert(
            "direct_io".to_string(),
            Box::new(BooleanOption::new(
                "direct_io",
                false, // default
                "Force direct I/O for all files (deprecated, use cache.files)",
                config.clone(),
            )),
        );
        
        options.insert(
            "cache.files".to_string(),
            Box::new(CacheFilesOption::new(config.clone())),
        );
        
        options.insert(
            "inodecalc".to_string(),
            Box::new(InodeCalcOption::new(config.clone())),
        );
        
        options.insert(
            "statfs".to_string(),
            Box::new(StatFSModeOption::new(config.clone())),
        );
        
        options.insert(
            "statfs.ignore".to_string(),
            Box::new(StatFSIgnoreOption::new(config.clone())),
        );
        
        // Read-only options
        options.insert(
            "version".to_string(),
            Box::new(ReadOnlyOption::new(
                "version",
                env!("CARGO_PKG_VERSION"),
                "mergerfs-rs version",
            )),
        );
        
        options.insert(
            "pid".to_string(),
            Box::new(ReadOnlyOption::new(
                "pid",
                &std::process::id().to_string(),
                "Process ID of mergerfs",
            )),
        );
        
        Self {
            options: Arc::new(RwLock::new(options)),
            config,
            file_manager: Weak::new(),
        }
    }
    
    /// Set the file manager reference for runtime policy updates
    pub fn set_file_manager(&mut self, file_manager: &Arc<FileManager>) {
        self.file_manager = Arc::downgrade(file_manager);
        
        // Sync the initial policy value with the FileManager's current policy
        let current_policy_name = file_manager.get_create_policy_name();
        if let Some(create_option) = self.options.write().get_mut("func.create") {
            // Update the stored value to match the FileManager's current policy
            let _ = create_option.set_value(&current_policy_name);
        }
        
        tracing::info!("ConfigManager initialized with FileManager, current policy: {}", current_policy_name);
    }
    
    /// Get all available option names with "user.mergerfs." prefix
    pub fn list_options(&self) -> Vec<String> {
        let options = self.options.read();
        options
            .keys()
            .map(|k| format!("user.mergerfs.{}", k))
            .collect()
    }
    
    /// Get a specific option value
    pub fn get_option(&self, name: &str) -> Result<String, ConfigError> {
        // Remove "user.mergerfs." prefix if present
        let name = name.strip_prefix("user.mergerfs.").unwrap_or(name);
        
        let options = self.options.read();
        match options.get(name) {
            Some(option) => Ok(option.get_value()),
            None => Err(ConfigError::NotFound),
        }
    }
    
    /// Set a specific option value
    pub fn set_option(&self, name: &str, value: &str) -> Result<(), ConfigError> {
        // Remove "user.mergerfs." prefix if present
        let name = name.strip_prefix("user.mergerfs.").unwrap_or(name);
        
        // Special handling for create policy
        if name == "func.create" {
            return self.set_create_policy(value);
        }
        
        let mut options = self.options.write();
        match options.get_mut(name) {
            Some(option) => {
                if option.is_readonly() {
                    Err(ConfigError::ReadOnly)
                } else {
                    option.set_value(value)
                }
            }
            None => Err(ConfigError::NotFound),
        }
    }
    
    /// Set create policy with file manager update
    fn set_create_policy(&self, value: &str) -> Result<(), ConfigError> {
        // Validate policy name and create the policy
        let policy = create_policy_from_name(value)
            .ok_or_else(|| ConfigError::InvalidValue(format!(
                "Unknown create policy: {}. Valid options: ff, mfs, lfs, lus, rand, epff, epmfs, eplfs, pfrd",
                value
            )))?;
        
        // Update the file manager's policy if available
        if let Some(file_manager) = self.file_manager.upgrade() {
            eprintln!("DEBUG: Setting create policy to: {}", value);
            file_manager.set_create_policy(policy);
            let new_policy_name = file_manager.get_create_policy_name();
            eprintln!("DEBUG: FileManager policy after update: {}", new_policy_name);
            tracing::info!("Updated create policy to: {}", value);
        } else {
            eprintln!("DEBUG: FileManager not available for policy update");
            tracing::warn!("FileManager not available for policy update");
        }
        
        // Update the stored value in the config option
        let mut options = self.options.write();
        if let Some(option) = options.get_mut("func.create") {
            option.set_value(value)?;
        }
        
        Ok(())
    }
    
    /// Get access to the underlying config
    pub fn config(&self) -> &ConfigRef {
        &self.config
    }
}

/// Option for create policy configuration
struct CreatePolicyOption {
    #[allow(dead_code)]
    config: ConfigRef,
    current_value: RwLock<String>,
}

impl CreatePolicyOption {
    fn new(config: ConfigRef) -> Self {
        Self { 
            config,
            current_value: RwLock::new("ff".to_string()),
        }
    }
}

impl ConfigOption for CreatePolicyOption {
    fn name(&self) -> &str {
        "func.create"
    }
    
    fn get_value(&self) -> String {
        self.current_value.read().clone()
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        // Just validate and store the value - actual policy update is handled by ConfigManager
        match value {
            "ff" | "mfs" | "lfs" | "lus" | "rand" | "epff" | "epmfs" | "eplfs" | "pfrd" => {
                *self.current_value.write() = value.to_string();
                Ok(())
            }
            _ => Err(ConfigError::InvalidValue(format!(
                "Unknown create policy: {}. Valid options: ff, mfs, lfs, lus, rand, epff, epmfs, eplfs, pfrd",
                value
            ))),
        }
    }
    
    fn help(&self) -> &str {
        "Create policy: ff (first found), mfs (most free space), lfs (least free space), lus (least used space), rand (random), epmfs (existing path most free space), eplfs (existing path least free space), pfrd (proportional fill random distribution)"
    }
}

/// Option for moveonenospc configuration
struct MoveOnENOSPCOption {
    config: ConfigRef,
}

impl MoveOnENOSPCOption {
    fn new(config: ConfigRef) -> Self {
        Self { config }
    }
}

impl ConfigOption for MoveOnENOSPCOption {
    fn name(&self) -> &str {
        "moveonenospc"
    }
    
    fn get_value(&self) -> String {
        let config = self.config.read();
        if config.moveonenospc.enabled {
            config.moveonenospc.policy_name.clone()
        } else {
            "false".to_string()
        }
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        let mut config = self.config.write();
        
        match value.to_lowercase().as_str() {
            "false" | "0" | "no" | "off" => {
                config.moveonenospc.enabled = false;
                Ok(())
            }
            "true" | "1" | "yes" | "on" => {
                config.moveonenospc.enabled = true;
                config.moveonenospc.policy_name = "pfrd".to_string(); // Default policy
                Ok(())
            }
            // Check if it's a valid policy name
            "ff" | "mfs" | "lfs" | "lus" | "rand" | "epff" | "epmfs" | "eplfs" | "pfrd" => {
                config.moveonenospc.enabled = true;
                config.moveonenospc.policy_name = value.to_string();
                Ok(())
            }
            _ => Err(ConfigError::InvalidValue(format!(
                "Invalid moveonenospc value: {}. Use 'true', 'false', or a valid create policy name",
                value
            ))),
        }
    }
    
    fn help(&self) -> &str {
        "Move files to another branch on ENOSPC. Values: true, false, or a create policy name (ff, mfs, lfs, lus, rand, epmfs, eplfs, pfrd)"
    }
}

/// Generic boolean option
struct BooleanOption {
    name: String,
    value: Arc<RwLock<bool>>,
    help: String,
    #[allow(dead_code)]
    config: ConfigRef,
}

impl BooleanOption {
    fn new(name: &str, default: bool, help: &str, config: ConfigRef) -> Self {
        Self {
            name: name.to_string(),
            value: Arc::new(RwLock::new(default)),
            help: help.to_string(),
            config,
        }
    }
}

impl ConfigOption for BooleanOption {
    fn name(&self) -> &str {
        &self.name
    }
    
    fn get_value(&self) -> String {
        self.value.read().to_string()
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        match value.to_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => {
                *self.value.write() = true;
                Ok(())
            }
            "false" | "0" | "no" | "off" => {
                *self.value.write() = false;
                Ok(())
            }
            _ => Err(ConfigError::InvalidValue(format!(
                "Invalid boolean value: {}. Use true/false, 1/0, yes/no, or on/off",
                value
            ))),
        }
    }
    
    fn help(&self) -> &str {
        &self.help
    }
}

/// Cache files configuration option
struct CacheFilesOption {
    config: ConfigRef,
}

impl CacheFilesOption {
    fn new(config: ConfigRef) -> Self {
        Self { config }
    }
}

impl ConfigOption for CacheFilesOption {
    fn name(&self) -> &str {
        "cache.files"
    }
    
    fn get_value(&self) -> String {
        use crate::config::CacheFiles;
        match self.config.read().cache_files {
            CacheFiles::Libfuse => "libfuse".to_string(),
            CacheFiles::Off => "off".to_string(),
            CacheFiles::Partial => "partial".to_string(),
            CacheFiles::Full => "full".to_string(),
            CacheFiles::AutoFull => "auto-full".to_string(),
            CacheFiles::PerProcess => "per-process".to_string(),
        }
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        use crate::config::CacheFiles;
        let cache_mode = match value.to_lowercase().as_str() {
            "libfuse" => CacheFiles::Libfuse,
            "off" => CacheFiles::Off,
            "partial" => CacheFiles::Partial,
            "full" => CacheFiles::Full,
            "auto-full" => CacheFiles::AutoFull,
            "per-process" => CacheFiles::PerProcess,
            _ => return Err(ConfigError::InvalidValue(format!("Invalid cache.files value: {}", value))),
        };
        
        self.config.write().cache_files = cache_mode;
        Ok(())
    }
    
    fn is_readonly(&self) -> bool {
        false
    }
    
    fn help(&self) -> &str {
        "File caching behavior (libfuse|off|partial|full|auto-full|per-process)"
    }
}

/// Inode calculation algorithm configuration option
struct InodeCalcOption {
    config: ConfigRef,
}

impl InodeCalcOption {
    fn new(config: ConfigRef) -> Self {
        Self { config }
    }
}

impl ConfigOption for InodeCalcOption {
    fn name(&self) -> &str {
        "inodecalc"
    }
    
    fn get_value(&self) -> String {
        self.config.read().inodecalc.to_string().to_string()
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        use crate::inode::InodeCalc;
        
        match InodeCalc::from_str(value) {
            Ok(mode) => {
                self.config.write().inodecalc = mode;
                Ok(())
            }
            Err(e) => Err(ConfigError::InvalidValue(e)),
        }
    }
    
    fn help(&self) -> &str {
        "Inode calculation algorithm (passthrough|path-hash|path-hash32|devino-hash|devino-hash32|hybrid-hash|hybrid-hash32)"
    }
}

/// Read-only option that returns a fixed value
struct ReadOnlyOption {
    name: String,
    value: String,
    help: String,
}

impl ReadOnlyOption {
    fn new(name: &str, value: &str, help: &str) -> Self {
        Self {
            name: name.to_string(),
            value: value.to_string(),
            help: help.to_string(),
        }
    }
}

impl ConfigOption for ReadOnlyOption {
    fn name(&self) -> &str {
        &self.name
    }
    
    fn get_value(&self) -> String {
        self.value.clone()
    }
    
    fn set_value(&mut self, _value: &str) -> Result<(), ConfigError> {
        Err(ConfigError::ReadOnly)
    }
    
    fn is_readonly(&self) -> bool {
        true
    }
    
    fn help(&self) -> &str {
        &self.help
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;
    
    #[test]
    fn test_config_manager_basics() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test listing options
        let options = manager.list_options();
        assert!(options.contains(&"user.mergerfs.func.create".to_string()));
        assert!(options.contains(&"user.mergerfs.moveonenospc".to_string()));
        assert!(options.contains(&"user.mergerfs.version".to_string()));
        
        // Test getting values
        assert!(manager.get_option("func.create").is_ok());
        assert!(manager.get_option("version").is_ok());
        assert!(manager.get_option("nonexistent").is_err());
        
        // Test with full prefix
        assert!(manager.get_option("user.mergerfs.version").is_ok());
    }
    
    #[test]
    fn test_moveonenospc_option() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test getting default value (enabled with pfrd)
        let value = manager.get_option("moveonenospc").unwrap();
        assert_eq!(value, "pfrd");
        
        // Test disabling
        assert!(manager.set_option("moveonenospc", "false").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "false");
        
        // Test enabling with true (should use default pfrd)
        assert!(manager.set_option("moveonenospc", "true").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "pfrd");
        
        // Test setting specific policies
        assert!(manager.set_option("moveonenospc", "mfs").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "mfs");
        
        assert!(manager.set_option("moveonenospc", "0").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "false");
        
        // Test invalid values
        assert!(manager.set_option("moveonenospc", "invalid").is_err());
    }
    
    #[test]
    fn test_cache_files_option() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test default value
        assert_eq!(manager.get_option("cache.files").unwrap(), "libfuse");
        
        // Test setting valid values
        assert!(manager.set_option("cache.files", "off").is_ok());
        assert_eq!(manager.get_option("cache.files").unwrap(), "off");
        
        assert!(manager.set_option("cache.files", "partial").is_ok());
        assert_eq!(manager.get_option("cache.files").unwrap(), "partial");
        
        assert!(manager.set_option("cache.files", "full").is_ok());
        assert_eq!(manager.get_option("cache.files").unwrap(), "full");
        
        assert!(manager.set_option("cache.files", "auto-full").is_ok());
        assert_eq!(manager.get_option("cache.files").unwrap(), "auto-full");
        
        assert!(manager.set_option("cache.files", "per-process").is_ok());
        assert_eq!(manager.get_option("cache.files").unwrap(), "per-process");
        
        // Test invalid values
        assert!(manager.set_option("cache.files", "invalid").is_err());
    }

    #[test]
    fn test_readonly_option() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test getting value
        assert!(manager.get_option("version").is_ok());
        
        // Test setting should fail
        match manager.set_option("version", "new_value") {
            Err(ConfigError::ReadOnly) => {}
            _ => panic!("Expected ReadOnly error"),
        }
    }
    
    #[test]
    fn test_create_policy_option() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test valid policies
        assert!(manager.set_option("func.create", "ff").is_ok());
        assert!(manager.set_option("func.create", "mfs").is_ok());
        assert!(manager.set_option("func.create", "lfs").is_ok());
        assert!(manager.set_option("func.create", "rand").is_ok());
        assert!(manager.set_option("func.create", "epmfs").is_ok());
        
        // Test invalid policy
        assert!(manager.set_option("func.create", "invalid").is_err());
    }
}

/// StatFS mode configuration option
struct StatFSModeOption {
    config: ConfigRef,
}

impl StatFSModeOption {
    fn new(config: ConfigRef) -> Self {
        Self { config }
    }
}

impl ConfigOption for StatFSModeOption {
    fn name(&self) -> &str {
        "statfs"
    }
    
    fn get_value(&self) -> String {
        use crate::config::StatFSMode;
        match self.config.read().statfs_mode {
            StatFSMode::Base => "base".to_string(),
            StatFSMode::Full => "full".to_string(),
        }
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        use crate::config::StatFSMode;
        let mode = match value.to_lowercase().as_str() {
            "base" => StatFSMode::Base,
            "full" => StatFSMode::Full,
            _ => return Err(ConfigError::InvalidValue(format!("Invalid statfs mode: {}", value))),
        };
        
        self.config.write().statfs_mode = mode;
        Ok(())
    }
    
    fn help(&self) -> &str {
        "StatFS mode (base|full) - controls how filesystem statistics are reported"
    }
}

/// StatFS ignore configuration option
struct StatFSIgnoreOption {
    config: ConfigRef,
}

impl StatFSIgnoreOption {
    fn new(config: ConfigRef) -> Self {
        Self { config }
    }
}

impl ConfigOption for StatFSIgnoreOption {
    fn name(&self) -> &str {
        "statfs.ignore"
    }
    
    fn get_value(&self) -> String {
        use crate::config::StatFSIgnore;
        match self.config.read().statfs_ignore {
            StatFSIgnore::None => "none".to_string(),
            StatFSIgnore::ReadOnly => "ro".to_string(),
            StatFSIgnore::NoCreate => "nc".to_string(),
        }
    }
    
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError> {
        use crate::config::StatFSIgnore;
        let ignore = match value.to_lowercase().as_str() {
            "none" => StatFSIgnore::None,
            "ro" => StatFSIgnore::ReadOnly,
            "nc" => StatFSIgnore::NoCreate,
            _ => return Err(ConfigError::InvalidValue(format!("Invalid statfs.ignore value: {}", value))),
        };
        
        self.config.write().statfs_ignore = ignore;
        Ok(())
    }
    
    fn help(&self) -> &str {
        "StatFS ignore mode (none|ro|nc) - which branches to ignore for space calculations"
    }
}