# Security Considerations and Hardening for Rust Implementation

## Overview

This guide provides comprehensive security considerations for the Rust implementation of mergerfs, covering threat modeling, attack vectors, security hardening, privilege management, and defensive programming practices to ensure the filesystem is secure and resistant to attacks.

## Threat Model and Attack Vectors

### Filesystem-Specific Threats

#### Path Traversal and Directory Injection

```rust
use std::path::{Path, PathBuf, Component};

pub struct SecurePath {
    normalized: PathBuf,
    is_safe: bool,
}

impl SecurePath {
    pub fn new(path: &Path) -> Result<Self, SecurityError> {
        let normalized = Self::normalize_path(path)?;
        let is_safe = Self::validate_path_safety(&normalized)?;
        
        Ok(Self {
            normalized,
            is_safe,
        })
    }
    
    fn normalize_path(path: &Path) -> Result<PathBuf, SecurityError> {
        let mut normalized = PathBuf::new();
        
        for component in path.components() {
            match component {
                Component::Normal(name) => {
                    // Check for null bytes and other dangerous characters
                    let name_str = name.to_str()
                        .ok_or(SecurityError::InvalidPath("Non-UTF8 path component".into()))?;
                    
                    if name_str.contains('\0') {
                        return Err(SecurityError::InvalidPath("Null byte in path".into()));
                    }
                    
                    if name_str.len() > 255 {
                        return Err(SecurityError::InvalidPath("Path component too long".into()));
                    }
                    
                    normalized.push(name);
                }
                Component::ParentDir => {
                    // Only allow going up if we're not at root
                    if !normalized.pop() {
                        return Err(SecurityError::InvalidPath("Path traversal attempt".into()));
                    }
                }
                Component::RootDir => {
                    normalized = PathBuf::from("/");
                }
                Component::CurDir => {
                    // Ignore current directory references
                }
                Component::Prefix(_) => {
                    return Err(SecurityError::InvalidPath("Windows path prefix not allowed".into()));
                }
            }
        }
        
        Ok(normalized)
    }
    
    fn validate_path_safety(path: &Path) -> Result<bool, SecurityError> {
        let path_str = path.to_str()
            .ok_or(SecurityError::InvalidPath("Non-UTF8 path".into()))?;
        
        // Check total path length
        if path_str.len() > 4096 {
            return Err(SecurityError::InvalidPath("Path too long".into()));
        }
        
        // Check for dangerous patterns
        let dangerous_patterns = [
            "//", "\\", "\r", "\n", "\t",
            "/..", "../", "./.", 
        ];
        
        for pattern in &dangerous_patterns {
            if path_str.contains(pattern) {
                return Err(SecurityError::InvalidPath(
                    format!("Dangerous pattern '{}' in path", pattern)
                ));
            }
        }
        
        // Check for reserved names (case-insensitive)
        let path_lower = path_str.to_lowercase();
        let reserved_names = [
            "con", "prn", "aux", "nul",
            "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
            "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
        ];
        
        for reserved in &reserved_names {
            if path_lower == *reserved || path_lower.starts_with(&format!("{}.", reserved)) {
                return Err(SecurityError::InvalidPath(
                    format!("Reserved name '{}' not allowed", reserved)
                ));
            }
        }
        
        Ok(true)
    }
    
    pub fn as_path(&self) -> &Path {
        &self.normalized
    }
    
    pub fn join<P: AsRef<Path>>(&self, path: P) -> Result<SecurePath, SecurityError> {
        let joined = self.normalized.join(path);
        SecurePath::new(&joined)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SecurityError {
    #[error("Invalid path: {0}")]
    InvalidPath(String),
    
    #[error("Permission denied: {0}")]
    PermissionDenied(String),
    
    #[error("Access control violation: {0}")]
    AccessViolation(String),
    
    #[error("Resource limit exceeded: {0}")]
    ResourceLimit(String),
}
```

#### Symlink Attack Prevention

