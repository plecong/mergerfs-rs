use crate::config::{Config, ConfigRef};
use crate::policy::{CreatePolicy, ActionPolicy, SearchPolicy};
use std::collections::HashMap;
use std::sync::Arc;
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
pub trait ConfigOption: Send + Sync {
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
    config: ConfigRef,
}

impl ConfigManager {
    pub fn new(config: ConfigRef) -> Self {
        let mut options: HashMap<String, Box<dyn ConfigOption>> = HashMap::new();
        
        // Register all configuration options
        // Phase 1: Core options
        options.insert(
            "func.create".to_string(),
            Box::new(CreatePolicyOption::new(config.clone())),
        );
        
        options.insert(
            "moveonenospc".to_string(),
            Box::new(BooleanOption::new(
                "moveonenospc",
                false, // default
                "Move files to another branch on ENOSPC",
                config.clone(),
            )),
        );
        
        options.insert(
            "direct_io".to_string(),
            Box::new(BooleanOption::new(
                "direct_io",
                false, // default
                "Force direct I/O for all files",
                config.clone(),
            )),
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
        }
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
}

/// Option for create policy configuration
struct CreatePolicyOption {
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
        // Validate policy name
        match value {
            "ff" | "mfs" | "lfs" | "rand" => {
                *self.current_value.write() = value.to_string();
                // TODO: Actually update the policy in file_manager
                // This will require modifying FileManager to support runtime policy changes
                Ok(())
            }
            _ => Err(ConfigError::InvalidValue(format!(
                "Unknown create policy: {}. Valid options: ff, mfs, lfs, rand",
                value
            ))),
        }
    }
    
    fn help(&self) -> &str {
        "Create policy: ff (first found), mfs (most free space), lfs (least free space), rand (random)"
    }
}

/// Generic boolean option
struct BooleanOption {
    name: String,
    value: Arc<RwLock<bool>>,
    help: String,
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
    fn test_boolean_option() {
        let config = config::create_config();
        let manager = ConfigManager::new(config);
        
        // Test getting default value
        let value = manager.get_option("moveonenospc").unwrap();
        assert_eq!(value, "false");
        
        // Test setting valid values
        assert!(manager.set_option("moveonenospc", "true").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "true");
        
        assert!(manager.set_option("moveonenospc", "0").is_ok());
        assert_eq!(manager.get_option("moveonenospc").unwrap(), "false");
        
        // Test invalid values
        assert!(manager.set_option("moveonenospc", "invalid").is_err());
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
        
        // Test invalid policy
        assert!(manager.set_option("func.create", "invalid").is_err());
    }
}