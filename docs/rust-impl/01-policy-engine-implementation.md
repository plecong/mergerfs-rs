# Policy Engine Implementation in Rust

## Overview

The policy engine is the core innovation of mergerfs, determining which filesystem branches to use for different operations. This guide provides a comprehensive approach to implementing the policy system in Rust using traits, dynamic dispatch, and type safety.

## Core Architecture

### Policy Trait Hierarchy

```rust
use std::path::Path;
use std::sync::Arc;

// Base trait for all policies
pub trait Policy: Send + Sync {
    fn name(&self) -> &'static str;
    fn description(&self) -> &'static str;
}

// Create policies determine where to place new files/directories
pub trait CreatePolicy: Policy {
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
    
    fn is_path_preserving(&self) -> bool;
}

// Search policies determine where to look for existing files
pub trait SearchPolicy: Policy {
    fn find_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
}

// Action policies determine which instances to operate on
pub trait ActionPolicy: Policy {
    fn target_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError>;
}
```

### Policy Error Types

```rust
#[derive(Debug, thiserror::Error)]
pub enum PolicyError {
    #[error("No suitable branches found")]
    NoBranchesAvailable,
    
    #[error("Access denied on all branches")]
    AccessDenied,
    
    #[error("All branches are read-only")]
    ReadOnlyFilesystem,
    
    #[error("Insufficient space on all branches")]
    InsufficientSpace,
    
    #[error("Branch not found: {0}")]
    BranchNotFound(String),
    
    #[error("I/O error: {0}")]
    IoError(#[from] std::io::Error),
}

impl PolicyError {
    pub fn errno(&self) -> i32 {
        match self {
            PolicyError::NoBranchesAvailable => libc::ENOENT,
            PolicyError::AccessDenied => libc::EACCES,
            PolicyError::ReadOnlyFilesystem => libc::EROFS,
            PolicyError::InsufficientSpace => libc::ENOSPC,
            PolicyError::BranchNotFound(_) => libc::ENOENT,
            PolicyError::IoError(e) => e.raw_os_error().unwrap_or(libc::EIO),
        }
    }
}
```

## Branch Representation

### Branch Structure

```rust
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

#[derive(Debug, Clone)]
pub enum BranchMode {
    ReadWrite,
    ReadOnly,
    NoCreate, // Read-write but no new file creation
}

#[derive(Debug)]
pub struct Branch {
    pub path: PathBuf,
    pub mode: BranchMode,
    pub min_free_space: u64,
    
    // Cached filesystem information
    cached_info: parking_lot::RwLock<Option<CachedBranchInfo>>,
    info_timestamp: AtomicU64, // Unix timestamp
}

#[derive(Debug, Clone)]
struct CachedBranchInfo {
    total_space: u64,
    free_space: u64,
    available_space: u64,
    readonly: bool,
    filesystem_type: String,
}

impl Branch {
    pub fn new(path: PathBuf, mode: BranchMode, min_free_space: u64) -> Self {
        Self {
            path,
            mode,
            min_free_space,
            cached_info: parking_lot::RwLock::new(None),
            info_timestamp: AtomicU64::new(0),
        }
    }
    
    pub fn is_readonly(&self) -> bool {
        matches!(self.mode, BranchMode::ReadOnly)
    }
    
    pub fn allows_create(&self) -> bool {
        matches!(self.mode, BranchMode::ReadWrite)
    }
    
    pub fn get_space_info(&self) -> Result<CachedBranchInfo, std::io::Error> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        
        let last_update = self.info_timestamp.load(Ordering::Relaxed);
        
        // Cache for 1 second
        if now - last_update < 1 {
            if let Some(ref info) = *self.cached_info.read() {
                return Ok(info.clone());
            }
        }
        
        // Update cache
        let info = self.query_filesystem_info()?;
        *self.cached_info.write() = Some(info.clone());
        self.info_timestamp.store(now, Ordering::Relaxed);
        
        Ok(info)
    }
    
    fn query_filesystem_info(&self) -> Result<CachedBranchInfo, std::io::Error> {
        use std::ffi::CString;
        use std::mem::MaybeUninit;
        
        let path_cstr = CString::new(self.path.to_string_lossy().as_ref())?;
        let mut statvfs: MaybeUninit<libc::statvfs> = MaybeUninit::uninit();
        
        let result = unsafe {
            libc::statvfs(path_cstr.as_ptr(), statvfs.as_mut_ptr())
        };
        
        if result != 0 {
            return Err(std::io::Error::last_os_error());
        }
        
        let statvfs = unsafe { statvfs.assume_init() };
        
        Ok(CachedBranchInfo {
            total_space: statvfs.f_blocks * statvfs.f_frsize,
            free_space: statvfs.f_bfree * statvfs.f_frsize,
            available_space: statvfs.f_bavail * statvfs.f_frsize,
            readonly: (statvfs.f_flag & libc::ST_RDONLY) != 0,
            filesystem_type: "unknown".to_string(), // Could be enhanced
        })
    }
}
```