```rust
use std::os::unix::fs::MetadataExt;

pub struct SymlinkValidator {
    max_symlink_depth: u32,
    allow_absolute_symlinks: bool,
    restricted_targets: Vec<PathBuf>,
}

impl SymlinkValidator {
    pub fn new() -> Self {
        Self {
            max_symlink_depth: 8,
            allow_absolute_symlinks: false,
            restricted_targets: vec![
                PathBuf::from("/etc/passwd"),
                PathBuf::from("/etc/shadow"),
                PathBuf::from("/proc"),
                PathBuf::from("/sys"),
                PathBuf::from("/dev"),
            ],
        }
    }
    
    pub fn validate_symlink(&self, link_path: &Path, target: &Path) -> Result<(), SecurityError> {
        // Check symlink depth
        let depth = self.count_symlink_depth(link_path)?;
        if depth > self.max_symlink_depth {
            return Err(SecurityError::AccessViolation(
                format!("Symlink depth {} exceeds maximum {}", depth, self.max_symlink_depth)
            ));
        }
        
        // Check if target is absolute and whether that's allowed
        if target.is_absolute() && !self.allow_absolute_symlinks {
            return Err(SecurityError::AccessViolation(
                "Absolute symlinks not allowed".into()
            ));
        }
        
        // Check if target points to restricted paths
        let resolved_target = if target.is_absolute() {
            target.to_path_buf()
        } else {
            link_path.parent()
                .ok_or(SecurityError::InvalidPath("Invalid link parent".into()))?
                .join(target)
        };
        
        for restricted in &self.restricted_targets {
            if resolved_target.starts_with(restricted) {
                return Err(SecurityError::AccessViolation(
                    format!("Symlink target '{}' points to restricted path", resolved_target.display())
                ));
            }
        }
        
        // Check for symlink loops
        self.check_symlink_loop(&resolved_target)?;
        
        Ok(())
    }
    
    fn count_symlink_depth(&self, path: &Path) -> Result<u32, SecurityError> {
        let mut current = path.to_path_buf();
        let mut depth = 0;
        
        loop {
            match std::fs::symlink_metadata(&current) {
                Ok(metadata) => {
                    if metadata.file_type().is_symlink() {
                        depth += 1;
                        if depth > self.max_symlink_depth {
                            return Err(SecurityError::AccessViolation(
                                "Symlink depth limit exceeded".into()
                            ));
                        }
                        
                        let target = std::fs::read_link(&current)
                            .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
                        
                        current = if target.is_absolute() {
                            target
                        } else {
                            current.parent()
                                .ok_or(SecurityError::InvalidPath("Invalid parent".into()))?
                                .join(target)
                        };
                    } else {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        
        Ok(depth)
    }
    
    fn check_symlink_loop(&self, path: &Path) -> Result<(), SecurityError> {
        use std::collections::HashSet;
        
        let mut visited = HashSet::new();
        let mut current = path.to_path_buf();
        
        loop {
            let canonical = current.canonicalize()
                .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
            
            if visited.contains(&canonical) {
                return Err(SecurityError::AccessViolation("Symlink loop detected".into()));
            }
            
            visited.insert(canonical.clone());
            
            match std::fs::symlink_metadata(&current) {
                Ok(metadata) if metadata.file_type().is_symlink() => {
                    let target = std::fs::read_link(&current)
                        .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
                    
                    current = if target.is_absolute() {
                        target
                    } else {
                        current.parent()
                            .ok_or(SecurityError::InvalidPath("Invalid parent".into()))?
                            .join(target)
                    };
                }
                _ => break,
            }
        }
        
        Ok(())
    }
}
```

### Access Control and Permission Management

#### Capability-Based Security

