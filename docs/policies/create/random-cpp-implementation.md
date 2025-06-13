# Random Create Policy - Original C++ Implementation Details

This document provides a detailed analysis of how the random create policy is implemented in the original mergerfs C++ codebase.

## Overview

The random policy in mergerfs C++ uses a two-stage approach:
1. Find all eligible branches using the `all` policy
2. Randomly select one branch from the eligible set

## Detailed Implementation

### 1. Main Random Policy Function (`policy_rand.cpp`)

```cpp
int Policy::Func::rand(const Category type_,
                      const Branches &branches_,
                      const char *fusepath_,
                      StrVec *paths_)
{
  int rv;

  rv = Policies::Create::all(branches_, fusepath_, paths_);
  if(rv == 0)
    RND::shrink_to_rand_elem(paths_);

  return rv;
}
```

The implementation:
- Calls the `all` policy to populate `paths_` with ALL eligible branches
- If successful (`rv == 0`), randomly selects one branch
- Returns the same error code if no branches were found

### 2. Random Selection Logic (`rnd.hpp`)

```cpp
template<typename T>
void shrink_to_rand_elem(std::vector<T> &v_)
{
  if(v_.size() <= 1)
    return;

  static std::random_device rd;
  static std::mt19937 g(rd());
  
  std::uniform_int_distribution<size_t> dist(0, v_.size() - 1);
  size_t idx = dist(g);
  
  std::swap(v_[0], v_[idx]);
  v_.resize(1);
}
```

Key features:
- Uses Mersenne Twister (`std::mt19937`) for high-quality randomness
- Thread-local static random generator for efficiency
- Swaps randomly selected element to position 0
- Resizes vector to contain only the selected element
- No-op for empty or single-element vectors

### 3. Branch Eligibility (`policy_all.cpp`)

The `all` policy checks each branch for eligibility:

```cpp
for(size_t i = 0, ei = branches_.size(); i < ei; i++)
{
  branch = branches_[i];
  
  // Skip read-only or no-create branches
  if(branch.ro_or_nc())
    error_and_continue(err, EROFS);
    
  // Get filesystem info
  rv = fs::info(branch.path, &info);
  if(rv == -1)
    error_and_continue(err, ENOENT);
    
  // Check if filesystem is read-only
  if(info.readonly)
    error_and_continue(err, EROFS);
    
  // Check minimum free space
  if(info.spaceavail < minfreespace_)
    error_and_continue(err, ENOSPC);
    
  // Branch is eligible
  obranches_.push_back(i);
}
```

### 4. Error Handling System

#### Error Priority (`policy_error.hpp`)

```cpp
#define error_and_continue(err, newerr) \
  { err = calc_error(err, newerr); continue; }

static int calc_error(const int preverr, const int newerr)
{
  if(preverr == ENOENT)    // Lowest priority
    return newerr;
  if(preverr == ENOSPC)    // Medium priority
    return (newerr == EROFS) ? newerr : preverr;
  return preverr;          // EROFS highest priority
}
```

Error precedence (lowest to highest):
1. **ENOENT** - No such file or directory
2. **ENOSPC** - No space left on device
3. **EROFS** - Read-only file system

### 5. Branch Modes

Branches can be in three modes:
- **RW (Read-Write)**: Full access, can be used for creates
- **RO (Read-Only)**: No writes allowed, skipped for creates
- **NC (No-Create)**: No new file creation, but existing files can be modified

The `branch.ro_or_nc()` check filters out both RO and NC branches.

## Key Differences from Simple Random Implementation

1. **Two-stage process**: Instead of filtering and selecting in one pass, it:
   - First collects ALL valid branches
   - Then picks one randomly
   
2. **Uniform distribution**: By collecting all valid branches first, each has equal probability of selection

3. **Error accumulation**: Tracks the highest-priority error encountered across all branches

4. **Consistent eligibility**: Reuses the `all` policy logic, ensuring consistent branch validation

## Design Implications for Rust Implementation

Our Rust implementation should:

1. **Match the two-stage approach** for consistency with original behavior
2. **Use the same error priority system** when all branches fail
3. **Check all the same conditions**:
   - Branch mode (RO/NC/RW)
   - Filesystem accessibility
   - Read-only filesystem status
   - Minimum free space
4. **Ensure uniform random distribution** across eligible branches

## Example Scenarios

### Scenario 1: Multiple Eligible Branches
```
Branches: [RW, RW, RO, RW]
Eligible: [0, 1, 3]
Random selection: One of {0, 1, 3} with equal probability
```

### Scenario 2: Mixed Errors
```
Branch 0: RW but filesystem full (ENOSPC)
Branch 1: RO (EROFS)
Branch 2: RW but path doesn't exist (ENOENT)
Result: Error EROFS (highest priority)
```

### Scenario 3: Single Eligible Branch
```
Branches: [RO, RO, RW, RO]
Eligible: [2]
Result: Branch 2 selected (no randomization needed)
```

## Performance Considerations

The C++ implementation optimizes for:
- **Memory efficiency**: Reuses the paths vector, just shrinks it
- **Random number generation**: Uses thread-local static generator
- **Branch validation**: Single pass through all branches

These optimizations should be considered in the Rust implementation while maintaining idiomatic Rust patterns.