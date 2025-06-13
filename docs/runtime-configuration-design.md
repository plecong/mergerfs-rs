# Runtime Configuration Design for mergerfs-rs

## Overview

This document outlines the design for implementing runtime configuration in mergerfs-rs, allowing users to modify filesystem behavior without remounting. The implementation will follow the C++ mergerfs approach of using extended attributes (xattr) on a special control file.

## Architecture

### 1. Control File Interface

The primary interface will be a virtual control file at `/.mergerfs` that responds to xattr operations:

```rust
pub struct ControlFile {
    // Virtual file that doesn't exist on any branch
    pub path: PathBuf,  // Always "/.mergerfs"
    pub ino: u64,       // Special inode number
}
```

### 2. Configuration Options

Each configuration option will implement a trait:

```rust
pub trait ConfigOption: Send + Sync {
    /// Get the option name (e.g., "moveonenospc")
    fn name(&self) -> &str;
    
    /// Get the current value as a string
    fn get_value(&self) -> String;
    
    /// Set the value from a string
    fn set_value(&mut self, value: &str) -> Result<(), ConfigError>;
    
    /// Check if this option is read-only
    fn is_readonly(&self) -> bool;
    
    /// Get help text for this option
    fn help(&self) -> &str;
}
```

### 3. Configuration Manager

```rust
pub struct ConfigManager {
    options: Arc<RwLock<HashMap<String, Box<dyn ConfigOption>>>>,
    config: ConfigRef,  // Reference to main Config struct
}

impl ConfigManager {
    pub fn new(config: ConfigRef) -> Self;
    
    /// Get all available option names
    pub fn list_options(&self) -> Vec<String>;
    
    /// Get a specific option value
    pub fn get_option(&self, name: &str) -> Result<String, ConfigError>;
    
    /// Set a specific option value
    pub fn set_option(&self, name: &str, value: &str) -> Result<(), ConfigError>;
}
```

### 4. Integration with FUSE

The FUSE filesystem will handle xattr operations on `/.mergerfs` specially:

```rust
impl Filesystem for MergerFS {
    fn getxattr(&mut self, req: &Request, ino: u64, name: &OsStr, size: u32, 
                reply: ReplyXattr) {
        if ino == CONTROL_FILE_INO {
            // Handle control file xattr
            self.handle_control_getxattr(name, size, reply);
        } else {
            // Normal xattr handling
            // ...
        }
    }
    
    fn setxattr(&mut self, req: &Request, ino: u64, name: &OsStr, value: &[u8], 
                flags: i32, position: u32, reply: ReplyEmpty) {
        if ino == CONTROL_FILE_INO {
            // Handle control file xattr
            self.handle_control_setxattr(name, value, reply);
        } else {
            // Normal xattr handling
            // ...
        }
    }
}
```

## Configuration Options to Implement

### Phase 1: Core Options

1. **Policy Configuration**
   - `user.mergerfs.func.create`: Create policy (ff, mfs, lfs, rand, etc.)
   - `user.mergerfs.func.getattr`: Getattr policy
   - `user.mergerfs.func.chmod`: Chmod policy
   - `user.mergerfs.func.chown`: Chown policy
   - `user.mergerfs.func.mkdir`: Mkdir policy
   - `user.mergerfs.func.unlink`: Unlink policy

2. **Feature Toggles**
   - `user.mergerfs.moveonenospc`: Enable/disable moving files on ENOSPC
   - `user.mergerfs.direct_io`: Force direct I/O
   - `user.mergerfs.dropcacheonclose`: Drop cache on file close

3. **Branch Management**
   - `user.mergerfs.branches`: Get/set branch list
   - `user.mergerfs.minfreespace`: Minimum free space requirement

### Phase 2: Advanced Options

1. **Caching**
   - `user.mergerfs.cache.files`: File caching mode
   - `user.mergerfs.cache.writeback`: Enable writeback caching
   - `user.mergerfs.cache.statfs`: StatFS cache timeout
   - `user.mergerfs.cache.attr`: Attribute cache timeout
   - `user.mergerfs.cache.entry`: Entry cache timeout
   - `user.mergerfs.cache.negative_entry`: Negative entry cache timeout
   - `user.mergerfs.cache.readdir`: Readdir caching

2. **Performance**
   - `user.mergerfs.async_read`: Enable async reads
   - `user.mergerfs.auto_cache`: Enable auto caching
   - `user.mergerfs.threads`: Thread pool size

3. **Information (Read-only)**
   - `user.mergerfs.version`: Version string
   - `user.mergerfs.pid`: Process ID
   - `user.mergerfs.srcmounts`: Source mount points

### Phase 3: File-specific Attributes

On regular files, support:
- `user.mergerfs.basepath`: Branch path where file exists
- `user.mergerfs.relpath`: Relative path within mergerfs
- `user.mergerfs.fullpath`: Full path on underlying filesystem
- `user.mergerfs.allpaths`: All paths (for duplicated files)

## Implementation Plan

### Step 1: Basic Infrastructure
1. Create ConfigOption trait and ConfigManager
2. Add control file handling to FUSE operations
3. Implement basic get/set for a test option

### Step 2: Policy Configuration
1. Create PolicyOption struct implementing ConfigOption
2. Wire up all policy options to actual policy selection
3. Add validation for policy names

### Step 3: Feature Options
1. Implement boolean options (moveonenospc, direct_io, etc.)
2. Implement numeric options (minfreespace, cache timeouts)
3. Add proper validation and error handling

### Step 4: Branch Management
1. Implement branch list parsing and validation
2. Support adding/removing branches at runtime
3. Handle branch mode changes (RW/RO/NC)

### Step 5: File Attributes
1. Add support for file-specific xattrs
2. Implement basepath, relpath, fullpath, allpaths
3. Ensure proper branch resolution

## Error Handling

Configuration errors will map to standard errno values:
- `ENOATTR` (61): Attribute not found
- `EINVAL` (22): Invalid value
- `EROFS` (30): Read-only attribute
- `ENOTSUP` (95): Operation not supported
- `EPERM` (1): Permission denied

## Testing Strategy

1. **Unit Tests**
   - Test each ConfigOption implementation
   - Test ConfigManager operations
   - Test validation logic

2. **Integration Tests**
   - Test xattr operations on control file
   - Test configuration changes take effect
   - Test invalid configurations are rejected

3. **Python Tests**
   - End-to-end tests using xattr module
   - Test configuration persistence
   - Test concurrent configuration changes

## Security Considerations

1. **Permission Checks**
   - Only root or mount owner can modify configuration
   - Some options may be restricted further

2. **Validation**
   - All input must be validated before applying
   - Prevent injection attacks through option values

3. **Atomicity**
   - Configuration changes must be atomic
   - No partial updates on failure

## Example Usage

```bash
# List all configuration options
xattr -l /.mergerfs

# Get current create policy
xattr -p user.mergerfs.func.create /.mergerfs

# Change create policy to most-free-space
xattr -w user.mergerfs.func.create mfs /.mergerfs

# Enable moveonenospc
xattr -w user.mergerfs.moveonenospc true /.mergerfs

# Get file's actual location
xattr -p user.mergerfs.fullpath /mnt/union/myfile.txt
```

## Benefits

1. **No Special Tools**: Uses standard xattr utilities
2. **Scriptable**: Easy to automate configuration changes
3. **Compatible**: Same interface as C++ mergerfs
4. **Discoverable**: Can list all options
5. **Safe**: Validation prevents invalid configurations