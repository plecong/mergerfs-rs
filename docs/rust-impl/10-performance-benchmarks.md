# Performance Benchmarks and Optimization Guide

## Overview

This guide provides comprehensive performance benchmarking strategies, optimization techniques, and comparative analysis frameworks for the Rust implementation of mergerfs, ensuring it meets or exceeds the performance characteristics of the original C++ implementation.

## Benchmark Architecture

### Core Performance Metrics

```rust
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId, Throughput};
use std::time::{Duration, Instant};
use sysinfo::{System, SystemExt, ProcessExt};

#[derive(Debug, Clone)]
pub struct PerformanceMetrics {
    pub throughput_ops_per_sec: f64,
    pub latency_p50: Duration,
    pub latency_p95: Duration,
    pub latency_p99: Duration,
    pub memory_usage_mb: u64,
    pub cpu_usage_percent: f64,
    pub disk_io_bytes_per_sec: u64,
    pub error_rate_percent: f64,
}

pub struct BenchmarkSuite {
    system: System,
    start_time: Instant,
    operation_counts: std::collections::HashMap<String, u64>,
    latencies: std::collections::HashMap<String, Vec<Duration>>,
}

impl BenchmarkSuite {
    pub fn new() -> Self {
        let mut system = System::new_all();
        system.refresh_all();
        
        Self {
            system,
            start_time: Instant::now(),
            operation_counts: std::collections::HashMap::new(),
            latencies: std::collections::HashMap::new(),
        }
    }
    
    pub fn measure_operation<F, T>(&mut self, operation_name: &str, operation: F) -> T
    where
        F: FnOnce() -> T,
    {
        let start = Instant::now();
        let result = operation();
        let elapsed = start.elapsed();
        
        self.latencies.entry(operation_name.to_string())
            .or_insert_with(Vec::new)
            .push(elapsed);
        
        *self.operation_counts.entry(operation_name.to_string())
            .or_insert(0) += 1;
        
        result
    }
    
    pub fn get_metrics(&mut self, operation_name: &str) -> PerformanceMetrics {
        self.system.refresh_all();
        
        let latencies = self.latencies.get(operation_name).cloned().unwrap_or_default();
        let mut sorted_latencies = latencies.clone();
        sorted_latencies.sort();
        
        let latency_p50 = percentile(&sorted_latencies, 50);
        let latency_p95 = percentile(&sorted_latencies, 95);
        let latency_p99 = percentile(&sorted_latencies, 99);
        
        let total_time = self.start_time.elapsed();
        let operation_count = self.operation_counts.get(operation_name).copied().unwrap_or(0);
        let throughput_ops_per_sec = operation_count as f64 / total_time.as_secs_f64();
        
        let memory_usage_mb = self.system.used_memory() / 1024 / 1024;
        let cpu_usage_percent = self.system.global_cpu_info().cpu_usage() as f64;
        
        PerformanceMetrics {
            throughput_ops_per_sec,
            latency_p50,
            latency_p95,
            latency_p99,
            memory_usage_mb,
            cpu_usage_percent,
            disk_io_bytes_per_sec: 0, // Would need additional monitoring
            error_rate_percent: 0.0,   // Would track from error counts
        }
    }
}

fn percentile(sorted_data: &[Duration], percentile: u8) -> Duration {
    if sorted_data.is_empty() {
        return Duration::ZERO;
    }
    
    let index = (sorted_data.len() as f64 * (percentile as f64 / 100.0)) as usize;
    let index = index.min(sorted_data.len() - 1);
    sorted_data[index]
}
```

### File System Operation Benchmarks

