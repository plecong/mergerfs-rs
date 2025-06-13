# Error Handling System Design for Rust

## Overview

This guide provides a comprehensive approach to implementing mergerfs's sophisticated error handling system in Rust, leveraging `thiserror`, custom error types, error priority systems, and graceful degradation patterns while maintaining type safety and performance.

## Core Error Architecture

### Error Type Hierarchy

```rust
use thiserror::Error;
use std::path::PathBuf;

#[derive(Error, Debug, Clone)]
pub enum MergerFsError {
    #[error("I/O error: {0}")]
    Io(#[from] IoErrorWrapper),
    
    #[error("Policy error: {0}")]
    Policy(#[from] PolicyError),
    
    #[error("Configuration error: {0}")]
    Config(#[from] ConfigError),
    
    #[error("Branch error: {0}")]
    Branch(#[from] BranchError),
    
    #[error("FUSE error: {0}")]
    Fuse(#[from] FuseError),
    
    #[error("Permission denied for path: {path}")]
    PermissionDenied { path: PathBuf },
    
    #[error("Path not found: {path}")]
    PathNotFound { path: PathBuf },
    
    #[error("No space left on device for path: {path}")]
    NoSpaceLeft { path: PathBuf },
    
    #[error("Read-only filesystem for path: {path}")]
    ReadOnlyFilesystem { path: PathBuf },
    
    #[error("Cross-device operation attempted")]
    CrossDevice,
    
    #[error("Operation not supported")]
    NotSupported,
}

// Wrapper for std::io::Error to make it cloneable
#[derive(Error, Debug, Clone)]
#[error("IO error: {message}")]
pub struct IoErrorWrapper {
    pub message: String,
    pub errno: Option<i32>,
}

impl From<std::io::Error> for IoErrorWrapper {
    fn from(err: std::io::Error) -> Self {
        Self {
            message: err.to_string(),
            errno: err.raw_os_error(),
        }
    }
}

impl From<std::io::Error> for MergerFsError {
    fn from(err: std::io::Error) -> Self {
        MergerFsError::Io(IoErrorWrapper::from(err))
    }
}
```

### Error Priority System

```rust
use std::cmp::Ordering;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorPriority {
    Critical = 4,    // System errors, corruption
    High = 3,        // Permission denied, access errors
    Medium = 2,      // Resource errors (space, read-only)
    Low = 1,         // Path not found, file not exists
    None = 0,        // No error
}

impl PartialOrd for ErrorPriority {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for ErrorPriority {
    fn cmp(&self, other: &Self) -> Ordering {
        (*self as u8).cmp(&(*other as u8))
    }
}

impl MergerFsError {
    pub fn priority(&self) -> ErrorPriority {
        match self {
            MergerFsError::Io(io_err) => {
                match io_err.errno {
                    Some(libc::EACCES) => ErrorPriority::High,
                    Some(libc::EPERM) => ErrorPriority::High,
                    Some(libc::EROFS) => ErrorPriority::Medium,
                    Some(libc::ENOSPC) => ErrorPriority::Medium,
                    Some(libc::ENOENT) => ErrorPriority::Low,
                    Some(libc::EIO) => ErrorPriority::Critical,
                    Some(libc::ENODEV) => ErrorPriority::Critical,
                    _ => ErrorPriority::Low,
                }
            }
            MergerFsError::PermissionDenied { .. } => ErrorPriority::High,
            MergerFsError::ReadOnlyFilesystem { .. } => ErrorPriority::Medium,
            MergerFsError::NoSpaceLeft { .. } => ErrorPriority::Medium,
            MergerFsError::PathNotFound { .. } => ErrorPriority::Low,
            MergerFsError::Policy(_) => ErrorPriority::Medium,
            MergerFsError::Config(_) => ErrorPriority::High,
            MergerFsError::Branch(_) => ErrorPriority::Medium,
            MergerFsError::Fuse(_) => ErrorPriority::Critical,
            MergerFsError::CrossDevice => ErrorPriority::Medium,
            MergerFsError::NotSupported => ErrorPriority::Low,
        }
    }
    
    pub fn errno(&self) -> i32 {
        match self {
            MergerFsError::Io(io_err) => io_err.errno.unwrap_or(libc::EIO),
            MergerFsError::PermissionDenied { .. } => libc::EACCES,
            MergerFsError::PathNotFound { .. } => libc::ENOENT,
            MergerFsError::NoSpaceLeft { .. } => libc::ENOSPC,
            MergerFsError::ReadOnlyFilesystem { .. } => libc::EROFS,
            MergerFsError::CrossDevice => libc::EXDEV,
            MergerFsError::NotSupported => libc::ENOTSUP,
            MergerFsError::Policy(policy_err) => policy_err.errno(),
            MergerFsError::Config(_) => libc::EINVAL,
            MergerFsError::Branch(_) => libc::EIO,
            MergerFsError::Fuse(_) => libc::EIO,
        }
    }
    
    pub fn is_temporary(&self) -> bool {
        match self {
            MergerFsError::Io(io_err) => {
                matches!(io_err.errno, 
                    Some(libc::EAGAIN) | 
                    Some(libc::EWOULDBLOCK) |
                    Some(libc::EINTR) |
                    Some(libc::ETIMEDOUT)
                )
            }
            MergerFsError::NoSpaceLeft { .. } => true, // Might be temporary
            _ => false,
        }
    }
}
```