## Policy Implementations

### First Found (FF) Policy

```rust
pub struct FirstFoundCreatePolicy;

impl Policy for FirstFoundCreatePolicy {
    fn name(&self) -> &'static str { "ff" }
    fn description(&self) -> &'static str { "First Found - use first branch with sufficient space" }
}

impl CreatePolicy for FirstFoundCreatePolicy {
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut last_error = PolicyError::NoBranchesAvailable;
        
        for branch in branches {
            if !branch.allows_create() {
                last_error = PolicyError::ReadOnlyFilesystem;
                continue;
            }
            
            match branch.get_space_info() {
                Ok(info) => {
                    if info.readonly {
                        last_error = PolicyError::ReadOnlyFilesystem;
                        continue;
                    }
                    
                    if info.available_space < branch.min_free_space {
                        last_error = PolicyError::InsufficientSpace;
                        continue;
                    }
                    
                    return Ok(vec![branch.clone()]);
                }
                Err(_) => {
                    last_error = PolicyError::NoBranchesAvailable;
                    continue;
                }
            }
        }
        
        Err(last_error)
    }
    
    fn is_path_preserving(&self) -> bool { false }
}
```

### Most Free Space (MFS) Policy

```rust
pub struct MostFreeSpaceCreatePolicy;

impl Policy for MostFreeSpaceCreatePolicy {
    fn name(&self) -> &'static str { "mfs" }
    fn description(&self) -> &'static str { "Most Free Space - use branch with most available space" }
}

impl CreatePolicy for MostFreeSpaceCreatePolicy {
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut best_branch: Option<Arc<Branch>> = None;
        let mut max_space: u64 = 0;
        let mut last_error = PolicyError::NoBranchesAvailable;
        
        for branch in branches {
            if !branch.allows_create() {
                last_error = PolicyError::ReadOnlyFilesystem;
                continue;
            }
            
            match branch.get_space_info() {
                Ok(info) => {
                    if info.readonly {
                        last_error = PolicyError::ReadOnlyFilesystem;
                        continue;
                    }
                    
                    if info.available_space < branch.min_free_space {
                        last_error = PolicyError::InsufficientSpace;
                        continue;
                    }
                    
                    if info.available_space > max_space {
                        max_space = info.available_space;
                        best_branch = Some(branch.clone());
                    }
                }
                Err(_) => {
                    last_error = PolicyError::NoBranchesAvailable;
                    continue;
                }
            }
        }
        
        best_branch.map(|b| vec![b]).ok_or(last_error)
    }
    
    fn is_path_preserving(&self) -> bool { false }
}
```

### Existing Path First Found (EPFF) Policy

```rust
pub struct ExistingPathFirstFoundActionPolicy;

impl Policy for ExistingPathFirstFoundActionPolicy {
    fn name(&self) -> &'static str { "epff" }
    fn description(&self) -> &'static str { "Existing Path First Found - prefer existing path, else first found" }
}

impl ActionPolicy for ExistingPathFirstFoundActionPolicy {
    fn target_branches(
        &self,
        branches: &[Arc<Branch>],
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut found_branches = Vec::new();
        
        // First pass: look for existing files
        for branch in branches {
            let full_path = branch.path.join(path);
            if full_path.exists() {
                found_branches.push(branch.clone());
                break; // First found
            }
        }
        
        if found_branches.is_empty() {
            return Err(PolicyError::NoBranchesAvailable);
        }
        
        Ok(found_branches)
    }
}
```

