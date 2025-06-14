# Testing Space-Based Policies

## Overview

Testing space-based policies (MFS, LFS) can be challenging because the behavior depends on actual filesystem space calculations using `statvfs` and `f_bavail`.

## Challenges

### 1. Real Filesystem Space

When running on real filesystems with many GB of available space:
- Creating small test files (KB or MB) may not significantly affect the available space calculation
- Different filesystems may have different block sizes and reservations
- The same test may pass on one system but fail on another

### 2. f_bavail vs f_bfree

The implementation uses `f_bavail` (blocks available to unprivileged users) which:
- Respects filesystem reservations (typically 5% on ext filesystems)
- May show different values than expected when running as root
- Can vary significantly between filesystem types

## Test Design Recommendations

### For Unit Tests

1. **Mock the DiskSpace calculation** - Instead of relying on real filesystem space, mock the `DiskSpace::for_path` function to return predictable values

2. **Use relative comparisons** - Instead of expecting specific branches, verify that the policy selects the branch with relatively more/less space

3. **Test edge cases** - Focus on testing behavior when:
   - All branches have equal space
   - Some branches are read-only
   - Space calculation fails

### For Integration Tests

1. **Create significant space differences** - Use larger files (hundreds of MB) to ensure detectable differences

2. **Use dedicated test filesystems** - Mount tmpfs with specific size limits for predictable behavior

3. **Make tests adaptive** - Query actual space before and after operations rather than assuming fixed values

## Example Test Pattern

```rust
// Instead of:
assert!(branch1_selected, "Should select branch 1 with most space");

// Use:
let space1 = DiskSpace::for_path(&branch1)?;
let space2 = DiskSpace::for_path(&branch2)?;
if space1.available > space2.available {
    assert!(branch1_selected, "Should select branch with more space");
} else {
    assert!(branch2_selected, "Should select branch with more space");
}
```

## Python Test Considerations

The Python tests use `FileSystemState.create_file_with_size()` to create files of specific sizes. When running on systems with large filesystems:

1. The created files may be too small to affect space calculations
2. Tests may need to be run in containers or VMs with limited disk space
3. Consider using loop devices or tmpfs with size limits for consistent testing

## CI/CD Recommendations

1. Use Docker containers with limited disk space for consistent test environments
2. Run tests on multiple filesystem types (ext4, xfs, btrfs)
3. Include tests with both privileged and unprivileged users
4. Monitor for flaky tests related to space calculations