```rust
use std::collections::HashSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Capability {
    Read,
    Write,
    Execute,
    Delete,
    CreateFile,
    CreateDirectory,
    ChangeMetadata,
    ChangeOwnership,
    ReadExtendedAttributes,
    WriteExtendedAttributes,
    Mount,
    Unmount,
}

#[derive(Debug, Clone)]
pub struct SecurityContext {
    pub uid: u32,
    pub gid: u32,
    pub pid: u32,
    pub capabilities: HashSet<Capability>,
    pub effective_capabilities: HashSet<Capability>,
    pub selinux_context: Option<String>,
    pub apparmor_profile: Option<String>,
}

impl SecurityContext {
    pub fn from_request(req: &fuser::Request<'_>) -> Self {
        let capabilities = Self::get_process_capabilities(req.pid());
        let effective_capabilities = Self::get_effective_capabilities(req.uid(), req.gid());
        
        Self {
            uid: req.uid(),
            gid: req.gid(),
            pid: req.pid(),
            capabilities,
            effective_capabilities,
            selinux_context: Self::get_selinux_context(req.pid()),
            apparmor_profile: Self::get_apparmor_profile(req.pid()),
        }
    }
    
    pub fn has_capability(&self, cap: Capability) -> bool {
        self.effective_capabilities.contains(&cap)
    }
    
    pub fn can_access(&self, path: &Path, requested_caps: &[Capability]) -> Result<bool, SecurityError> {
        // Check basic Unix permissions
        let metadata = std::fs::metadata(path)
            .map_err(|e| SecurityError::PermissionDenied(e.to_string()))?;
        
        let file_mode = metadata.mode();
        let file_uid = metadata.uid();
        let file_gid = metadata.gid();
        
        // Owner permissions
        if self.uid == file_uid {
            return Ok(self.check_owner_permissions(file_mode, requested_caps));
        }
        
        // Group permissions
        if self.gid == file_gid {
            return Ok(self.check_group_permissions(file_mode, requested_caps));
        }
        
        // Other permissions
        Ok(self.check_other_permissions(file_mode, requested_caps))
    }
    
    fn check_owner_permissions(&self, mode: u32, requested_caps: &[Capability]) -> bool {
        let owner_perms = (mode >> 6) & 0o7;
        self.check_unix_permissions(owner_perms, requested_caps)
    }
    
    fn check_group_permissions(&self, mode: u32, requested_caps: &[Capability]) -> bool {
        let group_perms = (mode >> 3) & 0o7;
        self.check_unix_permissions(group_perms, requested_caps)
    }
    
    fn check_other_permissions(&self, mode: u32, requested_caps: &[Capability]) -> bool {
        let other_perms = mode & 0o7;
        self.check_unix_permissions(other_perms, requested_caps)
    }
    
    fn check_unix_permissions(&self, perms: u32, requested_caps: &[Capability]) -> bool {
        for cap in requested_caps {
            match cap {
                Capability::Read => {
                    if (perms & 0o4) == 0 && !self.has_capability(Capability::Read) {
                        return false;
                    }
                }
                Capability::Write | Capability::Delete | Capability::CreateFile => {
                    if (perms & 0o2) == 0 && !self.has_capability(Capability::Write) {
                        return false;
                    }
                }
                Capability::Execute => {
                    if (perms & 0o1) == 0 && !self.has_capability(Capability::Execute) {
                        return false;
                    }
                }
                _ => {
                    if !self.has_capability(*cap) {
                        return false;
                    }
                }
            }
        }
        
        true
    }
    
    fn get_process_capabilities(pid: u32) -> HashSet<Capability> {
        // Read /proc/{pid}/status to get capability information
        let status_path = format!("/proc/{}/status", pid);
        if let Ok(contents) = std::fs::read_to_string(&status_path) {
            // Parse CapEff line to get effective capabilities
            for line in contents.lines() {
                if line.starts_with("CapEff:") {
                    if let Some(caps_hex) = line.split_whitespace().nth(1) {
                        return Self::parse_capabilities(caps_hex);
                    }
                }
            }
        }
        
        HashSet::new()
    }
    
    fn get_effective_capabilities(uid: u32, gid: u32) -> HashSet<Capability> {
        let mut caps = HashSet::new();
        
        // Root has all capabilities
        if uid == 0 {
            caps.insert(Capability::Read);
            caps.insert(Capability::Write);
            caps.insert(Capability::Execute);
            caps.insert(Capability::Delete);
            caps.insert(Capability::CreateFile);
            caps.insert(Capability::CreateDirectory);
            caps.insert(Capability::ChangeMetadata);
            caps.insert(Capability::ChangeOwnership);
            caps.insert(Capability::ReadExtendedAttributes);
            caps.insert(Capability::WriteExtendedAttributes);
            caps.insert(Capability::Mount);
            caps.insert(Capability::Unmount);
        } else {
            // Regular users have limited capabilities
            caps.insert(Capability::Read);
            caps.insert(Capability::Write);
            caps.insert(Capability::Execute);
            caps.insert(Capability::CreateFile);
            caps.insert(Capability::ReadExtendedAttributes);
        }
        
        caps
    }
    
    fn parse_capabilities(caps_hex: &str) -> HashSet<Capability> {
        // Parse hexadecimal capability mask
        // This is a simplified implementation
        let mut caps = HashSet::new();
        
        if let Ok(caps_value) = u64::from_str_radix(caps_hex, 16) {
            // Check specific capability bits
            if caps_value & (1 << 2) != 0 { // CAP_DAC_OVERRIDE
                caps.insert(Capability::Read);
                caps.insert(Capability::Write);
            }
            if caps_value & (1 << 1) != 0 { // CAP_DAC_READ_SEARCH
                caps.insert(Capability::Read);
            }
            if caps_value & (1 << 21) != 0 { // CAP_SYS_ADMIN
                caps.insert(Capability::Mount);
                caps.insert(Capability::Unmount);
            }
        }
        
        caps
    }
    
    fn get_selinux_context(pid: u32) -> Option<String> {
        let attr_path = format!("/proc/{}/attr/current", pid);
        std::fs::read_to_string(&attr_path).ok()
    }
    
    fn get_apparmor_profile(pid: u32) -> Option<String> {
        let attr_path = format!("/proc/{}/attr/apparmor/current", pid);
        std::fs::read_to_string(&attr_path).ok()
    }
}
```