### Proportional Free Random Distribution (PFRD) Policy

```rust
use rand::Rng;

pub struct ProportionalFreeRandomCreatePolicy {
    rng: parking_lot::Mutex<rand::rngs::ThreadRng>,
}

impl ProportionalFreeRandomCreatePolicy {
    pub fn new() -> Self {
        Self {
            rng: parking_lot::Mutex::new(rand::thread_rng()),
        }
    }
}

impl Policy for ProportionalFreeRandomCreatePolicy {
    fn name(&self) -> &'static str { "pfrd" }
    fn description(&self) -> &'static str { "Proportional Free Random Distribution - weight by available space" }
}

impl CreatePolicy for ProportionalFreeRandomCreatePolicy {
    fn select_branches(
        &self,
        branches: &[Arc<Branch>],
        _path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let mut eligible_branches = Vec::new();
        let mut total_weight = 0u64;
        let mut last_error = PolicyError::NoBranchesAvailable;
        
        // Collect eligible branches and their weights
        for branch in branches {
            if !branch.allows_create() {
                last_error = PolicyError::ReadOnlyFilesystem;
                continue;
            }
            
            match branch.get_space_info() {
                Ok(info) => {
                    if info.readonly {
                        last_error = PolicyError::ReadOnlyFilesystem;
                        continue;
                    }
                    
                    if info.available_space < branch.min_free_space {
                        last_error = PolicyError::InsufficientSpace;
                        continue;
                    }
                    
                    eligible_branches.push((branch.clone(), info.available_space));
                    total_weight += info.available_space;
                }
                Err(_) => {
                    last_error = PolicyError::NoBranchesAvailable;
                    continue;
                }
            }
        }
        
        if eligible_branches.is_empty() {
            return Err(last_error);
        }
        
        if total_weight == 0 {
            return Err(PolicyError::InsufficientSpace);
        }
        
        // Weighted random selection
        let threshold = {
            let mut rng = self.rng.lock();
            rng.gen_range(0..total_weight)
        };
        
        let mut accumulated = 0u64;
        for (branch, weight) in eligible_branches {
            accumulated += weight;
            if accumulated > threshold {
                return Ok(vec![branch]);
            }
        }
        
        // Fallback (shouldn't happen)
        Err(PolicyError::NoBranchesAvailable)
    }
    
    fn is_path_preserving(&self) -> bool { false }
}
```

## Policy Registry and Dynamic Dispatch

### Policy Registry

```rust
use std::collections::HashMap;
use std::sync::OnceLock;

pub struct PolicyRegistry {
    create_policies: HashMap<&'static str, Box<dyn CreatePolicy>>,
    search_policies: HashMap<&'static str, Box<dyn SearchPolicy>>,
    action_policies: HashMap<&'static str, Box<dyn ActionPolicy>>,
}

impl PolicyRegistry {
    pub fn new() -> Self {
        let mut registry = Self {
            create_policies: HashMap::new(),
            search_policies: HashMap::new(),
            action_policies: HashMap::new(),
        };
        
        registry.register_builtin_policies();
        registry
    }
    
    fn register_builtin_policies(&mut self) {
        // Create policies
        self.register_create_policy(Box::new(FirstFoundCreatePolicy));
        self.register_create_policy(Box::new(MostFreeSpaceCreatePolicy));
        self.register_create_policy(Box::new(ProportionalFreeRandomCreatePolicy::new()));
        
        // Search policies
        self.register_search_policy(Box::new(FirstFoundSearchPolicy));
        self.register_search_policy(Box::new(AllSearchPolicy));
        
        // Action policies
        self.register_action_policy(Box::new(AllActionPolicy));
        self.register_action_policy(Box::new(ExistingPathFirstFoundActionPolicy));
    }
    
    pub fn register_create_policy(&mut self, policy: Box<dyn CreatePolicy>) {
        self.create_policies.insert(policy.name(), policy);
    }
    
    pub fn register_search_policy(&mut self, policy: Box<dyn SearchPolicy>) {
        self.search_policies.insert(policy.name(), policy);
    }
    
    pub fn register_action_policy(&mut self, policy: Box<dyn ActionPolicy>) {
        self.action_policies.insert(policy.name(), policy);
    }
    
    pub fn get_create_policy(&self, name: &str) -> Option<&dyn CreatePolicy> {
        self.create_policies.get(name).map(|p| p.as_ref())
    }
    
    pub fn get_search_policy(&self, name: &str) -> Option<&dyn SearchPolicy> {
        self.search_policies.get(name).map(|p| p.as_ref())
    }
    
    pub fn get_action_policy(&self, name: &str) -> Option<&dyn ActionPolicy> {
        self.action_policies.get(name).map(|p| p.as_ref())
    }
    
    pub fn list_create_policies(&self) -> Vec<&'static str> {
        self.create_policies.keys().copied().collect()
    }
    
    pub fn list_search_policies(&self) -> Vec<&'static str> {
        self.search_policies.keys().copied().collect()
    }
    
    pub fn list_action_policies(&self) -> Vec<&'static str> {
        self.action_policies.keys().copied().collect()
    }
}

// Global registry instance
static POLICY_REGISTRY: OnceLock<PolicyRegistry> = OnceLock::new();

pub fn get_policy_registry() -> &'static PolicyRegistry {
    POLICY_REGISTRY.get_or_init(PolicyRegistry::new)
}
```