## Multi-Branch Error Aggregation

### Error Collection and Prioritization

```rust
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct BranchResult<T> {
    pub branch_path: PathBuf,
    pub result: Result<T, MergerFsError>,
}

#[derive(Debug)]
pub struct MultibranchError {
    pub operation: String,
    pub path: PathBuf,
    pub branch_results: Vec<BranchResult<()>>,
    pub final_error: MergerFsError,
}

impl std::fmt::Display for MultibranchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Operation '{}' failed on path '{}': {}", 
               self.operation, self.path.display(), self.final_error)?;
        
        write!(f, "\nBranch attempts:")?;
        for result in &self.branch_results {
            write!(f, "\n  {}: ", result.branch_path.display())?;
            match &result.result {
                Ok(_) => write!(f, "SUCCESS")?,
                Err(e) => write!(f, "FAILED ({})", e)?,
            }
        }
        Ok(())
    }
}

impl std::error::Error for MultibranchError {}

pub struct ErrorAggregator {
    operation: String,
    path: PathBuf,
    results: Vec<BranchResult<()>>,
    highest_priority_error: Option<MergerFsError>,
}

impl ErrorAggregator {
    pub fn new(operation: impl Into<String>, path: PathBuf) -> Self {
        Self {
            operation: operation.into(),
            path,
            results: Vec::new(),
            highest_priority_error: None,
        }
    }
    
    pub fn add_success(&mut self, branch_path: PathBuf) {
        self.results.push(BranchResult {
            branch_path,
            result: Ok(()),
        });
    }
    
    pub fn add_error(&mut self, branch_path: PathBuf, error: MergerFsError) {
        // Update highest priority error
        match &self.highest_priority_error {
            None => self.highest_priority_error = Some(error.clone()),
            Some(current) => {
                if error.priority() > current.priority() {
                    self.highest_priority_error = Some(error.clone());
                }
            }
        }
        
        self.results.push(BranchResult {
            branch_path,
            result: Err(error),
        });
    }
    
    pub fn has_successes(&self) -> bool {
        self.results.iter().any(|r| r.result.is_ok())
    }
    
    pub fn success_count(&self) -> usize {
        self.results.iter().filter(|r| r.result.is_ok()).count()
    }
    
    pub fn error_count(&self) -> usize {
        self.results.iter().filter(|r| r.result.is_err()).count()
    }
    
    pub fn into_result(self) -> Result<(), MultibranchError> {
        if self.has_successes() {
            Ok(())
        } else {
            let final_error = self.highest_priority_error
                .unwrap_or(MergerFsError::PathNotFound { path: self.path.clone() });
            
            Err(MultibranchError {
                operation: self.operation,
                path: self.path,
                branch_results: self.results,
                final_error,
            })
        }
    }
    
    pub fn into_partial_result(self) -> Result<usize, MultibranchError> {
        let success_count = self.success_count();
        if success_count > 0 {
            Ok(success_count)
        } else {
            self.into_result().map(|_| 0)
        }
    }
}

// Macro for collecting errors across multiple branch operations
macro_rules! try_all_branches {
    ($aggregator:expr, $branches:expr, $operation:expr) => {{
        for branch in $branches {
            match $operation(branch) {
                Ok(_) => $aggregator.add_success(branch.path.clone()),
                Err(e) => $aggregator.add_error(branch.path.clone(), e),
            }
        }
    }};
}

// Example usage
pub async fn delete_file_from_all_branches(
    branches: &[Arc<Branch>],
    path: &std::path::Path,
) -> Result<usize, MultibranchError> {
    let mut aggregator = ErrorAggregator::new("unlink", path.to_path_buf());
    
    try_all_branches!(aggregator, branches, |branch: &Arc<Branch>| {
        let full_path = branch.path.join(path);
        std::fs::remove_file(&full_path)
            .map_err(|e| MergerFsError::from(e))
    });
    
    aggregator.into_partial_result()
}
```

