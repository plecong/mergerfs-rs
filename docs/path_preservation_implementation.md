# Path Preservation Implementation in mergerfs

## Overview

Path preservation is a key feature in mergerfs that ensures files are placed in branches where their parent directories already exist. This is implemented through the "existing path" (ep*) policies.

## Key Concepts

### Path Preserving vs Non-Path Preserving Policies

1. **Path Preserving Policies** (ep* policies):
   - Only consider branches where the relative path already exists
   - All policies starting with `ep`: `epall`, `epff`, `eplfs`, `epmfs`, `eprand`, etc.
   - Also includes `msp*` (most shared path) policies for controlling link/rename behaviors

2. **Non-Path Preserving Policies**:
   - Can select any branch regardless of existing directory structure
   - Examples: `ff`, `mfs`, `lfs`, `rand`, etc.

## Implementation Details

### Policy Structure

Each policy type implements three variants:
- **Action**: For operations like chmod, chown, link, rename, etc.
- **Create**: For operations like create, mkdir, mknod, symlink
- **Search**: For operations like access, getattr, open, readlink

### Path Preservation Flag

In `policy.hpp`, the CreateImpl base class defines:
```cpp
virtual bool path_preserving(void) const = 0;
```

Path preserving policies return `true` from this method.

### Core Algorithm

The path preservation logic works as follows:

1. **Directory Path Extraction**: Get the parent directory of the target path
2. **Search for Existing Paths**: Use the search policy to find branches where the parent directory exists
3. **Branch Selection**: Apply the specific policy algorithm (ff, mfs, etc.) only to branches with existing paths
4. **Path Cloning**: If needed, clone the directory structure from an existing branch to the selected branch

### Example: Creating a File with epff

From `fuse_create.cpp`:

```cpp
static int
_create(const Policy::Search &searchFunc_,
        const Policy::Create &createFunc_,
        const Branches       &branches_,
        const char           *fusepath_,
        fuse_file_info_t     *ffi_,
        const mode_t          mode_,
        const mode_t          umask_)
{
    int rv;
    std::string fullpath;
    std::string fusedirpath;
    std::vector<Branch*> createpaths;
    std::vector<Branch*> existingpaths;

    // Get parent directory
    fusedirpath = fs::path::dirname(fusepath_);

    // Find branches where parent exists (using search policy)
    rv = searchFunc_(branches_,fusedirpath,existingpaths);
    if(rv == -1)
        return -errno;

    // Select branch for creation (using create policy)
    rv = createFunc_(branches_,fusedirpath,createpaths);
    if(rv == -1)
        return -errno;

    // Clone directory structure if needed
    rv = fs::clonepath_as_root(existingpaths[0]->path,
                               createpaths[0]->path,
                               fusedirpath);
    if(rv == -1)
        return -errno;

    // Create the file
    return ::_create_core(createpaths[0],
                          fusepath_,
                          ffi_,
                          mode_,
                          umask_);
}
```

### Policy Implementation Example: epff

The `epff` (existing path, first found) policy:

```cpp
static int
create(const Branches::Ptr  &branches_,
       const char           *fusepath_,
       std::vector<Branch*> &paths_)
{
    int rv;
    int error;
    fs::info_t info;

    error = ENOENT;
    for(auto &branch : *branches_)
    {
        // Skip read-only or no-create branches
        if(branch.ro_or_nc())
            error_and_continue(error,EROFS);
        
        // Check if path exists in this branch
        if(!fs::exists(branch.path,fusepath_))
            error_and_continue(error,ENOENT);
        
        // Check filesystem info
        rv = fs::info(branch.path,&info);
        if(rv == -1)
            error_and_continue(error,ENOENT);
        if(info.readonly)
            error_and_continue(error,EROFS);
        if(info.spaceavail < branch.minfreespace())
            error_and_continue(error,ENOSPC);

        // Found first valid branch with existing path
        paths_.push_back(&branch);
        return 0;
    }

    return (errno=error,-1);
}
```

### Path Cloning

The `fs::clonepath` function recursively creates directory structures:

```cpp
int clonepath(const string &fromsrc_,
              const string &tosrc_,
              const char   *relative_,
              const bool    return_metadata_errors_)
{
    // Recursively create parent directories
    dirname = fs::path::dirname(relative_);
    if(dirname != "/")
    {
        rv = fs::clonepath(fromsrc_,tosrc_,dirname,return_metadata_errors_);
        if(rv == -1)
            return -1;
    }

    // Get source directory metadata
    frompath = fs::path::make(fromsrc_,relative_);
    rv = fs::lstat(frompath,&st);
    if(rv == -1)
        return -1;

    // Create directory with same permissions
    topath = fs::path::make(tosrc_,relative_);
    rv = fs::mkdir(topath,st.st_mode);
    if(rv == -1 && errno != EEXIST)
        return -1;

    // Copy attributes, xattrs, ownership, timestamps
    fs::attr::copy(frompath,topath);
    fs::xattr::copy(frompath,topath);
    fs::lchown_check_on_error(topath,st);
    fs::lutimens(topath,st);

    return 0;
}
```

## Usage Pattern

Path preservation is used consistently across file creation operations:

1. **create**: Uses getattr policy to find existing parent, create policy to select branch
2. **mkdir**: Same pattern - find existing parent, select branch, clone path
3. **symlink**: Same pattern
4. **mknod**: Same pattern

## Benefits

1. **Maintains Directory Structure**: Files stay organized in their logical locations
2. **Predictable Behavior**: Users can control where files are placed
3. **Efficient Storage**: Related files stay together on the same branch
4. **Compatibility**: Works well with applications expecting consistent directory structures

## Configuration

Path preservation is inherent to the policy, not a separate configuration option. To use path preservation, simply select an `ep*` policy for the desired operation:

- `func.create.policy=epff` - Use existing path, first found for file creation
- `func.mkdir.policy=epmfs` - Use existing path, most free space for directory creation
- etc.