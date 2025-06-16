# Tracing Enhancements for mergerfs-rs

## Overview

Comprehensive tracing has been added to all major FUSE operations in the mergerfs-rs implementation. This provides detailed visibility into the filesystem's behavior, including operation timing, policy decisions, branch selection, and error handling.

## Tracing Spans Added

### File Operations (`file_ops.rs`)

1. **create_file** - `info_span!("file_ops::create_file")`
   - Includes: path, content_size
   - Logs: branch selection, full path, success/failure

2. **write_to_file** - `debug_span!("file_ops::write_to_file")`
   - Includes: path, offset, data_len
   - Logs: branch search, bytes written

3. **truncate_file** - `info_span!("file_ops::truncate_file")`
   - Includes: path, size
   - Logs: branch search, truncation result

4. **create_directory** - `info_span!("file_ops::create_directory")`
   - Includes: path
   - Logs: branch selection, creation result

5. **create_symlink** - `info_span!("file_ops::create_symlink")`
   - Includes: link path, target path
   - Logs: branch selection, symlink creation

6. **create_hard_link** - `info_span!("file_ops::create_hard_link")`
   - Includes: source path, link path
   - Logs: source branch, link creation

7. **remove_file** - `info_span!("file_ops::remove_file")`
   - Includes: path
   - Logs: branch search, removal from each branch

8. **remove_directory** - `info_span!("file_ops::remove_directory")`
   - Includes: path
   - Logs: branch search, removal from each branch

### FUSE Operations (`fuse_fs.rs`)

1. **create** - `info_span!("fuse::create")`
   - Includes: parent inode, name, mode, umask, flags
   - Logs: file creation details, policy evaluation

2. **write** - `info_span!("fuse::write")`
   - Includes: inode, file handle, offset, length, flags
   - Logs: file handle usage, branch selection, bytes written

3. **mkdir** - `info_span!("fuse::mkdir")`
   - Includes: parent inode, name, mode, umask
   - Logs: directory creation path

4. **rename** - `info_span!("fuse::rename")`
   - Includes: parent inodes, old/new names, flags
   - Logs: rename strategy, path resolution

5. **setattr** - `info_span!("fuse::setattr")`
   - Includes: inode, mode, uid, gid, size, timestamps, flags
   - Logs: individual attribute changes (chmod, chown, truncate, utimens)

6. **unlink** - `info_span!("fuse::unlink")`
   - Includes: parent inode, name
   - Logs: file removal path

7. **rmdir** - `info_span!("fuse::rmdir")`
   - Includes: parent inode, name
   - Logs: directory removal path

8. **getxattr** - `info_span!("fuse::getxattr")`
   - Includes: inode, attribute name, size
   - Logs: attribute retrieval, value size

9. **setxattr** - `info_span!("fuse::setxattr")`
   - Includes: inode, attribute name, value length, flags
   - Logs: attribute setting result

10. **listxattr** - `info_span!("fuse::listxattr")`
    - Includes: inode, size
    - Logs: number of attributes found

11. **removexattr** - `info_span!("fuse::removexattr")`
    - Includes: inode, attribute name
    - Logs: attribute removal result

### Metadata Operations (`metadata_ops.rs`)

1. **chmod** - `info_span!("metadata::chmod")`
   - Includes: path, mode (octal format)
   - Logs: branch selection, success per branch

2. **chown** - `info_span!("metadata::chown")`
   - Includes: path, uid, gid
   - Logs: branch selection, success per branch

3. **utimens** - `info_span!("metadata::utimens")`
   - Includes: path, atime, mtime
   - Logs: branch selection, success per branch

### Extended Attributes (`xattr/operations.rs`)

1. **get_xattr** - `info_span!("xattr::get_xattr")`
   - Includes: path, attribute name
   - Logs: branch search, value retrieval

2. **set_xattr** - `info_span!("xattr::set_xattr")`
   - Includes: path, name, value length, flags
   - Logs: branch selection, mergerfs attribute blocking

3. **list_xattr** - `info_span!("xattr::list_xattr")`
   - Includes: path
   - Logs: branch search, attribute count

4. **remove_xattr** - `info_span!("xattr::remove_xattr")`
   - Includes: path, attribute name
   - Logs: branch selection, mergerfs attribute blocking

### Rename Operations (`rename_ops.rs`)

1. **rename** - `info_span!("rename::rename")`
   - Includes: old path, new path
   - Logs: strategy selection (path-preserving vs create-path)

2. **rename_preserve_path** - `debug_span!("rename::preserve_path")`
   - Includes: old path, new path
   - Logs: per-branch rename attempts

3. **rename_create_path** - `debug_span!("rename::create_path")`
   - Includes: old path, new path
   - Logs: parent directory creation, rename attempts

## Usage

To enable tracing, set the `RUST_LOG` environment variable:

```bash
# Enable all tracing (debug level)
RUST_LOG=mergerfs_rs=debug mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Enable info-level tracing only
RUST_LOG=mergerfs_rs=info mergerfs /mnt/union /mnt/disk1 /mnt/disk2

# Enable tracing for specific modules
RUST_LOG=mergerfs_rs::file_ops=debug,mergerfs_rs::fuse_fs=info mergerfs /mnt/union /mnt/disk1 /mnt/disk2
```

## Benefits

1. **Debugging**: Detailed operation traces help identify issues quickly
2. **Performance Analysis**: Timing information helps identify bottlenecks
3. **Policy Verification**: See which branches are selected by policies
4. **Error Tracking**: Detailed error context for troubleshooting
5. **Operational Visibility**: Monitor filesystem behavior in production

## Example Output

```
INFO fuse::create{parent=1 name="test.txt" mode="644" umask="22" flags="0x8042"} mergerfs_rs::fuse_fs: Starting create operation
DEBUG fuse::create{parent=1 name="test.txt" mode="644" umask="22" flags="0x8042"} mergerfs_rs::fuse_fs: Creating file at path: "/test.txt"
INFO file_ops::create_file{path="/test.txt" content_size=0} mergerfs_rs::file_ops: Selected branch "/mnt/disk1" for creating file "/test.txt"
INFO file_ops::create_file{path="/test.txt" content_size=0} mergerfs_rs::file_ops: File created successfully at "/mnt/disk1/test.txt" with 0 bytes
INFO fuse::create{parent=1 name="test.txt" mode="644" umask="22" flags="0x8042"} mergerfs_rs::fuse_fs: File created successfully at "/test.txt"
```

## Testing

A comprehensive test suite (`test_tracing_verification.py`) has been added to verify that all tracing spans are properly emitted during normal filesystem operations.