## Graceful Degradation Patterns

### Branch Failure Recovery

```rust
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct BranchHealth {
    is_healthy: AtomicBool,
    last_failure: parking_lot::RwLock<Option<Instant>>,
    consecutive_failures: parking_lot::RwLock<u32>,
    backoff_until: parking_lot::RwLock<Option<Instant>>,
}

impl BranchHealth {
    pub fn new() -> Self {
        Self {
            is_healthy: AtomicBool::new(true),
            last_failure: parking_lot::RwLock::new(None),
            consecutive_failures: parking_lot::RwLock::new(0),
            backoff_until: parking_lot::RwLock::new(None),
        }
    }
    
    pub fn is_available(&self) -> bool {
        if !self.is_healthy.load(Ordering::Relaxed) {
            return false;
        }
        
        if let Some(backoff_until) = *self.backoff_until.read() {
            if Instant::now() < backoff_until {
                return false;
            }
            
            // Backoff period expired, try to recover
            *self.backoff_until.write() = None;
            self.is_healthy.store(true, Ordering::Relaxed);
        }
        
        true
    }
    
    pub fn record_success(&self) {
        self.is_healthy.store(true, Ordering::Relaxed);
        *self.consecutive_failures.write() = 0;
        *self.last_failure.write() = None;
        *self.backoff_until.write() = None;
    }
    
    pub fn record_failure(&self, error: &MergerFsError) {
        *self.last_failure.write() = Some(Instant::now());
        
        let mut failures = self.consecutive_failures.write();
        *failures += 1;
        
        // Exponential backoff for temporary errors
        if error.is_temporary() && *failures > 3 {
            let backoff_duration = Duration::from_millis(100 * (1 << (*failures).min(10)));
            *self.backoff_until.write() = Some(Instant::now() + backoff_duration);
            self.is_healthy.store(false, Ordering::Relaxed);
        } else if *failures > 10 {
            // Mark as unhealthy after too many failures
            self.is_healthy.store(false, Ordering::Relaxed);
        }
    }
    
    pub fn force_unhealthy(&self) {
        self.is_healthy.store(false, Ordering::Relaxed);
        *self.consecutive_failures.write() = u32::MAX;
    }
    
    pub fn get_stats(&self) -> BranchHealthStats {
        BranchHealthStats {
            is_healthy: self.is_healthy.load(Ordering::Relaxed),
            consecutive_failures: *self.consecutive_failures.read(),
            last_failure: *self.last_failure.read(),
            backoff_until: *self.backoff_until.read(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct BranchHealthStats {
    pub is_healthy: bool,
    pub consecutive_failures: u32,
    pub last_failure: Option<Instant>,
    pub backoff_until: Option<Instant>,
}

// Enhanced Branch with health tracking
pub struct HealthyBranch {
    pub branch: Arc<Branch>,
    pub health: BranchHealth,
}

impl HealthyBranch {
    pub fn new(branch: Arc<Branch>) -> Self {
        Self {
            branch,
            health: BranchHealth::new(),
        }
    }
    
    pub fn is_available(&self) -> bool {
        self.health.is_available() && self.branch.allows_operations()
    }
    
    pub async fn execute_operation<F, T>(&self, operation: F) -> Result<T, MergerFsError>
    where
        F: FnOnce(&Branch) -> Result<T, MergerFsError>,
    {
        if !self.is_available() {
            return Err(MergerFsError::PathNotFound { 
                path: self.branch.path.clone() 
            });
        }
        
        match operation(&self.branch) {
            Ok(result) => {
                self.health.record_success();
                Ok(result)
            }
            Err(error) => {
                self.health.record_failure(&error);
                Err(error)
            }
        }
    }
}
```