### Resource Limits and DoS Prevention

#### Rate Limiting and Request Throttling

```rust
use std::sync::Arc;
use std::time::{Duration, Instant};
use parking_lot::RwLock;
use std::collections::HashMap;

pub struct RateLimiter {
    limits: Arc<RwLock<HashMap<u32, UserLimits>>>,
    global_limits: GlobalLimits,
}

#[derive(Debug, Clone)]
struct UserLimits {
    requests_per_second: u32,
    current_requests: u32,
    last_reset: Instant,
    bandwidth_bytes_per_second: u64,
    current_bandwidth: u64,
    open_files: u32,
    max_open_files: u32,
}

#[derive(Debug, Clone)]
struct GlobalLimits {
    max_concurrent_operations: u32,
    max_memory_usage: u64,
    max_open_files_total: u32,
    current_concurrent_operations: Arc<std::sync::atomic::AtomicU32>,
    current_memory_usage: Arc<std::sync::atomic::AtomicU64>,
    current_open_files: Arc<std::sync::atomic::AtomicU32>,
}

impl RateLimiter {
    pub fn new() -> Self {
        Self {
            limits: Arc::new(RwLock::new(HashMap::new())),
            global_limits: GlobalLimits {
                max_concurrent_operations: 10000,
                max_memory_usage: 1024 * 1024 * 1024, // 1GB
                max_open_files_total: 100000,
                current_concurrent_operations: Arc::new(std::sync::atomic::AtomicU32::new(0)),
                current_memory_usage: Arc::new(std::sync::atomic::AtomicU64::new(0)),
                current_open_files: Arc::new(std::sync::atomic::AtomicU32::new(0)),
            },
        }
    }
    
    pub fn check_rate_limit(&self, uid: u32, operation: Operation) -> Result<RateLimitGuard, SecurityError> {
        // Check global limits first
        self.check_global_limits()?;
        
        // Check per-user limits
        let mut limits = self.limits.write();
        let user_limits = limits.entry(uid).or_insert_with(|| UserLimits {
            requests_per_second: self.get_user_rate_limit(uid),
            current_requests: 0,
            last_reset: Instant::now(),
            bandwidth_bytes_per_second: self.get_user_bandwidth_limit(uid),
            current_bandwidth: 0,
            open_files: 0,
            max_open_files: self.get_user_file_limit(uid),
        });
        
        // Reset counters if time window has passed
        let now = Instant::now();
        if now.duration_since(user_limits.last_reset) >= Duration::from_secs(1) {
            user_limits.current_requests = 0;
            user_limits.current_bandwidth = 0;
            user_limits.last_reset = now;
        }
        
        // Check request rate limit
        if user_limits.current_requests >= user_limits.requests_per_second {
            return Err(SecurityError::ResourceLimit(
                format!("Rate limit exceeded for user {}: {} requests/second", 
                       uid, user_limits.requests_per_second)
            ));
        }
        
        // Check operation-specific limits
        match operation {
            Operation::Read(size) | Operation::Write(size) => {
                if user_limits.current_bandwidth + size > user_limits.bandwidth_bytes_per_second {
                    return Err(SecurityError::ResourceLimit(
                        format!("Bandwidth limit exceeded for user {}", uid)
                    ));
                }
                user_limits.current_bandwidth += size;
            }
            Operation::Open => {
                if user_limits.open_files >= user_limits.max_open_files {
                    return Err(SecurityError::ResourceLimit(
                        format!("Open file limit exceeded for user {}", uid)
                    ));
                }
                user_limits.open_files += 1;
                self.global_limits.current_open_files.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            }
            Operation::Other => {}
        }
        
        user_limits.current_requests += 1;
        self.global_limits.current_concurrent_operations.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        
        Ok(RateLimitGuard {
            rate_limiter: self,
            uid,
            operation,
        })
    }
    
    fn check_global_limits(&self) -> Result<(), SecurityError> {
        let current_ops = self.global_limits.current_concurrent_operations.load(std::sync::atomic::Ordering::Relaxed);
        if current_ops >= self.global_limits.max_concurrent_operations {
            return Err(SecurityError::ResourceLimit(
                "Global operation limit exceeded".into()
            ));
        }
        
        let current_memory = self.global_limits.current_memory_usage.load(std::sync::atomic::Ordering::Relaxed);
        if current_memory >= self.global_limits.max_memory_usage {
            return Err(SecurityError::ResourceLimit(
                "Global memory limit exceeded".into()
            ));
        }
        
        let current_files = self.global_limits.current_open_files.load(std::sync::atomic::Ordering::Relaxed);
        if current_files >= self.global_limits.max_open_files_total {
            return Err(SecurityError::ResourceLimit(
                "Global file limit exceeded".into()
            ));
        }
        
        Ok(())
    }
    
    fn get_user_rate_limit(&self, uid: u32) -> u32 {
        if uid == 0 { 10000 } else { 1000 } // Root gets higher limits
    }
    
    fn get_user_bandwidth_limit(&self, uid: u32) -> u64 {
        if uid == 0 { 
            1024 * 1024 * 1024 // 1GB/s for root
        } else { 
            100 * 1024 * 1024 // 100MB/s for users
        }
    }
    
    fn get_user_file_limit(&self, uid: u32) -> u32 {
        if uid == 0 { 10000 } else { 1000 }
    }
    
    fn release_operation(&self, uid: u32, operation: &Operation) {
        self.global_limits.current_concurrent_operations.fetch_sub(1, std::sync::atomic::Ordering::Relaxed);
        
        if matches!(operation, Operation::Open) {
            let mut limits = self.limits.write();
            if let Some(user_limits) = limits.get_mut(&uid) {
                user_limits.open_files = user_limits.open_files.saturating_sub(1);
            }
            self.global_limits.current_open_files.fetch_sub(1, std::sync::atomic::Ordering::Relaxed);
        }
    }
}

#[derive(Debug, Clone)]
pub enum Operation {
    Read(u64),  // bytes
    Write(u64), // bytes
    Open,
    Other,
}

pub struct RateLimitGuard<'a> {
    rate_limiter: &'a RateLimiter,
    uid: u32,
    operation: Operation,
}

impl<'a> Drop for RateLimitGuard<'a> {
    fn drop(&mut self) {
        self.rate_limiter.release_operation(self.uid, &self.operation);
    }
}
```

