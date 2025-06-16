# mknod Operation Design

## Overview

The `mknod` FUSE operation creates special files (device files, FIFOs, sockets) or regular files. This operation is essential for creating non-regular files that cannot be created through the standard `create` operation.

## C++ Implementation Analysis

### Key Components

1. **Policy-based branch selection**:
   - Uses search policy to find existing branches with the parent directory
   - Uses create policy to select branches for creating the new special file
   - Implements path cloning from existing to create branches

2. **Special file creation**:
   - Supports all file types: regular files, character devices, block devices, FIFOs, sockets
   - Applies umask unless directory has default ACLs
   - Uses the system `mknod` call with appropriate mode and device numbers

3. **Error handling**:
   - Handles EROFS by marking branches read-only and retrying
   - Aggregates errors across multiple branches
   - Returns appropriate errno values

### C++ Implementation Flow (Pseudocode)

```
function mknod(fusepath, mode, rdev):
    // Get configuration and set user/group context
    config = get_config()
    ugid = set_ugid_context(uid, gid)
    
    // Extract directory path
    fusedirpath = dirname(fusepath)
    
    // Find branches with existing parent directory
    existingbranches = search_policy(branches, fusedirpath)
    if existingbranches.empty():
        return -ENOENT
    
    // Select branches for creation
    createbranches = create_policy(branches, fusedirpath)
    if createbranches.empty():
        return -ENOSPC
    
    // Create special file on each selected branch
    error = -1
    for branch in createbranches:
        // Clone parent directory path if needed
        rv = clone_path_as_root(existingbranches[0], branch, fusedirpath)
        if rv == -1:
            error = aggregate_error(rv, error, errno)
            continue
            
        // Create the special file
        fullpath = join_path(branch, fusepath)
        
        // Apply umask unless directory has default ACLs
        if !has_default_acls(fullpath):
            mode &= ~umask
            
        rv = system_mknod(fullpath, mode, rdev)
        error = aggregate_error(rv, error, errno)
    
    return -error
```

## Rust Implementation Design

### Key Differences from Current Implementation

1. **Support all file types**: Current implementation only supports regular files
2. **Use nix::sys::stat::mknod**: Instead of creating regular files with File::create
3. **Device number handling**: Pass through rdev parameter for device files
4. **Mode type mapping**: Convert FUSE mode bits to nix SFlag types

### Implementation Plan

1. **Add nix imports**:
   ```rust
   use nix::sys::stat::{mknod as nix_mknod, Mode, SFlag};
   use nix::unistd::mkfifo;
   ```

2. **Map file type from mode**:
   ```rust
   fn get_file_type(mode: u32) -> SFlag {
       match mode & 0o170000 {
           0o010000 => SFlag::S_IFIFO,   // FIFO
           0o020000 => SFlag::S_IFCHR,   // Character device
           0o060000 => SFlag::S_IFBLK,   // Block device
           0o100000 => SFlag::S_IFREG,   // Regular file
           0o140000 => SFlag::S_IFSOCK,  // Socket
           _ => SFlag::empty(),
       }
   }
   ```

3. **Implement special file creation**:
   ```rust
   fn create_special_file(path: &Path, mode: u32, rdev: u32) -> Result<()> {
       let file_type = get_file_type(mode);
       let permissions = Mode::from_bits_truncate(mode & 0o7777);
       
       match file_type {
           SFlag::S_IFIFO => {
               // Use mkfifo for named pipes (simpler API)
               mkfifo(path, permissions)?;
           }
           _ => {
               // Use mknod for all other types
               nix_mknod(path, file_type, permissions, rdev as dev_t)?;
           }
       }
       Ok(())
   }
   ```

4. **Update FileManager trait**:
   - Add `create_special_file` method
   - Implement branch selection and path cloning logic
   - Handle errors appropriately

### Error Mapping

- `ENOENT`: Parent directory doesn't exist
- `ENOSPC`: No writable branches available
- `EPERM`: Insufficient permissions (for device files)
- `EEXIST`: File already exists
- `EIO`: I/O error during creation

### Testing Strategy

1. **Unit tests**:
   - Test file type detection from mode bits
   - Test permission bit handling
   - Mock nix::mknod calls for different file types

2. **Integration tests**:
   - Create FIFOs and verify with `stat`
   - Test error cases (missing parent, permissions)
   - Verify proper branch selection

3. **Python end-to-end tests**:
   - Create named pipes using os.mkfifo through FUSE
   - Verify special file attributes
   - Test cross-branch behavior

### Security Considerations

1. **Device file creation**: Typically requires elevated privileges
2. **Permission checks**: Ensure proper permission validation
3. **Device number validation**: Validate rdev parameter for device files

### Platform Compatibility

- Use nix crate for portable special file creation
- Avoid direct libc calls
- Handle platform-specific limitations gracefully