```rust
use tempfile::TempDir;
use std::fs;
use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;

fn benchmark_file_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("file_operations");
    
    // File creation benchmarks
    for file_count in [100, 1000, 10000].iter() {
        group.bench_with_input(
            BenchmarkId::new("create_files", file_count),
            file_count,
            |b, &file_count| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        for i in 0..file_count {
                            let file_path = format!("/test_file_{}.txt", i);
                            let content = format!("Test content for file {}", i);
                            
                            black_box(create_file_through_mergerfs(
                                &fixture,
                                &file_path,
                                content.as_bytes(),
                            ).unwrap());
                        }
                    },
                );
            },
        );
    }
    
    // File read benchmarks with different sizes
    for file_size in [1024, 64 * 1024, 1024 * 1024, 10 * 1024 * 1024].iter() {
        group.throughput(Throughput::Bytes(*file_size as u64));
        group.bench_with_input(
            BenchmarkId::new("read_file", file_size),
            file_size,
            |b, &file_size| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        
                        // Create test file
                        let test_data = generate_test_data(file_size);
                        create_file_through_mergerfs(&fixture, "/test_file.bin", &test_data).unwrap();
                        
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        let data = black_box(read_file_through_mergerfs(
                            &fixture,
                            "/test_file.bin",
                        ).unwrap());
                        assert_eq!(data.len(), file_size);
                    },
                );
            },
        );
    }
    
    // File write benchmarks
    for file_size in [1024, 64 * 1024, 1024 * 1024, 10 * 1024 * 1024].iter() {
        group.throughput(Throughput::Bytes(*file_size as u64));
        group.bench_with_input(
            BenchmarkId::new("write_file", file_size),
            file_size,
            |b, &file_size| {
                let test_data = generate_test_data(file_size);
                
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        black_box(create_file_through_mergerfs(
                            &fixture,
                            "/test_file.bin",
                            &test_data,
                        ).unwrap());
                    },
                );
            },
        );
    }
    
    group.finish();
}

fn benchmark_directory_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("directory_operations");
    
    // Directory listing with varying file counts
    for file_count in [100, 1000, 10000].iter() {
        group.bench_with_input(
            BenchmarkId::new("list_directory", file_count),
            file_count,
            |b, &file_count| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        
                        // Create test files across branches
                        for i in 0..file_count {
                            let branch_idx = i % 3;
                            let file_name = format!("file_{:06}.txt", i);
                            create_file_in_branch(&fixture, branch_idx, &file_name, b"test content").unwrap();
                        }
                        
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        let entries = black_box(list_directory_through_mergerfs(
                            &fixture,
                            "/",
                        ).unwrap());
                        assert_eq!(entries.len(), file_count);
                    },
                );
            },
        );
    }
    
    // Directory tree traversal
    for depth in [3, 5, 8].iter() {
        group.bench_with_input(
            BenchmarkId::new("traverse_tree", depth),
            depth,
            |b, &depth| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        create_directory_tree(&fixture, depth, 10).unwrap();
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        let count = black_box(count_files_recursively(&fixture, "/").unwrap());
                        assert!(count > 0);
                    },
                );
            },
        );
    }
    
    group.finish();
}

fn benchmark_policy_performance(c: &mut Criterion) {
    let mut group = c.benchmark_group("policy_execution");
    
    // Test different policies with varying branch counts
    for branch_count in [3, 5, 10, 20, 50].iter() {
        for policy_name in ["ff", "mfs", "epff", "rand"].iter() {
            group.bench_with_input(
                BenchmarkId::new(format!("policy_{}", policy_name), branch_count),
                &(branch_count, policy_name),
                |b, &(branch_count, policy_name)| {
                    b.iter_with_setup(
                        || {
                            let temp_dir = TempDir::new().unwrap();
                            let fixture = create_test_environment(&temp_dir, *branch_count);
                            setup_policy(&fixture, policy_name);
                            (temp_dir, fixture)
                        },
                        |(temp_dir, fixture)| {
                            // Create 100 files to test policy selection
                            for i in 0..100 {
                                let file_path = format!("/policy_test_{}.txt", i);
                                black_box(create_file_through_mergerfs(
                                    &fixture,
                                    &file_path,
                                    b"test content",
                                ).unwrap());
                            }
                        },
                    );
                },
            );
        }
    }
    
    group.finish();
}

fn benchmark_concurrent_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("concurrent_operations");
    
    // Concurrent file creation
    for thread_count in [1, 2, 4, 8, 16].iter() {
        group.bench_with_input(
            BenchmarkId::new("concurrent_create", thread_count),
            thread_count,
            |b, &thread_count| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = Arc::new(create_test_environment(&temp_dir, 3));
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        let runtime = tokio::runtime::Runtime::new().unwrap();
                        
                        runtime.block_on(async {
                            let mut handles = Vec::new();
                            
                            for thread_id in 0..thread_count {
                                let fixture_clone = fixture.clone();
                                let handle = tokio::spawn(async move {
                                    for i in 0..100 {
                                        let file_path = format!("/thread_{}_file_{}.txt", thread_id, i);
                                        create_file_through_mergerfs(
                                            &fixture_clone,
                                            &file_path,
                                            b"concurrent test content",
                                        ).unwrap();
                                    }
                                });
                                handles.push(handle);
                            }
                            
                            for handle in handles {
                                handle.await.unwrap();
                            }
                        });
                    },
                );
            },
        );
    }
    
    // Concurrent read/write operations
    for operation_mix in [(100, 0), (80, 20), (50, 50), (20, 80), (0, 100)].iter() {
        let (read_percent, write_percent) = operation_mix;
        group.bench_with_input(
            BenchmarkId::new("concurrent_read_write", format!("{}r_{}w", read_percent, write_percent)),
            operation_mix,
            |b, &(read_percent, write_percent)| {
                b.iter_with_setup(
                    || {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = Arc::new(create_test_environment(&temp_dir, 3));
                        
                        // Pre-create some files for reading
                        for i in 0..100 {
                            let file_path = format!("/preexisting_{}.txt", i);
                            create_file_through_mergerfs(
                                &fixture,
                                &file_path,
                                b"preexisting content",
                            ).unwrap();
                        }
                        
                        (temp_dir, fixture)
                    },
                    |(temp_dir, fixture)| {
                        let runtime = tokio::runtime::Runtime::new().unwrap();
                        
                        runtime.block_on(async {
                            let mut handles = Vec::new();
                            
                            for i in 0..8 { // 8 concurrent threads
                                let fixture_clone = fixture.clone();
                                let handle = tokio::spawn(async move {
                                    let mut rng = ChaCha8Rng::seed_from_u64(i as u64);
                                    
                                    for j in 0..50 {
                                        let operation_choice = rng.gen_range(0..100);
                                        
                                        if operation_choice < read_percent {
                                            // Read operation
                                            let file_index = rng.gen_range(0..100);
                                            let file_path = format!("/preexisting_{}.txt", file_index);
                                            let _ = read_file_through_mergerfs(&fixture_clone, &file_path);
                                        } else {
                                            // Write operation
                                            let file_path = format!("/new_{}_{}.txt", i, j);
                                            let _ = create_file_through_mergerfs(
                                                &fixture_clone,
                                                &file_path,
                                                b"new content",
                                            );
                                        }
                                    }
                                });
                                handles.push(handle);
                            }
                            
                            for handle in handles {
                                handle.await.unwrap();
                            }
                        });
                    },
                );
            },
        );
    }
    
    group.finish();
}

fn generate_test_data(size: usize) -> Vec<u8> {
    let mut rng = ChaCha8Rng::seed_from_u64(42);
    let mut data = vec![0u8; size];
    rng.fill(&mut data[..]);
    data
}

criterion_group!(
    benches,
    benchmark_file_operations,
    benchmark_directory_operations,
    benchmark_policy_performance,
    benchmark_concurrent_operations
);
criterion_main!(benches);
```