## Cryptographic Security

### Secure Random Number Generation

```rust
use rand::{RngCore, CryptoRng};
use rand_chacha::ChaCha20Rng;
use rand::SeedableRng;

pub struct SecureRng {
    rng: ChaCha20Rng,
}

impl SecureRng {
    pub fn new() -> Result<Self, SecurityError> {
        // Use OS random number generator for seeding
        let mut seed = [0u8; 32];
        getrandom::getrandom(&mut seed)
            .map_err(|e| SecurityError::ResourceLimit(
                format!("Failed to get random seed: {}", e)
            ))?;
        
        let rng = ChaCha20Rng::from_seed(seed);
        
        Ok(Self { rng })
    }
    
    pub fn generate_file_handle(&mut self) -> u64 {
        // Generate cryptographically secure file handles to prevent guessing
        self.rng.next_u64()
    }
    
    pub fn generate_inode(&mut self) -> u64 {
        // Generate secure inode numbers
        self.rng.next_u64()
    }
    
    pub fn generate_session_id(&mut self) -> [u8; 32] {
        let mut session_id = [0u8; 32];
        self.rng.fill_bytes(&mut session_id);
        session_id
    }
}

impl RngCore for SecureRng {
    fn next_u32(&mut self) -> u32 {
        self.rng.next_u32()
    }
    
    fn next_u64(&mut self) -> u64 {
        self.rng.next_u64()
    }
    
    fn fill_bytes(&mut self, dest: &mut [u8]) {
        self.rng.fill_bytes(dest)
    }
    
    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), rand::Error> {
        self.rng.try_fill_bytes(dest)
    }
}

impl CryptoRng for SecureRng {}
```

