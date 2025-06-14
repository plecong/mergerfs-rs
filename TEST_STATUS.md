# Test Status

## Rust Tests

All Rust tests pass, including:
- ✅ Unit tests
- ✅ Integration tests  
- ✅ Space-based policy tests (using mock space calculations)

Run with: `cargo test`

## Python Tests

### Passing Tests ✅
- **Concurrent Access** (5 tests) - File/directory concurrent operations
- **Fuzz Foundation** (3 tests) - Basic fuzzing with invariant checking
- **Policy Behavior** (12 tests) - Create policies (ff, mfs, lfs, rand)
- **Property Based** (5 tests) - Hypothesis-based property testing
- **File Handles Property** (3 tests) - Handle management (with cleanup warnings)
- **MFS Policy** (8/10 tests) - Most free space policy behavior
- **Random Policy** (all tests) - Random policy implementation
- **Search Policies** (all tests) - Search policy tests
- **StatFS Property** (all tests) - StatFS behavior

### Failing Tests ❌
- **MFS Policy** (2 tests)
  - `test_mfs_updates_as_space_changes` - Relies on dynamic space simulation
  - `test_mfs_policy_consistency_multiple_runs` - Similar space simulation issue

These failures are due to tests that simulate space changes using small files,
which don't affect real filesystem space calculations significantly.

### Running Tests

```bash
# Setup tmpfs mounts (required for space-based tests)
sudo python_tests/scripts/setup_tmpfs.sh

# Run all Python tests
cd python_tests && uv run pytest -v

# Run specific test categories
uv run pytest tests/test_policy_behavior.py -v
uv run pytest tests/test_concurrent_access.py -v

# Cleanup tmpfs mounts
sudo python_tests/scripts/cleanup_tmpfs.sh
```

## Test Infrastructure

- **Rust**: Uses mock space calculations via `.space_marker` files
- **Python**: Uses real tmpfs mounts with predictable space (8MB, 40MB, 90MB)
- **Hybrid Approach**: Fast unit tests in Rust, comprehensive integration tests in Python

## Known Issues

1. File handle tests show cleanup warnings about disconnected transport endpoints
   - Tests still pass, warnings are due to Hypothesis rerunning examples
   
2. Some MFS tests fail because they expect small file creation to affect space
   - Would need significant refactoring to work with real filesystem space

Overall test coverage is excellent with 56/58 Python tests passing.