### Policy Resolution with Type Safety

```rust
use std::marker::PhantomData;

#[derive(Debug, Clone)]
pub struct PolicyRef<T> {
    name: String,
    _phantom: PhantomData<T>,
}

impl<T> PolicyRef<T> {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            _phantom: PhantomData,
        }
    }
    
    pub fn name(&self) -> &str {
        &self.name
    }
}

impl PolicyRef<dyn CreatePolicy> {
    pub fn resolve(&self) -> Result<&'static dyn CreatePolicy, PolicyError> {
        get_policy_registry()
            .get_create_policy(&self.name)
            .ok_or_else(|| PolicyError::BranchNotFound(self.name.clone()))
    }
}

impl PolicyRef<dyn SearchPolicy> {
    pub fn resolve(&self) -> Result<&'static dyn SearchPolicy, PolicyError> {
        get_policy_registry()
            .get_search_policy(&self.name)
            .ok_or_else(|| PolicyError::BranchNotFound(self.name.clone()))
    }
}

impl PolicyRef<dyn ActionPolicy> {
    pub fn resolve(&self) -> Result<&'static dyn ActionPolicy, PolicyError> {
        get_policy_registry()
            .get_action_policy(&self.name)
            .ok_or_else(|| PolicyError::BranchNotFound(self.name.clone()))
    }
}

// Type aliases for convenience
pub type CreatePolicyRef = PolicyRef<dyn CreatePolicy>;
pub type SearchPolicyRef = PolicyRef<dyn SearchPolicy>;
pub type ActionPolicyRef = PolicyRef<dyn ActionPolicy>;
```

## Policy Configuration Structure

### Function-Specific Policy Assignment

```rust
#[derive(Debug, Clone)]
pub struct FunctionPolicies {
    pub access: SearchPolicyRef,
    pub chmod: ActionPolicyRef,
    pub chown: ActionPolicyRef,
    pub create: CreatePolicyRef,
    pub getattr: SearchPolicyRef,
    pub getxattr: SearchPolicyRef,
    pub link: ActionPolicyRef,
    pub listxattr: SearchPolicyRef,
    pub mkdir: CreatePolicyRef,
    pub mknod: CreatePolicyRef,
    pub open: SearchPolicyRef,
    pub readlink: SearchPolicyRef,
    pub removexattr: ActionPolicyRef,
    pub rename: ActionPolicyRef,
    pub rmdir: ActionPolicyRef,
    pub setxattr: ActionPolicyRef,
    pub symlink: CreatePolicyRef,
    pub truncate: ActionPolicyRef,
    pub unlink: ActionPolicyRef,
    pub utimens: ActionPolicyRef,
}

impl Default for FunctionPolicies {
    fn default() -> Self {
        Self {
            access: SearchPolicyRef::new("ff"),
            chmod: ActionPolicyRef::new("epall"),
            chown: ActionPolicyRef::new("epall"),
            create: CreatePolicyRef::new("pfrd"),
            getattr: SearchPolicyRef::new("ff"),
            getxattr: SearchPolicyRef::new("ff"),
            link: ActionPolicyRef::new("epall"),
            listxattr: SearchPolicyRef::new("ff"),
            mkdir: CreatePolicyRef::new("pfrd"),
            mknod: CreatePolicyRef::new("pfrd"),
            open: SearchPolicyRef::new("ff"),
            readlink: SearchPolicyRef::new("ff"),
            removexattr: ActionPolicyRef::new("epall"),
            rename: ActionPolicyRef::new("epall"),
            rmdir: ActionPolicyRef::new("epall"),
            setxattr: ActionPolicyRef::new("epall"),
            symlink: CreatePolicyRef::new("pfrd"),
            truncate: ActionPolicyRef::new("epall"),
            unlink: ActionPolicyRef::new("epall"),
            utimens: ActionPolicyRef::new("epall"),
        }
    }
}
```