## Memory Performance Analysis

### Memory Usage Profiling

```rust
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};

pub struct ProfilingAllocator {
    inner: System,
    allocated: AtomicUsize,
    deallocated: AtomicUsize,
    peak_usage: AtomicUsize,
    allocation_count: AtomicUsize,
    deallocation_count: AtomicUsize,
}

impl ProfilingAllocator {
    pub const fn new() -> Self {
        Self {
            inner: System,
            allocated: AtomicUsize::new(0),
            deallocated: AtomicUsize::new(0),
            peak_usage: AtomicUsize::new(0),
            allocation_count: AtomicUsize::new(0),
            deallocation_count: AtomicUsize::new(0),
        }
    }
    
    pub fn current_usage(&self) -> usize {
        self.allocated.load(Ordering::Relaxed) - self.deallocated.load(Ordering::Relaxed)
    }
    
    pub fn peak_usage(&self) -> usize {
        self.peak_usage.load(Ordering::Relaxed)
    }
    
    pub fn allocation_stats(&self) -> AllocationStats {
        AllocationStats {
            total_allocated: self.allocated.load(Ordering::Relaxed),
            total_deallocated: self.deallocated.load(Ordering::Relaxed),
            current_usage: self.current_usage(),
            peak_usage: self.peak_usage(),
            allocation_count: self.allocation_count.load(Ordering::Relaxed),
            deallocation_count: self.deallocation_count.load(Ordering::Relaxed),
        }
    }
    
    pub fn reset_stats(&self) {
        self.allocated.store(0, Ordering::Relaxed);
        self.deallocated.store(0, Ordering::Relaxed);
        self.peak_usage.store(0, Ordering::Relaxed);
        self.allocation_count.store(0, Ordering::Relaxed);
        self.deallocation_count.store(0, Ordering::Relaxed);
    }
}

unsafe impl GlobalAlloc for ProfilingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = self.inner.alloc(layout);
        if !ptr.is_null() {
            self.allocated.fetch_add(layout.size(), Ordering::Relaxed);
            self.allocation_count.fetch_add(1, Ordering::Relaxed);
            
            // Update peak usage
            let current = self.current_usage();
            let mut peak = self.peak_usage.load(Ordering::Relaxed);
            while current > peak {
                match self.peak_usage.compare_exchange_weak(
                    peak,
                    current,
                    Ordering::Relaxed,
                    Ordering::Relaxed,
                ) {
                    Ok(_) => break,
                    Err(new_peak) => peak = new_peak,
                }
            }
        }
        ptr
    }
    
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        self.inner.dealloc(ptr, layout);
        self.deallocated.fetch_add(layout.size(), Ordering::Relaxed);
        self.deallocation_count.fetch_add(1, Ordering::Relaxed);
    }
}

#[derive(Debug, Clone)]
pub struct AllocationStats {
    pub total_allocated: usize,
    pub total_deallocated: usize,
    pub current_usage: usize,
    pub peak_usage: usize,
    pub allocation_count: usize,
    pub deallocation_count: usize,
}

// Global allocator for profiling
#[global_allocator]
static GLOBAL: ProfilingAllocator = ProfilingAllocator::new();

pub fn get_memory_stats() -> AllocationStats {
    GLOBAL.allocation_stats()
}

fn benchmark_memory_usage(c: &mut Criterion) {
    let mut group = c.benchmark_group("memory_usage");
    
    group.bench_function("file_operations_memory", |b| {
        b.iter_custom(|iters| {
            GLOBAL.reset_stats();
            let start = Instant::now();
            
            for i in 0..iters {
                let temp_dir = TempDir::new().unwrap();
                let fixture = create_test_environment(&temp_dir, 3);
                
                // Perform various operations
                for j in 0..10 {
                    let file_path = format!("/memory_test_{}_{}.txt", i, j);
                    create_file_through_mergerfs(&fixture, &file_path, b"test content").unwrap();
                    let _ = read_file_through_mergerfs(&fixture, &file_path).unwrap();
                }
                
                black_box(fixture);
            }
            
            let stats = get_memory_stats();
            println!("Memory stats: {:?}", stats);
            
            start.elapsed()
        });
    });
    
    group.finish();
}
```