### Retry Mechanisms

```rust
use std::future::Future;

#[derive(Debug, Clone)]
pub struct RetryConfig {
    pub max_attempts: u32,
    pub base_delay: Duration,
    pub max_delay: Duration,
    pub backoff_multiplier: f64,
    pub jitter: bool,
}

impl Default for RetryConfig {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            base_delay: Duration::from_millis(100),
            max_delay: Duration::from_secs(10),
            backoff_multiplier: 2.0,
            jitter: true,
        }
    }
}

pub struct RetryableOperation<F> {
    operation: F,
    config: RetryConfig,
}

impl<F> RetryableOperation<F> {
    pub fn new(operation: F, config: RetryConfig) -> Self {
        Self { operation, config }
    }
    
    pub async fn execute<T, E>(&mut self) -> Result<T, E>
    where
        F: FnMut() -> Result<T, E>,
        E: Clone + std::fmt::Debug,
        MergerFsError: From<E>,
    {
        let mut last_error = None;
        
        for attempt in 1..=self.config.max_attempts {
            match (self.operation)() {
                Ok(result) => return Ok(result),
                Err(error) => {
                    let mergerfs_error = MergerFsError::from(error.clone());
                    last_error = Some(error);
                    
                    // Don't retry permanent errors
                    if !mergerfs_error.is_temporary() {
                        break;
                    }
                    
                    // Don't sleep on the last attempt
                    if attempt < self.config.max_attempts {
                        let delay = self.calculate_delay(attempt);
                        tokio::time::sleep(delay).await;
                    }
                }
            }
        }
        
        Err(last_error.unwrap())
    }
    
    fn calculate_delay(&self, attempt: u32) -> Duration {
        let mut delay = self.config.base_delay.as_millis() as f64 
            * self.config.backoff_multiplier.powi(attempt as i32 - 1);
        
        if self.config.jitter {
            delay *= 0.5 + rand::random::<f64>() * 0.5; // ±50% jitter
        }
        
        let delay_ms = delay.min(self.config.max_delay.as_millis() as f64) as u64;
        Duration::from_millis(delay_ms)
    }
}

// Convenience function for retryable operations
pub async fn retry_operation<F, T, E>(
    mut operation: F,
    config: RetryConfig,
) -> Result<T, E>
where
    F: FnMut() -> Result<T, E>,
    E: Clone + std::fmt::Debug,
    MergerFsError: From<E>,
{
    RetryableOperation::new(&mut operation, config).execute().await
}

// Async version
pub async fn retry_async_operation<F, Fut, T, E>(
    mut operation: F,
    config: RetryConfig,
) -> Result<T, E>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, E>>,
    E: Clone + std::fmt::Debug,
    MergerFsError: From<E>,
{
    let mut last_error = None;
    
    for attempt in 1..=config.max_attempts {
        match operation().await {
            Ok(result) => return Ok(result),
            Err(error) => {
                let mergerfs_error = MergerFsError::from(error.clone());
                last_error = Some(error);
                
                if !mergerfs_error.is_temporary() {
                    break;
                }
                
                if attempt < config.max_attempts {
                    let delay = calculate_retry_delay(&config, attempt);
                    tokio::time::sleep(delay).await;
                }
            }
        }
    }
    
    Err(last_error.unwrap())
}

fn calculate_retry_delay(config: &RetryConfig, attempt: u32) -> Duration {
    let mut delay = config.base_delay.as_millis() as f64 
        * config.backoff_multiplier.powi(attempt as i32 - 1);
    
    if config.jitter {
        delay *= 0.5 + rand::random::<f64>() * 0.5;
    }
    
    let delay_ms = delay.min(config.max_delay.as_millis() as f64) as u64;
    Duration::from_millis(delay_ms)
}
```

## Transaction-like Operations

### Atomic Operations with Rollback

