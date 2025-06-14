# Space Calculation in mergerfs-rs

## Overview

mergerfs-rs follows the same space calculation methodology as the original C++ mergerfs implementation, using `f_bavail` instead of `f_bfree` when determining available space on filesystems.

## Key Differences: f_bavail vs f_bfree

- **f_bfree**: Total number of free blocks in the filesystem
- **f_bavail**: Number of free blocks available to unprivileged users

The difference between these two values represents the reserved blocks on filesystems like ext2/3/4, which are typically reserved for root user operations.

## Why f_bavail?

Using `f_bavail` provides more accurate space calculations for regular users because:

1. It respects filesystem reservations (typically 5% on ext filesystems)
2. It prevents policies from selecting branches that appear to have space but are actually reserved
3. It matches the behavior users expect when comparing with tools like `df`

## Implementation

The space calculation is implemented in `src/policy/utils.rs` using the `nix` crate's `statvfs` function:

```rust
let stat = statvfs(path)?;
let available = stat.blocks_available() as u64 * block_size;  // f_bavail
```

## Affected Policies

The following policies use space calculations and are affected by this implementation:

- **mfs (Most Free Space)**: Selects the branch with the most available space
- **lfs (Least Free Space)**: Selects the branch with the least available space  
- **pfrd (Percentage Free Random Distribution)**: Randomly selects branches weighted by available space

## Testing Considerations

When testing space-based policies, be aware that:

1. The available space reported by mergerfs may differ from `df` output
2. Reserved blocks will not be counted as available
3. Root users may see different behavior as they can use reserved space

## Comparison with df

The `df` command typically shows both available space (using f_bavail) and total free space (using f_bfree). mergerfs only considers the available space for unprivileged users, which matches the "Avail" column in `df` output.