## CPU Performance Analysis

### CPU Profiling and Hot Path Analysis

```rust
use perf_event::Builder;
use std::collections::HashMap;

pub struct CpuProfiler {
    counters: HashMap<String, perf_event::Counter>,
    enabled: bool,
}

impl CpuProfiler {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let mut counters = HashMap::new();
        
        // CPU cycles
        let cycles_counter = Builder::new()
            .group(-1)
            .kind(perf_event::events::Hardware::CpuCycles)
            .build()?;
        counters.insert("cpu_cycles".to_string(), cycles_counter);
        
        // Instructions
        let instructions_counter = Builder::new()
            .group(-1)
            .kind(perf_event::events::Hardware::Instructions)
            .build()?;
        counters.insert("instructions".to_string(), instructions_counter);
        
        // Cache misses
        let cache_misses_counter = Builder::new()
            .group(-1)
            .kind(perf_event::events::Hardware::CacheMisses)
            .build()?;
        counters.insert("cache_misses".to_string(), cache_misses_counter);
        
        // Branch misses
        let branch_misses_counter = Builder::new()
            .group(-1)
            .kind(perf_event::events::Hardware::BranchMisses)
            .build()?;
        counters.insert("branch_misses".to_string(), branch_misses_counter);
        
        Ok(Self {
            counters,
            enabled: true,
        })
    }
    
    pub fn start_profiling(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        if !self.enabled {
            return Ok(());
        }
        
        for counter in self.counters.values_mut() {
            counter.enable()?;
            counter.reset()?;
        }
        
        Ok(())
    }
    
    pub fn stop_profiling(&mut self) -> Result<CpuStats, Box<dyn std::error::Error>> {
        if !self.enabled {
            return Ok(CpuStats::default());
        }
        
        let mut stats = CpuStats::default();
        
        for (name, counter) in &mut self.counters {
            counter.disable()?;
            let count = counter.read()?;
            
            match name.as_str() {
                "cpu_cycles" => stats.cpu_cycles = count,
                "instructions" => stats.instructions = count,
                "cache_misses" => stats.cache_misses = count,
                "branch_misses" => stats.branch_misses = count,
                _ => {}
            }
        }
        
        Ok(stats)
    }
}

#[derive(Debug, Clone, Default)]
pub struct CpuStats {
    pub cpu_cycles: u64,
    pub instructions: u64,
    pub cache_misses: u64,
    pub branch_misses: u64,
}

impl CpuStats {
    pub fn instructions_per_cycle(&self) -> f64 {
        if self.cpu_cycles == 0 {
            0.0
        } else {
            self.instructions as f64 / self.cpu_cycles as f64
        }
    }
    
    pub fn cache_miss_rate(&self) -> f64 {
        if self.instructions == 0 {
            0.0
        } else {
            self.cache_misses as f64 / self.instructions as f64
        }
    }
    
    pub fn branch_miss_rate(&self) -> f64 {
        if self.instructions == 0 {
            0.0
        } else {
            self.branch_misses as f64 / self.instructions as f64
        }
    }
}

fn benchmark_cpu_performance(c: &mut Criterion) {
    let mut group = c.benchmark_group("cpu_performance");
    
    group.bench_function("policy_execution_cpu", |b| {
        b.iter_custom(|iters| {
            let mut profiler = CpuProfiler::new().unwrap();
            profiler.start_profiling().unwrap();
            
            let start = Instant::now();
            
            for _ in 0..iters {
                let temp_dir = TempDir::new().unwrap();
                let fixture = create_test_environment(&temp_dir, 10);
                
                // Test policy execution hot path
                for i in 0..100 {
                    let file_path = format!("/cpu_test_{}.txt", i);
                    create_file_through_mergerfs(&fixture, &file_path, b"test").unwrap();
                }
                
                black_box(fixture);
            }
            
            let cpu_stats = profiler.stop_profiling().unwrap();
            println!("CPU stats: IPC={:.2}, cache_miss_rate={:.4}%, branch_miss_rate={:.4}%",
                     cpu_stats.instructions_per_cycle(),
                     cpu_stats.cache_miss_rate() * 100.0,
                     cpu_stats.branch_miss_rate() * 100.0);
            
            start.elapsed()
        });
    });
    
    group.finish();
}
```