```rust
use std::collections::VecDeque;

pub trait Rollbackable {
    type Error;
    fn rollback(&self) -> Result<(), Self::Error>;
}

#[derive(Debug)]
pub struct RollbackAction {
    description: String,
    action: Box<dyn FnOnce() -> Result<(), MergerFsError> + Send>,
}

impl RollbackAction {
    pub fn new<F>(description: impl Into<String>, action: F) -> Self
    where
        F: FnOnce() -> Result<(), MergerFsError> + Send + 'static,
    {
        Self {
            description: description.into(),
            action: Box::new(action),
        }
    }
    
    pub fn execute(self) -> Result<(), MergerFsError> {
        (self.action)()
    }
}

pub struct AtomicOperation {
    rollback_stack: VecDeque<RollbackAction>,
    committed: bool,
}

impl AtomicOperation {
    pub fn new() -> Self {
        Self {
            rollback_stack: VecDeque::new(),
            committed: false,
        }
    }
    
    pub fn add_rollback<F>(&mut self, description: impl Into<String>, rollback: F)
    where
        F: FnOnce() -> Result<(), MergerFsError> + Send + 'static,
    {
        self.rollback_stack.push_front(RollbackAction::new(description, rollback));
    }
    
    pub fn execute_step<F, T>(&mut self, step: F) -> Result<T, MergerFsError>
    where
        F: FnOnce(&mut Self) -> Result<T, MergerFsError>,
    {
        step(self)
    }
    
    pub fn commit(mut self) -> Result<(), MergerFsError> {
        self.committed = true;
        Ok(())
    }
    
    pub fn rollback(mut self) -> Result<(), MergerFsError> {
        let mut rollback_errors = Vec::new();
        
        while let Some(action) = self.rollback_stack.pop_front() {
            if let Err(e) = action.execute() {
                rollback_errors.push(e);
            }
        }
        
        if rollback_errors.is_empty() {
            Ok(())
        } else {
            // Return the first rollback error, but log all of them
            for (i, error) in rollback_errors.iter().enumerate() {
                eprintln!("Rollback error {}: {}", i + 1, error);
            }
            Err(rollback_errors.into_iter().next().unwrap())
        }
    }
}

impl Drop for AtomicOperation {
    fn drop(&mut self) {
        if !self.committed && !self.rollback_stack.is_empty() {
            eprintln!("AtomicOperation dropped without commit or explicit rollback");
            // Attempt best-effort rollback
            let _ = std::mem::replace(self, AtomicOperation::new()).rollback();
        }
    }
}

// Example: Atomic file move across branches
pub async fn atomic_move_file(
    src_branch: &Arc<Branch>,
    dst_branch: &Arc<Branch>,
    src_path: &std::path::Path,
    dst_path: &std::path::Path,
) -> Result<(), MergerFsError> {
    let mut operation = AtomicOperation::new();
    
    let src_full = src_branch.path.join(src_path);
    let dst_full = dst_branch.path.join(dst_path);
    let temp_path = dst_full.with_extension("tmp");
    
    // Step 1: Copy file to temporary location
    operation.execute_step(|op| {
        std::fs::copy(&src_full, &temp_path)?;
        
        // Add rollback for temporary file
        let temp_path_clone = temp_path.clone();
        op.add_rollback("remove temporary file", move || {
            std::fs::remove_file(&temp_path_clone)
                .map_err(MergerFsError::from)
        });
        
        Ok(())
    })?;
    
    // Step 2: Atomic rename to final location
    operation.execute_step(|op| {
        std::fs::rename(&temp_path, &dst_full)?;
        
        // Add rollback for final file (restore to temp)
        let dst_full_clone = dst_full.clone();
        let temp_path_clone = temp_path.clone();
        op.add_rollback("restore to temporary location", move || {
            std::fs::rename(&dst_full_clone, &temp_path_clone)
                .map_err(MergerFsError::from)
        });
        
        Ok(())
    })?;
    
    // Step 3: Remove original file
    operation.execute_step(|op| {
        std::fs::remove_file(&src_full)?;
        
        // Add rollback to restore original file
        let src_full_clone = src_full.clone();
        let dst_full_clone = dst_full.clone();
        op.add_rollback("restore original file", move || {
            std::fs::copy(&dst_full_clone, &src_full_clone)
                .map_err(MergerFsError::from)
                .map(|_| ())
        });
        
        Ok(())
    })?;
    
    // Commit the transaction
    operation.commit()
}
```

## Error Context and Debugging

### Rich Error Context