## Policy Execution Engine

### High-Level Policy Executor

```rust
pub struct PolicyExecutor {
    branches: Arc<parking_lot::RwLock<Vec<Arc<Branch>>>>,
    policies: Arc<parking_lot::RwLock<FunctionPolicies>>,
}

impl PolicyExecutor {
    pub fn new(
        branches: Vec<Arc<Branch>>,
        policies: FunctionPolicies,
    ) -> Self {
        Self {
            branches: Arc::new(parking_lot::RwLock::new(branches)),
            policies: Arc::new(parking_lot::RwLock::new(policies)),
        }
    }
    
    pub fn execute_create_policy(
        &self,
        policy_ref: &CreatePolicyRef,
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policy = policy_ref.resolve()?;
        let branches = self.branches.read();
        policy.select_branches(&branches, path)
    }
    
    pub fn execute_search_policy(
        &self,
        policy_ref: &SearchPolicyRef,
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policy = policy_ref.resolve()?;
        let branches = self.branches.read();
        policy.find_branches(&branches, path)
    }
    
    pub fn execute_action_policy(
        &self,
        policy_ref: &ActionPolicyRef,
        path: &Path,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policy = policy_ref.resolve()?;
        let branches = self.branches.read();
        policy.target_branches(&branches, path)
    }
    
    // Convenience methods for common operations
    pub fn select_create_branches(&self, path: &Path) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policies = self.policies.read();
        self.execute_create_policy(&policies.create, path)
    }
    
    pub fn find_file_branches(&self, path: &Path) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policies = self.policies.read();
        self.execute_search_policy(&policies.open, path)
    }
    
    pub fn get_function_policies(&self) -> FunctionPolicies {
        self.policies.read().clone()
    }
    
    pub fn update_function_policies(&self, new_policies: FunctionPolicies) {
        *self.policies.write() = new_policies;
    }
    
    pub fn update_branches(&self, new_branches: Vec<Arc<Branch>>) {
        *self.branches.write() = new_branches;
    }
}
```

## Testing Framework

