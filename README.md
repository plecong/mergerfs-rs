# mergerfs-rs

**⚠️ EXPERIMENTAL SOFTWARE - DO NOT USE IN PRODUCTION ⚠️**

This is an experimental Rust implementation of [mergerfs](https://github.com/trapexit/mergerfs), a union filesystem that combines multiple directories into a single mount point.

## 🚧 Project Status

This project is **highly experimental** and **incomplete**. It should **NOT** be used for any production workloads or important data. The implementation is approximately 43% complete compared to the original C++ mergerfs.

## 🤖 About This Repository

This repository is an experiment in AI-assisted software development using [Claude Code](https://claude.ai/code). The entire codebase has been developed through collaboration with Claude, Anthropic's AI assistant, to explore:

- How effectively AI can understand and implement complex system software
- The feasibility of porting a mature C++ project to Rust with AI assistance
- Best practices for AI-driven development of low-level filesystem code

## What is mergerfs?

mergerfs is a union filesystem that allows you to combine multiple directories (branches) into a single mount point. It's commonly used for:
- Combining multiple drives into a single logical volume
- Creating storage pools without RAID
- Implementing tiered storage solutions

## Current Implementation Status

### ✅ Implemented Features
- Basic FUSE filesystem operations (read, write, create, delete)
- Directory operations and metadata management
- Multiple file distribution policies (ff, mfs, lfs, rand, epff, epmfs, eplfs, pfrd)
- Extended attributes (xattr) support
- Symbolic and hard link support
- Runtime configuration via xattr
- Path preservation for existing path policies
- moveonenospc (automatic file migration on out-of-space errors)

### ❌ Not Implemented
- Many advanced policies
- File locking
- Advanced I/O operations (fallocate, copy_file_range)
- Performance optimizations and caching
- Many other features (see IMPLEMENTATION_STATUS.md for details)

## Development Approach

This project follows these principles:
1. **No unsafe Rust code** - All implementations use safe Rust
2. **Alpine Linux/MUSL compatible** - Avoids glibc dependencies
3. **Policy-driven design** - Flexible branch selection algorithms
4. **Comprehensive testing** - Unit tests and Python-based integration tests
5. **AI-documented** - Code and design decisions documented by Claude

## Building and Testing

**⚠️ Remember: This is experimental software and should not be used with important data!**

```bash
# Build the project
cargo build --release

# Run tests
cargo test

# Run Python integration tests
cd python_tests
uv sync
uv run pytest
```

## Usage Example (Experimental Only!)

```bash
# DO NOT USE WITH IMPORTANT DATA
./target/release/mergerfs-rs -o func.create=mfs /mnt/union /mnt/disk1 /mnt/disk2
```

## Contributing

As this is an experiment in AI-assisted development, contributions should align with the experimental nature of the project. See CLAUDE.md for guidelines on working with Claude Code.

## License

This project follows the same license as the original mergerfs project.

## Acknowledgments

- [mergerfs](https://github.com/trapexit/mergerfs) by trapexit - The original C++ implementation
- [Claude Code](https://claude.ai/code) by Anthropic - AI assistant used for development
- The Rust and FUSE communities for excellent libraries and documentation

---

**Final Warning**: This is experimental software created as an AI development experiment. It is incomplete, likely contains bugs, and should never be used for any important data or production systems. Use at your own risk!