```rust
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct ErrorContext {
    operation: String,
    path: PathBuf,
    branch_paths: Vec<PathBuf>,
    metadata: HashMap<String, String>,
    timestamp: std::time::SystemTime,
    thread_id: String,
}

impl ErrorContext {
    pub fn new(operation: impl Into<String>, path: PathBuf) -> Self {
        Self {
            operation: operation.into(),
            path,
            branch_paths: Vec::new(),
            metadata: HashMap::new(),
            timestamp: std::time::SystemTime::now(),
            thread_id: format!("{:?}", std::thread::current().id()),
        }
    }
    
    pub fn add_branch(&mut self, branch_path: PathBuf) -> &mut Self {
        self.branch_paths.push(branch_path);
        self
    }
    
    pub fn add_metadata(&mut self, key: impl Into<String>, value: impl Into<String>) -> &mut Self {
        self.metadata.insert(key.into(), value.into());
        self
    }
    
    pub fn add_user_context(&mut self, uid: u32, gid: u32, pid: u32) -> &mut Self {
        self.metadata.insert("uid".to_string(), uid.to_string());
        self.metadata.insert("gid".to_string(), gid.to_string());
        self.metadata.insert("pid".to_string(), pid.to_string());
        self
    }
}

#[derive(Debug, Clone)]
pub struct ContextualError {
    pub error: MergerFsError,
    pub context: ErrorContext,
    pub chain: Vec<MergerFsError>,
}

impl std::fmt::Display for ContextualError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Error in operation '{}' on path '{}': {}", 
               self.context.operation, 
               self.context.path.display(), 
               self.error)?;
        
        if !self.context.branch_paths.is_empty() {
            write!(f, "\nBranches attempted: {:?}", self.context.branch_paths)?;
        }
        
        if !self.context.metadata.is_empty() {
            write!(f, "\nContext: {:?}", self.context.metadata)?;
        }
        
        if !self.chain.is_empty() {
            write!(f, "\nError chain:")?;
            for (i, err) in self.chain.iter().enumerate() {
                write!(f, "\n  {}: {}", i + 1, err)?;
            }
        }
        
        Ok(())
    }
}

impl std::error::Error for ContextualError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
    }
}

// Error builder for fluent API
pub struct ErrorBuilder {
    context: ErrorContext,
    chain: Vec<MergerFsError>,
}

impl ErrorBuilder {
    pub fn new(operation: impl Into<String>, path: PathBuf) -> Self {
        Self {
            context: ErrorContext::new(operation, path),
            chain: Vec::new(),
        }
    }
    
    pub fn branch(mut self, branch_path: PathBuf) -> Self {
        self.context.add_branch(branch_path);
        self
    }
    
    pub fn metadata(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.context.add_metadata(key, value);
        self
    }
    
    pub fn user_context(mut self, uid: u32, gid: u32, pid: u32) -> Self {
        self.context.add_user_context(uid, gid, pid);
        self
    }
    
    pub fn caused_by(mut self, error: MergerFsError) -> Self {
        self.chain.push(error);
        self
    }
    
    pub fn build(self, error: MergerFsError) -> ContextualError {
        ContextualError {
            error,
            context: self.context,
            chain: self.chain,
        }
    }
}

// Convenience macro for creating contextual errors
macro_rules! contextual_error {
    ($operation:expr, $path:expr, $error:expr) => {
        ErrorBuilder::new($operation, $path.to_path_buf()).build($error)
    };
    
    ($operation:expr, $path:expr, $error:expr, $($key:expr => $value:expr),*) => {{
        let mut builder = ErrorBuilder::new($operation, $path.to_path_buf());
        $(
            builder = builder.metadata($key, $value);
        )*
        builder.build($error)
    }};
}
```

## Logging and Metrics Integration

### Structured Error Logging