### Policy Testing Utilities

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;
    
    struct TestBranch {
        temp_dir: TempDir,
        branch: Arc<Branch>,
    }
    
    impl TestBranch {
        fn new(mode: BranchMode, min_free_space: u64) -> Self {
            let temp_dir = TempDir::new().unwrap();
            let branch = Arc::new(Branch::new(
                temp_dir.path().to_path_buf(),
                mode,
                min_free_space,
            ));
            
            Self { temp_dir, branch }
        }
        
        fn create_file(&self, path: &str) -> std::io::Result<()> {
            let full_path = self.temp_dir.path().join(path);
            if let Some(parent) = full_path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(full_path, "test content")
        }
    }
    
    #[test]
    fn test_first_found_policy() {
        let branch1 = TestBranch::new(BranchMode::ReadWrite, 0);
        let branch2 = TestBranch::new(BranchMode::ReadWrite, 0);
        let branches = vec![branch1.branch.clone(), branch2.branch.clone()];
        
        let policy = FirstFoundCreatePolicy;
        let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
        
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].path, branch1.branch.path);
    }
    
    #[test]
    fn test_most_free_space_policy() {
        let branch1 = TestBranch::new(BranchMode::ReadWrite, 0);
        let branch2 = TestBranch::new(BranchMode::ReadWrite, 0);
        let branches = vec![branch1.branch.clone(), branch2.branch.clone()];
        
        let policy = MostFreeSpaceCreatePolicy;
        let result = policy.select_branches(&branches, Path::new("test.txt")).unwrap();
        
        assert_eq!(result.len(), 1);
        // Result should be the branch with more free space
    }
    
    #[test]
    fn test_existing_path_policy() {
        let branch1 = TestBranch::new(BranchMode::ReadWrite, 0);
        let branch2 = TestBranch::new(BranchMode::ReadWrite, 0);
        
        // Create file in branch2
        branch2.create_file("existing.txt").unwrap();
        
        let branches = vec![branch1.branch.clone(), branch2.branch.clone()];
        
        let policy = ExistingPathFirstFoundActionPolicy;
        let result = policy.target_branches(&branches, Path::new("existing.txt")).unwrap();
        
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].path, branch2.branch.path);
    }
    
    #[test]
    fn test_policy_registry() {
        let registry = PolicyRegistry::new();
        
        assert!(registry.get_create_policy("ff").is_some());
        assert!(registry.get_create_policy("mfs").is_some());
        assert!(registry.get_create_policy("nonexistent").is_none());
        
        let policies = registry.list_create_policies();
        assert!(policies.contains(&"ff"));
        assert!(policies.contains(&"mfs"));
    }
}
```

## Performance Considerations

### Policy Caching

```rust
use std::time::{Duration, Instant};

pub struct CachedPolicyResult {
    branches: Vec<Arc<Branch>>,
    timestamp: Instant,
    path: PathBuf,
    policy_name: String,
}

pub struct PolicyCache {
    cache: parking_lot::RwLock<HashMap<String, CachedPolicyResult>>,
    ttl: Duration,
}

impl PolicyCache {
    pub fn new(ttl: Duration) -> Self {
        Self {
            cache: parking_lot::RwLock::new(HashMap::new()),
            ttl,
        }
    }
    
    pub fn get(
        &self,
        policy_name: &str,
        path: &Path,
    ) -> Option<Vec<Arc<Branch>>> {
        let cache = self.cache.read();
        let key = format!("{}:{}", policy_name, path.display());
        
        if let Some(entry) = cache.get(&key) {
            if entry.timestamp.elapsed() < self.ttl {
                return Some(entry.branches.clone());
            }
        }
        
        None
    }
    
    pub fn insert(
        &self,
        policy_name: &str,
        path: &Path,
        branches: Vec<Arc<Branch>>,
    ) {
        let mut cache = self.cache.write();
        let key = format!("{}:{}", policy_name, path.display());
        
        cache.insert(key, CachedPolicyResult {
            branches,
            timestamp: Instant::now(),
            path: path.to_path_buf(),
            policy_name: policy_name.to_string(),
        });
    }
    
    pub fn invalidate(&self, path: &Path) {
        let mut cache = self.cache.write();
        let path_str = path.display().to_string();
        
        cache.retain(|key, _| {
            !key.ends_with(&format!(":{}", path_str))
        });
    }
}
```

## Integration Points

### FUSE Operation Integration

```rust
impl PolicyExecutor {
    pub async fn handle_create_operation(
        &self,
        path: &Path,
        mode: u32,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policies = self.policies.read();
        
        // Try primary create policy
        match self.execute_create_policy(&policies.create, path) {
            Ok(branches) => Ok(branches),
            Err(PolicyError::InsufficientSpace) => {
                // Fallback to first-found if no space
                let ff_policy = CreatePolicyRef::new("ff");
                self.execute_create_policy(&ff_policy, path)
            }
            Err(e) => Err(e),
        }
    }
    
    pub async fn handle_search_operation(
        &self,
        path: &Path,
        operation: &str,
    ) -> Result<Vec<Arc<Branch>>, PolicyError> {
        let policies = self.policies.read();
        
        let policy_ref = match operation {
            "open" => &policies.open,
            "getattr" => &policies.getattr,
            "access" => &policies.access,
            _ => &policies.open, // Default fallback
        };
        
        self.execute_search_policy(policy_ref, path)
    }
}
```

This implementation provides a solid foundation for the policy engine in Rust, leveraging type safety, performance optimizations, and idiomatic Rust patterns while maintaining compatibility with the original mergerfs design.