### Data Integrity and Tampering Detection

```rust
use sha2::{Sha256, Digest};
use std::collections::HashMap;
use parking_lot::RwLock;

pub struct IntegrityChecker {
    checksums: Arc<RwLock<HashMap<PathBuf, FileChecksum>>>,
}

#[derive(Debug, Clone)]
struct FileChecksum {
    hash: [u8; 32],
    size: u64,
    mtime: u64,
    computed_at: Instant,
}

impl IntegrityChecker {
    pub fn new() -> Self {
        Self {
            checksums: Arc::new(RwLock::new(HashMap::new())),
        }
    }
    
    pub fn verify_file_integrity(&self, path: &Path) -> Result<bool, SecurityError> {
        let metadata = std::fs::metadata(path)
            .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
        
        let current_size = metadata.len();
        let current_mtime = metadata.modified()
            .map_err(|e| SecurityError::InvalidPath(e.to_string()))?
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        
        let checksums = self.checksums.read();
        if let Some(stored_checksum) = checksums.get(path) {
            // Check if file has been modified
            if stored_checksum.size != current_size || stored_checksum.mtime != current_mtime {
                // Recompute checksum
                drop(checksums);
                return self.compute_and_store_checksum(path);
            }
            
            // Verify existing checksum
            let current_hash = self.compute_file_hash(path)?;
            Ok(current_hash == stored_checksum.hash)
        } else {
            // First time checking this file
            drop(checksums);
            self.compute_and_store_checksum(path)
        }
    }
    
    fn compute_and_store_checksum(&self, path: &Path) -> Result<bool, SecurityError> {
        let hash = self.compute_file_hash(path)?;
        let metadata = std::fs::metadata(path)
            .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
        
        let checksum = FileChecksum {
            hash,
            size: metadata.len(),
            mtime: metadata.modified()
                .map_err(|e| SecurityError::InvalidPath(e.to_string()))?
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            computed_at: Instant::now(),
        };
        
        self.checksums.write().insert(path.to_path_buf(), checksum);
        Ok(true)
    }
    
    fn compute_file_hash(&self, path: &Path) -> Result<[u8; 32], SecurityError> {
        let mut file = std::fs::File::open(path)
            .map_err(|e| SecurityError::PermissionDenied(e.to_string()))?;
        
        let mut hasher = Sha256::new();
        let mut buffer = [0u8; 8192];
        
        use std::io::Read;
        loop {
            let bytes_read = file.read(&mut buffer)
                .map_err(|e| SecurityError::PermissionDenied(e.to_string()))?;
            
            if bytes_read == 0 {
                break;
            }
            
            hasher.update(&buffer[..bytes_read]);
        }
        
        Ok(hasher.finalize().into())
    }
    
    pub fn invalidate_checksum(&self, path: &Path) {
        self.checksums.write().remove(path);
    }
    
    pub fn cleanup_old_checksums(&self, max_age: Duration) {
        let now = Instant::now();
        self.checksums.write().retain(|_, checksum| {
            now.duration_since(checksum.computed_at) < max_age
        });
    }
}
```

## Security Configuration and Hardening

### Secure Configuration Management

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityConfig {
    pub enable_path_validation: bool,
    pub enable_symlink_validation: bool,
    pub enable_rate_limiting: bool,
    pub enable_integrity_checking: bool,
    pub max_path_length: usize,
    pub max_symlink_depth: u32,
    pub allow_absolute_symlinks: bool,
    pub restricted_paths: Vec<PathBuf>,
    pub privileged_users: Vec<u32>,
    pub audit_enabled: bool,
    pub audit_log_path: Option<PathBuf>,
    pub security_namespace: Option<String>,
}

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            enable_path_validation: true,
            enable_symlink_validation: true,
            enable_rate_limiting: true,
            enable_integrity_checking: false, // Disabled by default for performance
            max_path_length: 4096,
            max_symlink_depth: 8,
            allow_absolute_symlinks: false,
            restricted_paths: vec![
                PathBuf::from("/etc"),
                PathBuf::from("/proc"),
                PathBuf::from("/sys"),
                PathBuf::from("/dev"),
            ],
            privileged_users: vec![0], // Only root by default
            audit_enabled: false,
            audit_log_path: None,
            security_namespace: None,
        }
    }
}