```rust
use tracing::{error, warn, info, debug};
use serde_json::json;

pub trait ErrorLogging {
    fn log_error(&self, error: &ContextualError);
    fn log_warning(&self, error: &MergerFsError);
    fn log_recovery(&self, operation: &str, original_error: &MergerFsError);
}

pub struct StructuredErrorLogger {
    component: String,
}

impl StructuredErrorLogger {
    pub fn new(component: impl Into<String>) -> Self {
        Self {
            component: component.into(),
        }
    }
}

impl ErrorLogging for StructuredErrorLogger {
    fn log_error(&self, error: &ContextualError) {
        let context_json = json!({
            "component": self.component,
            "operation": error.context.operation,
            "path": error.context.path,
            "branch_paths": error.context.branch_paths,
            "metadata": error.context.metadata,
            "thread_id": error.context.thread_id,
            "timestamp": error.context.timestamp,
            "errno": error.error.errno(),
            "priority": format!("{:?}", error.error.priority()),
            "error_chain": error.chain.iter().map(|e| e.to_string()).collect::<Vec<_>>(),
        });
        
        error!(
            target: "mergerfs::error",
            error = %error.error,
            context = %context_json,
            "Operation failed"
        );
    }
    
    fn log_warning(&self, error: &MergerFsError) {
        warn!(
            target: "mergerfs::warning",
            component = %self.component,
            error = %error,
            errno = %error.errno(),
            priority = ?error.priority(),
            "Recoverable error occurred"
        );
    }
    
    fn log_recovery(&self, operation: &str, original_error: &MergerFsError) {
        info!(
            target: "mergerfs::recovery",
            component = %self.component,
            operation = %operation,
            original_error = %original_error,
            "Recovered from error"
        );
    }
}

// Global error metrics
use std::sync::atomic::{AtomicU64, Ordering};

pub struct ErrorMetrics {
    total_errors: AtomicU64,
    errors_by_type: parking_lot::RwLock<HashMap<String, u64>>,
    errors_by_priority: parking_lot::RwLock<HashMap<ErrorPriority, u64>>,
}

impl ErrorMetrics {
    pub fn new() -> Self {
        Self {
            total_errors: AtomicU64::new(0),
            errors_by_type: parking_lot::RwLock::new(HashMap::new()),
            errors_by_priority: parking_lot::RwLock::new(HashMap::new()),
        }
    }
    
    pub fn record_error(&self, error: &MergerFsError) {
        self.total_errors.fetch_add(1, Ordering::Relaxed);
        
        let error_type = std::any::type_name_of_val(error);
        *self.errors_by_type.write()
            .entry(error_type.to_string())
            .or_insert(0) += 1;
        
        *self.errors_by_priority.write()
            .entry(error.priority())
            .or_insert(0) += 1;
    }
    
    pub fn get_total_errors(&self) -> u64 {
        self.total_errors.load(Ordering::Relaxed)
    }
    
    pub fn get_error_stats(&self) -> (HashMap<String, u64>, HashMap<ErrorPriority, u64>) {
        (
            self.errors_by_type.read().clone(),
            self.errors_by_priority.read().clone(),
        )
    }
}

lazy_static::lazy_static! {
    pub static ref GLOBAL_ERROR_METRICS: ErrorMetrics = ErrorMetrics::new();
    pub static ref GLOBAL_ERROR_LOGGER: StructuredErrorLogger = 
        StructuredErrorLogger::new("mergerfs");
}

// Convenience trait for automatic error logging
pub trait LoggableError {
    fn log_and_return(self) -> Self;
}

impl LoggableError for MergerFsError {
    fn log_and_return(self) -> Self {
        GLOBAL_ERROR_METRICS.record_error(&self);
        GLOBAL_ERROR_LOGGER.log_warning(&self);
        self
    }
}

impl LoggableError for ContextualError {
    fn log_and_return(self) -> Self {
        GLOBAL_ERROR_METRICS.record_error(&self.error);
        GLOBAL_ERROR_LOGGER.log_error(&self);
        self
    }
}
```

## Testing Error Conditions

### Error Injection Framework