## I/O Performance Analysis

### Disk I/O Monitoring

```rust
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::collections::HashMap;

#[derive(Debug, Clone, Default)]
pub struct IoStats {
    pub read_bytes: u64,
    pub write_bytes: u64,
    pub read_operations: u64,
    pub write_operations: u64,
    pub read_latency_ms: f64,
    pub write_latency_ms: f64,
}

pub struct IoMonitor {
    initial_stats: HashMap<String, IoStats>,
    proc_diskstats_path: String,
}

impl IoMonitor {
    pub fn new() -> Result<Self, std::io::Error> {
        let mut monitor = Self {
            initial_stats: HashMap::new(),
            proc_diskstats_path: "/proc/diskstats".to_string(),
        };
        
        monitor.initial_stats = monitor.read_diskstats()?;
        Ok(monitor)
    }
    
    pub fn get_io_delta(&self) -> Result<HashMap<String, IoStats>, std::io::Error> {
        let current_stats = self.read_diskstats()?;
        let mut deltas = HashMap::new();
        
        for (device, current) in &current_stats {
            if let Some(initial) = self.initial_stats.get(device) {
                let delta = IoStats {
                    read_bytes: current.read_bytes.saturating_sub(initial.read_bytes),
                    write_bytes: current.write_bytes.saturating_sub(initial.write_bytes),
                    read_operations: current.read_operations.saturating_sub(initial.read_operations),
                    write_operations: current.write_operations.saturating_sub(initial.write_operations),
                    read_latency_ms: current.read_latency_ms,
                    write_latency_ms: current.write_latency_ms,
                };
                deltas.insert(device.clone(), delta);
            }
        }
        
        Ok(deltas)
    }
    
    fn read_diskstats(&self) -> Result<HashMap<String, IoStats>, std::io::Error> {
        let file = File::open(&self.proc_diskstats_path)?;
        let reader = BufReader::new(file);
        let mut stats = HashMap::new();
        
        for line in reader.lines() {
            let line = line?;
            let parts: Vec<&str> = line.split_whitespace().collect();
            
            if parts.len() >= 14 {
                let device = parts[2].to_string();
                
                // Parse relevant fields from /proc/diskstats
                let read_operations = parts[3].parse::<u64>().unwrap_or(0);
                let read_sectors = parts[5].parse::<u64>().unwrap_or(0);
                let write_operations = parts[7].parse::<u64>().unwrap_or(0);
                let write_sectors = parts[9].parse::<u64>().unwrap_or(0);
                
                // Convert sectors to bytes (assuming 512-byte sectors)
                let read_bytes = read_sectors * 512;
                let write_bytes = write_sectors * 512;
                
                stats.insert(device, IoStats {
                    read_bytes,
                    write_bytes,
                    read_operations,
                    write_operations,
                    read_latency_ms: 0.0,  // Would need additional monitoring
                    write_latency_ms: 0.0, // Would need additional monitoring
                });
            }
        }
        
        Ok(stats)
    }
}

fn benchmark_io_performance(c: &mut Criterion) {
    let mut group = c.benchmark_group("io_performance");
    
    for file_size in [1024, 64 * 1024, 1024 * 1024].iter() {
        group.throughput(Throughput::Bytes(*file_size as u64));
        
        group.bench_with_input(
            BenchmarkId::new("sequential_read", file_size),
            file_size,
            |b, &file_size| {
                b.iter_custom(|iters| {
                    let io_monitor = IoMonitor::new().unwrap();
                    let start = Instant::now();
                    
                    for i in 0..iters {
                        let temp_dir = TempDir::new().unwrap();
                        let fixture = create_test_environment(&temp_dir, 3);
                        
                        // Create test file
                        let test_data = generate_test_data(file_size);
                        let file_path = format!("/io_test_{}.bin", i);
                        create_file_through_mergerfs(&fixture, &file_path, &test_data).unwrap();
                        
                        // Read file
                        let read_data = read_file_through_mergerfs(&fixture, &file_path).unwrap();
                        black_box(read_data);
                    }
                    
                    let io_stats = io_monitor.get_io_delta().unwrap();
                    let total_read_bytes: u64 = io_stats.values().map(|s| s.read_bytes).sum();
                    let total_write_bytes: u64 = io_stats.values().map(|s| s.write_bytes).sum();
                    
                    println!("I/O stats: read={} MB, write={} MB", 
                             total_read_bytes / 1024 / 1024,
                             total_write_bytes / 1024 / 1024);
                    
                    start.elapsed()
                });
            },
        );
    }
    
    group.finish();
}
```