pub struct SecurityManager {
    config: Arc<RwLock<SecurityConfig>>,
    path_validator: SecurePath,
    symlink_validator: SymlinkValidator,
    rate_limiter: RateLimiter,
    integrity_checker: IntegrityChecker,
    audit_logger: Option<AuditLogger>,
}

impl SecurityManager {
    pub fn new(config: SecurityConfig) -> Result<Self, SecurityError> {
        let audit_logger = if config.audit_enabled {
            Some(AuditLogger::new(config.audit_log_path.clone())?)
        } else {
            None
        };
        
        Ok(Self {
            config: Arc::new(RwLock::new(config)),
            path_validator: SecurePath::new(Path::new("/"))?,
            symlink_validator: SymlinkValidator::new(),
            rate_limiter: RateLimiter::new(),
            integrity_checker: IntegrityChecker::new(),
            audit_logger,
        })
    }
    
    pub fn validate_operation(
        &self,
        context: &SecurityContext,
        operation: &SecurityOperation,
    ) -> Result<SecurityGuard, SecurityError> {
        let config = self.config.read();
        
        // Check rate limits
        if config.enable_rate_limiting {
            let _rate_guard = self.rate_limiter.check_rate_limit(
                context.uid,
                self.convert_operation(operation)
            )?;
        }
        
        // Validate path security
        if config.enable_path_validation {
            self.validate_path_security(&operation.path, &config)?;
        }
        
        // Check symlink security
        if config.enable_symlink_validation {
            self.validate_symlink_security(&operation.path)?;
        }
        
        // Check permissions
        context.can_access(&operation.path, &operation.required_capabilities)?;
        
        // Log security event if auditing is enabled
        if let Some(ref audit_logger) = self.audit_logger {
            audit_logger.log_operation(context, operation)?;
        }
        
        // Check integrity if enabled
        if config.enable_integrity_checking && matches!(operation.operation_type, OperationType::Read) {
            self.integrity_checker.verify_file_integrity(&operation.path)?;
        }
        
        Ok(SecurityGuard {
            operation: operation.clone(),
            start_time: Instant::now(),
        })
    }
    
    fn validate_path_security(&self, path: &Path, config: &SecurityConfig) -> Result<(), SecurityError> {
        // Check if path is in restricted areas
        for restricted in &config.restricted_paths {
            if path.starts_with(restricted) {
                return Err(SecurityError::AccessViolation(
                    format!("Access to restricted path '{}' denied", path.display())
                ));
            }
        }
        
        // Validate path structure
        let _secure_path = SecurePath::new(path)?;
        
        Ok(())
    }
    
    fn validate_symlink_security(&self, path: &Path) -> Result<(), SecurityError> {
        if let Ok(metadata) = std::fs::symlink_metadata(path) {
            if metadata.file_type().is_symlink() {
                let target = std::fs::read_link(path)
                    .map_err(|e| SecurityError::InvalidPath(e.to_string()))?;
                
                self.symlink_validator.validate_symlink(path, &target)?;
            }
        }
        
        Ok(())
    }
    
    fn convert_operation(&self, op: &SecurityOperation) -> Operation {
        match op.operation_type {
            OperationType::Read => Operation::Read(op.size_hint.unwrap_or(0)),
            OperationType::Write => Operation::Write(op.size_hint.unwrap_or(0)),
            OperationType::Open => Operation::Open,
            _ => Operation::Other,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SecurityOperation {
    pub path: PathBuf,
    pub operation_type: OperationType,
    pub required_capabilities: Vec<Capability>,
    pub size_hint: Option<u64>,
}

#[derive(Debug, Clone)]
pub enum OperationType {
    Read,
    Write,
    Open,
    Create,
    Delete,
    Metadata,
    ExtendedAttributes,
}

pub struct SecurityGuard {
    operation: SecurityOperation,
    start_time: Instant,
}

impl Drop for SecurityGuard {
    fn drop(&mut self) {
        // Log completion time for security monitoring
        let duration = self.start_time.elapsed();
        if duration > Duration::from_millis(1000) {
            tracing::warn!(
                operation = ?self.operation.operation_type,
                path = %self.operation.path.display(),
                duration_ms = duration.as_millis(),
                "Slow security operation detected"
            );
        }
    }
}
```

This comprehensive security documentation covers threat modeling, access control, resource limits, cryptographic security, and secure configuration management. The implementation leverages Rust's safety features while providing robust protection against common filesystem attacks.