```rust
use std::sync::Arc;
use parking_lot::RwLock;

#[derive(Debug, Clone)]
pub enum ErrorInjection {
    AlwaysFail(MergerFsError),
    FailAfter(u32), // Fail after N successful operations
    FailProbability(f64), // Fail with given probability (0.0 to 1.0)
    FailOnPath(PathBuf, MergerFsError),
    FailOnOperation(String, MergerFsError),
}

pub struct ErrorInjector {
    injections: Arc<RwLock<Vec<ErrorInjection>>>,
    operation_count: Arc<parking_lot::RwLock<HashMap<String, u32>>>,
}

impl ErrorInjector {
    pub fn new() -> Self {
        Self {
            injections: Arc::new(RwLock::new(Vec::new())),
            operation_count: Arc::new(parking_lot::RwLock::new(HashMap::new())),
        }
    }
    
    pub fn add_injection(&self, injection: ErrorInjection) {
        self.injections.write().push(injection);
    }
    
    pub fn clear_injections(&self) {
        self.injections.write().clear();
        self.operation_count.write().clear();
    }
    
    pub fn should_inject_error(
        &self,
        operation: &str,
        path: &std::path::Path,
    ) -> Option<MergerFsError> {
        // Update operation count
        {
            let mut counts = self.operation_count.write();
            *counts.entry(operation.to_string()).or_insert(0) += 1;
        }
        
        let injections = self.injections.read();
        let counts = self.operation_count.read();
        
        for injection in injections.iter() {
            match injection {
                ErrorInjection::AlwaysFail(error) => {
                    return Some(error.clone());
                }
                ErrorInjection::FailAfter(n) => {
                    if let Some(count) = counts.get(operation) {
                        if *count > *n {
                            return Some(MergerFsError::Io(IoErrorWrapper {
                                message: "Injected failure".to_string(),
                                errno: Some(libc::EIO),
                            }));
                        }
                    }
                }
                ErrorInjection::FailProbability(prob) => {
                    if rand::random::<f64>() < *prob {
                        return Some(MergerFsError::Io(IoErrorWrapper {
                            message: "Random injected failure".to_string(),
                            errno: Some(libc::EIO),
                        }));
                    }
                }
                ErrorInjection::FailOnPath(fail_path, error) => {
                    if path == fail_path {
                        return Some(error.clone());
                    }
                }
                ErrorInjection::FailOnOperation(fail_op, error) => {
                    if operation == fail_op {
                        return Some(error.clone());
                    }
                }
            }
        }
        
        None
    }
}

// Global error injector for testing
lazy_static::lazy_static! {
    pub static ref GLOBAL_ERROR_INJECTOR: ErrorInjector = ErrorInjector::new();
}

// Macro for operations that support error injection
macro_rules! with_error_injection {
    ($operation:expr, $path:expr, $body:expr) => {{
        #[cfg(test)]
        {
            if let Some(error) = GLOBAL_ERROR_INJECTOR.should_inject_error($operation, $path) {
                return Err(error);
            }
        }
        $body
    }};
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    
    #[test]
    fn test_error_priority_ordering() {
        let high_error = MergerFsError::PermissionDenied { 
            path: PathBuf::from("/test") 
        };
        let low_error = MergerFsError::PathNotFound { 
            path: PathBuf::from("/test") 
        };
        
        assert!(high_error.priority() > low_error.priority());
    }
    
    #[test]
    fn test_error_aggregation() {
        let mut aggregator = ErrorAggregator::new("test_op", PathBuf::from("/test"));
        
        aggregator.add_error(
            PathBuf::from("/branch1"),
            MergerFsError::PathNotFound { path: PathBuf::from("/test") },
        );
        aggregator.add_error(
            PathBuf::from("/branch2"),
            MergerFsError::PermissionDenied { path: PathBuf::from("/test") },
        );
        
        let result = aggregator.into_result();
        assert!(result.is_err());
        
        let error = result.unwrap_err();
        // Should report the higher priority error (PermissionDenied)
        assert!(matches!(error.final_error, MergerFsError::PermissionDenied { .. }));
    }
    
    #[tokio::test]
    async fn test_error_injection() {
        let injector = ErrorInjector::new();
        injector.add_injection(ErrorInjection::FailOnOperation(
            "test_op".to_string(),
            MergerFsError::Io(IoErrorWrapper {
                message: "Test error".to_string(),
                errno: Some(libc::EIO),
            }),
        ));
        
        let result = injector.should_inject_error("test_op", Path::new("/test"));
        assert!(result.is_some());
        
        let result = injector.should_inject_error("other_op", Path::new("/test"));
        assert!(result.is_none());
    }
}
```

This comprehensive error handling system provides:

1. **Hierarchical error types** with automatic errno conversion
2. **Error priority system** for multi-branch operation error selection
3. **Graceful degradation** with branch health tracking and exponential backoff
4. **Retry mechanisms** with configurable policies
5. **Transaction-like operations** with automatic rollback
6. **Rich error context** with structured logging
7. **Error injection framework** for comprehensive testing

The design leverages Rust's type system and ownership model to prevent common error handling mistakes while providing the sophisticated error management required for a robust union filesystem.