# mergerfs Architecture Overview

## Executive Summary

mergerfs is a FUSE-based union filesystem written in C++ that logically combines multiple filesystem paths into a single mount point. It acts as a proxy layer that routes filesystem operations to underlying storage branches based on configurable policies.

## Core Concepts

### Union Filesystem Model
- **Branches**: Individual filesystem paths that are combined (e.g., `/disk1`, `/disk2`, `/disk3`)
- **Mount Point**: Single virtual filesystem that presents unified view (e.g., `/merged`)
- **FUSE Layer**: Userspace filesystem that intercepts kernel VFS calls
- **Policy Engine**: Decision-making system that determines which branch(es) to use for operations

### Key Design Principles

1. **Non-destructive**: Operates on existing filesystems without modification
2. **Policy-driven**: Configurable algorithms for file placement and access
3. **Transparent**: Appears as regular filesystem to applications
4. **Fault-tolerant**: Individual branch failures don't affect other branches
5. **Runtime configurable**: Settings can be changed without remounting

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│              (read/write files normally)                    │
└─────────────────────────┬───────────────────────────────────┘
                          │ VFS calls
┌─────────────────────────▼───────────────────────────────────┐
│                    Kernel VFS                              │
└─────────────────────────┬───────────────────────────────────┘
                          │ FUSE protocol
┌─────────────────────────▼───────────────────────────────────┐
│                    mergerfs (FUSE)                         │
│  ┌─────────────────┐ ┌──────────────┐ ┌─────────────────┐   │
│  │  FUSE Handlers  │ │ Policy Engine│ │ Config Manager  │   │
│  └─────────────────┘ └──────────────┘ └─────────────────┘   │
│  ┌─────────────────┐ ┌──────────────┐ ┌─────────────────┐   │
│  │ Branch Manager  │ │  FS Abstraction│ │ Thread Manager  │   │
│  └─────────────────┘ └──────────────┘ └─────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │ System calls
┌─────────────────────────▼───────────────────────────────────┐
│              Underlying Filesystems                        │
│    /disk1       /disk2       /disk3       /disk4           │
│   (ext4)        (xfs)        (btrfs)      (zfs)            │
└─────────────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. FUSE Interface Layer (`fuse_*.cpp`)
- **Purpose**: Implements FUSE filesystem operations
- **Components**: 40+ operation handlers (open, read, write, mkdir, etc.)
- **Responsibility**: Translate FUSE calls to internal operations

### 2. Policy Engine (`policy_*.cpp`)
- **Purpose**: Determines which branch(es) to use for operations
- **Types**: Create, Search, Action policies
- **Algorithms**: 20+ different selection strategies

### 3. Branch Management (`branches.cpp`, `branch.cpp`)
- **Purpose**: Manages collection of underlying filesystem paths
- **Features**: Runtime modification, mode settings (RO/RW/NC)
- **Metadata**: Free space tracking, mount detection

### 4. Configuration System (`config*.cpp`)
- **Purpose**: Runtime configuration management
- **Pattern**: Singleton with reader-writer locks
- **Scope**: FUSE options, policies, caching, threading

### 5. Filesystem Abstraction (`fs_*.cpp`)
- **Purpose**: Cross-platform filesystem operations
- **Coverage**: 100+ filesystem functions
- **Features**: Conditional compilation for platform differences

### 6. Threading and Concurrency
- **FUSE Threads**: Configurable read/process thread pools
- **Synchronization**: Reader-writer locks, per-file mutexes
- **Memory**: Custom memory pools for performance

## Data Flow

### File Creation Flow
```
1. Application: open("/merged/file.txt", O_CREAT)
2. VFS: Route to FUSE
3. mergerfs: fuse_create() handler
4. Policy: Execute create policy (e.g., "mfs" - most free space)
5. Branch Selection: Choose /disk2 (has most free space)
6. Filesystem: Call open() on /disk2/file.txt
7. File Handle: Return file descriptor to application
```

### File Read Flow
```
1. Application: read(fd, buffer, size)
2. VFS: Route to FUSE
3. mergerfs: fuse_read() handler
4. File Info: Lookup which branch file exists on
5. Filesystem: Call read() on actual file
6. Data: Return data to application
```

### Directory Listing Flow
```
1. Application: readdir("/merged")
2. VFS: Route to FUSE
3. mergerfs: fuse_readdir() handler
4. Policy: Execute search policy (e.g., "all")
5. Branch Enumeration: Read all branches: /disk1, /disk2, /disk3
6. Merge: Combine and deduplicate entries
7. Result: Return unified directory listing
```

## Key Architectural Decisions

### 1. Policy-Based Operation Routing
**Decision**: Use pluggable policy system instead of fixed algorithms
**Rationale**: Different use cases need different file placement strategies
**Implementation**: Function pointer table with runtime selection

### 2. Copy-on-Write for Hard Links
**Decision**: Implement CoW when hard linking across branches
**Rationale**: Preserve POSIX semantics while enabling cross-branch links
**Implementation**: Detect cross-branch links and copy file content

### 3. Per-Operation Branch Selection
**Decision**: Policies can return different branches for each operation
**Rationale**: Enables complex behaviors like "create on fastest, read from nearest"
**Implementation**: Separate policy evaluation per FUSE call

### 4. Embedded FUSE Library
**Decision**: Include custom FUSE library instead of system libfuse
**Rationale**: Control over FUSE features, optimization, bug fixes
**Location**: `libfuse/` directory

### 5. Singleton Configuration
**Decision**: Global configuration object with reader-writer locks
**Rationale**: Runtime reconfiguration without remounting
**Implementation**: Thread-safe singleton pattern

## Performance Characteristics

### Strengths
- **Parallel I/O**: Multiple branches can be accessed simultaneously
- **Memory Pools**: Pre-allocated buffers reduce allocation overhead
- **Caching**: Configurable metadata and attribute caching
- **Zero-copy**: Direct I/O paths where possible

### Bottlenecks
- **Policy Evaluation**: Some policies require stat() on all branches
- **Directory Merging**: Reading large directories from multiple branches
- **Configuration Locks**: Reader-writer lock contention under high concurrency

### Scalability
- **Branches**: Tested with 100+ branches
- **Concurrency**: Configurable thread pools for FUSE operations
- **Memory**: Fixed memory pools prevent unbounded growth

## Extension Points

### Adding New Policies
1. Implement `Policy::CreateImpl`, `Policy::SearchImpl`, or `Policy::ActionImpl`
2. Add to policy registry in `policies.cpp`
3. Update option parser for new policy name

### Adding FUSE Operations
1. Create new `fuse_operationname.cpp` file
2. Implement operation handler function
3. Add to operation table in `mergerfs.cpp`

### Platform Support
1. Add conditional compilation in `fs_*.icpp` files
2. Implement platform-specific functionality
3. Update build system for new platform

## Dependencies

### Required
- **C++17**: Modern C++ features (filesystem, variant, optional)
- **FUSE**: Filesystem in Userspace (embedded version)
- **pthread**: POSIX threads for concurrency

### Optional
- **xattr**: Extended attribute support
- **copy_file_range**: Linux-specific efficient copying
- **clone file**: Platform-specific file cloning

## Build Configuration

### Compile-time Options
- `USE_XATTR`: Enable extended attribute support
- `UGID_USE_RWLOCK`: Use reader-writer locks for UID/GID cache
- `NDEBUG`: Release vs debug builds
- `STATIC`: Static linking

### Runtime Configuration
- All policies configurable via mount options
- Threading parameters adjustable
- Caching behavior configurable
- Branch list modifiable at runtime