## Comparative Analysis Framework

### Rust vs C++ Performance Comparison

```rust
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct ComparisonResult {
    pub rust_metrics: PerformanceMetrics,
    pub cpp_metrics: PerformanceMetrics,
    pub rust_faster_by: f64, // Factor by which Rust is faster (or negative if slower)
    pub memory_efficiency: f64, // Rust memory usage / C++ memory usage
}

pub struct PerformanceComparator {
    cpp_mergerfs_path: String,
    test_scenarios: Vec<TestScenario>,
}

#[derive(Debug, Clone)]
pub struct TestScenario {
    pub name: String,
    pub description: String,
    pub operation_count: u32,
    pub file_size: usize,
    pub concurrent_threads: u32,
    pub duration_seconds: u32,
}

impl PerformanceComparator {
    pub fn new(cpp_mergerfs_path: String) -> Self {
        let test_scenarios = vec![
            TestScenario {
                name: "small_files_create".to_string(),
                description: "Create 10000 small files (1KB each)".to_string(),
                operation_count: 10000,
                file_size: 1024,
                concurrent_threads: 1,
                duration_seconds: 60,
            },
            TestScenario {
                name: "large_files_io".to_string(),
                description: "Read/write 100 large files (10MB each)".to_string(),
                operation_count: 100,
                file_size: 10 * 1024 * 1024,
                concurrent_threads: 1,
                duration_seconds: 60,
            },
            TestScenario {
                name: "concurrent_mixed".to_string(),
                description: "Concurrent mixed operations with 8 threads".to_string(),
                operation_count: 5000,
                file_size: 64 * 1024,
                concurrent_threads: 8,
                duration_seconds: 120,
            },
            TestScenario {
                name: "directory_listing".to_string(),
                description: "List directories with 50000 files".to_string(),
                operation_count: 50000,
                file_size: 0,
                concurrent_threads: 1,
                duration_seconds: 30,
            },
        ];
        
        Self {
            cpp_mergerfs_path,
            test_scenarios,
        }
    }
    
    pub async fn run_comparison(&self) -> Result<Vec<ComparisonResult>, Box<dyn std::error::Error>> {
        let mut results = Vec::new();
        
        for scenario in &self.test_scenarios {
            println!("Running comparison for scenario: {}", scenario.name);
            
            let rust_metrics = self.benchmark_rust_implementation(scenario).await?;
            let cpp_metrics = self.benchmark_cpp_implementation(scenario).await?;
            
            let rust_faster_by = cpp_metrics.throughput_ops_per_sec / rust_metrics.throughput_ops_per_sec;
            let memory_efficiency = rust_metrics.memory_usage_mb as f64 / cpp_metrics.memory_usage_mb as f64;
            
            let comparison = ComparisonResult {
                rust_metrics,
                cpp_metrics,
                rust_faster_by,
                memory_efficiency,
            };
            
            results.push(comparison);
        }
        
        Ok(results)
    }
    
    async fn benchmark_rust_implementation(&self, scenario: &TestScenario) -> Result<PerformanceMetrics, Box<dyn std::error::Error>> {
        let mut benchmark_suite = BenchmarkSuite::new();
        let temp_dir = TempDir::new()?;
        let fixture = create_test_environment(&temp_dir, 3);
        
        let start_time = Instant::now();
        
        if scenario.concurrent_threads == 1 {
            // Single-threaded benchmark
            for i in 0..scenario.operation_count {
                benchmark_suite.measure_operation(&scenario.name, || {
                    self.run_scenario_operation(&fixture, scenario, i)
                })?;
            }
        } else {
            // Multi-threaded benchmark
            let runtime = tokio::runtime::Runtime::new()?;
            runtime.block_on(async {
                let mut handles = Vec::new();
                let operations_per_thread = scenario.operation_count / scenario.concurrent_threads;
                
                for thread_id in 0..scenario.concurrent_threads {
                    let fixture_clone = fixture.clone();
                    let scenario_clone = scenario.clone();
                    
                    let handle = tokio::spawn(async move {
                        for i in 0..operations_per_thread {
                            let operation_id = thread_id * operations_per_thread + i;
                            self.run_scenario_operation(&fixture_clone, &scenario_clone, operation_id)?;
                        }
                        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
                    });
                    handles.push(handle);
                }
                
                for handle in handles {
                    handle.await??;
                }
                
                Ok::<(), Box<dyn std::error::Error>>(())
            })?;
        }
        
        Ok(benchmark_suite.get_metrics(&scenario.name))
    }
    
    async fn benchmark_cpp_implementation(&self, scenario: &TestScenario) -> Result<PerformanceMetrics, Box<dyn std::error::Error>> {
        // Create temporary directories for C++ mergerfs
        let temp_dir = TempDir::new()?;
        let branch1 = temp_dir.path().join("branch1");
        let branch2 = temp_dir.path().join("branch2");
        let branch3 = temp_dir.path().join("branch3");
        let mount_point = temp_dir.path().join("mount");
        
        std::fs::create_dir_all(&branch1)?;
        std::fs::create_dir_all(&branch2)?;
        std::fs::create_dir_all(&branch3)?;
        std::fs::create_dir_all(&mount_point)?;
        
        // Mount C++ mergerfs
        let branches = format!("{}:{}:{}", branch1.display(), branch2.display(), branch3.display());
        let mut mergerfs_process = Command::new(&self.cpp_mergerfs_path)
            .arg(&branches)
            .arg(&mount_point)
            .arg("-o")
            .arg("allow_other,use_ino,cache.files=off")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        
        // Wait for mount to complete
        tokio::time::sleep(Duration::from_secs(2)).await;
        
        let start_time = Instant::now();
        let mut operations_completed = 0;
        
        // Run the same operations as Rust benchmark
        for i in 0..scenario.operation_count {
            match self.run_cpp_scenario_operation(&mount_point, scenario, i) {
                Ok(_) => operations_completed += 1,
                Err(e) => eprintln!("C++ operation failed: {}", e),
            }
        }
        
        let total_time = start_time.elapsed();
        
        // Unmount
        let _ = Command::new("fusermount")
            .arg("-u")
            .arg(&mount_point)
            .output();
        
        // Terminate mergerfs process
        let _ = mergerfs_process.kill();
        let _ = mergerfs_process.wait();
        
        // Calculate metrics
        let throughput_ops_per_sec = operations_completed as f64 / total_time.as_secs_f64();
        
        Ok(PerformanceMetrics {
            throughput_ops_per_sec,
            latency_p50: total_time / operations_completed.max(1),
            latency_p95: total_time / operations_completed.max(1), // Simplified
            latency_p99: total_time / operations_completed.max(1), // Simplified
            memory_usage_mb: 50, // Would need actual measurement
            cpu_usage_percent: 0.0, // Would need actual measurement
            disk_io_bytes_per_sec: 0,
            error_rate_percent: 0.0,
        })
    }
    
    fn run_scenario_operation(&self, fixture: &TestFixture, scenario: &TestScenario, operation_id: u32) -> Result<(), Box<dyn std::error::Error>> {
        match scenario.name.as_str() {
            "small_files_create" => {
                let file_path = format!("/small_file_{}.txt", operation_id);
                let content = vec![b'A'; scenario.file_size];
                create_file_through_mergerfs(fixture, &file_path, &content)?;
            }
            "large_files_io" => {
                let file_path = format!("/large_file_{}.bin", operation_id);
                let content = generate_test_data(scenario.file_size);
                create_file_through_mergerfs(fixture, &file_path, &content)?;
                let _data = read_file_through_mergerfs(fixture, &file_path)?;
            }
            "concurrent_mixed" => {
                if operation_id % 2 == 0 {
                    // Write operation
                    let file_path = format!("/mixed_file_{}.txt", operation_id);
                    let content = vec![b'B'; scenario.file_size];
                    create_file_through_mergerfs(fixture, &file_path, &content)?;
                } else {
                    // Read operation (if file exists)
                    let file_path = format!("/mixed_file_{}.txt", operation_id - 1);
                    if let Ok(_data) = read_file_through_mergerfs(fixture, &file_path) {
                        // Successfully read
                    }
                }
            }
            "directory_listing" => {
                // Create files first if needed
                if operation_id < 100 {
                    let file_path = format!("/dir_test_{}.txt", operation_id);
                    create_file_through_mergerfs(fixture, &file_path, b"test")?;
                } else {
                    // List directory
                    let _entries = list_directory_through_mergerfs(fixture, "/")?;
                }
            }
            _ => {
                return Err(format!("Unknown scenario: {}", scenario.name).into());
            }
        }
        
        Ok(())
    }
    
    fn run_cpp_scenario_operation(&self, mount_point: &std::path::Path, scenario: &TestScenario, operation_id: u32) -> Result<(), Box<dyn std::error::Error>> {
        match scenario.name.as_str() {
            "small_files_create" => {
                let file_path = mount_point.join(format!("small_file_{}.txt", operation_id));
                let content = vec![b'A'; scenario.file_size];
                std::fs::write(&file_path, &content)?;
            }
            "large_files_io" => {
                let file_path = mount_point.join(format!("large_file_{}.bin", operation_id));
                let content = generate_test_data(scenario.file_size);
                std::fs::write(&file_path, &content)?;
                let _data = std::fs::read(&file_path)?;
            }
            "concurrent_mixed" => {
                if operation_id % 2 == 0 {
                    let file_path = mount_point.join(format!("mixed_file_{}.txt", operation_id));
                    let content = vec![b'B'; scenario.file_size];
                    std::fs::write(&file_path, &content)?;
                } else {
                    let file_path = mount_point.join(format!("mixed_file_{}.txt", operation_id - 1));
                    if let Ok(_data) = std::fs::read(&file_path) {
                        // Successfully read
                    }
                }
            }
            "directory_listing" => {
                if operation_id < 100 {
                    let file_path = mount_point.join(format!("dir_test_{}.txt", operation_id));
                    std::fs::write(&file_path, b"test")?;
                } else {
                    let _entries = std::fs::read_dir(mount_point)?;
                }
            }
            _ => {
                return Err(format!("Unknown scenario: {}", scenario.name).into());
            }
        }
        
        Ok(())
    }
    
    pub fn generate_comparison_report(&self, results: &[ComparisonResult]) -> String {
        let mut report = String::new();
        
        report.push_str("# MergerFS Rust vs C++ Performance Comparison\n\n");
        
        for (i, result) in results.iter().enumerate() {
            let scenario = &self.test_scenarios[i];
            
            report.push_str(&format!("## {}\n\n", scenario.name));
            report.push_str(&format!("**Description:** {}\n\n", scenario.description));
            
            report.push_str("### Performance Metrics\n\n");
            report.push_str("| Metric | Rust | C++ | Improvement |\n");
            report.push_str("|--------|------|-----|-------------|\n");
            
            report.push_str(&format!(
                "| Throughput (ops/sec) | {:.2} | {:.2} | {:.2}x |\n",
                result.rust_metrics.throughput_ops_per_sec,
                result.cpp_metrics.throughput_ops_per_sec,
                result.rust_faster_by
            ));
            
            report.push_str(&format!(
                "| Memory Usage (MB) | {} | {} | {:.2}x efficiency |\n",
                result.rust_metrics.memory_usage_mb,
                result.cpp_metrics.memory_usage_mb,
                1.0 / result.memory_efficiency
            ));
            
            report.push_str(&format!(
                "| P95 Latency (ms) | {:.2} | {:.2} | {:.2}x faster |\n",
                result.rust_metrics.latency_p95.as_millis(),
                result.cpp_metrics.latency_p95.as_millis(),
                result.cpp_metrics.latency_p95.as_secs_f64() / result.rust_metrics.latency_p95.as_secs_f64()
            ));
            
            report.push_str("\n");
        }
        
        // Summary
        let avg_speedup: f64 = results.iter().map(|r| r.rust_faster_by).sum::<f64>() / results.len() as f64;
        let avg_memory_efficiency: f64 = results.iter().map(|r| 1.0 / r.memory_efficiency).sum::<f64>() / results.len() as f64;
        
        report.push_str("## Summary\n\n");
        report.push_str(&format!("- **Average Performance Improvement:** {:.2}x faster\n", avg_speedup));
        report.push_str(&format!("- **Average Memory Efficiency:** {:.2}x more efficient\n", avg_memory_efficiency));
        
        if avg_speedup > 1.0 {
            report.push_str("\n✅ **Rust implementation outperforms C++ implementation**\n");
        } else {
            report.push_str("\n⚠️ **C++ implementation currently faster - optimization needed**\n");
        }
        
        report
    }
}
```

This comprehensive performance benchmarking documentation provides detailed frameworks for measuring, analyzing, and comparing the Rust implementation against the C++ original, ensuring performance goals are met or exceeded.