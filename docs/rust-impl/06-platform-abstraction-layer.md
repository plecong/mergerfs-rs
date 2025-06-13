# Platform Abstraction Layer Implementation in Rust

## Overview

This guide provides a comprehensive approach to implementing mergerfs's platform abstraction layer in Rust, handling cross-platform filesystem operations, platform-specific optimizations, and conditional compilation patterns while maintaining type safety and performance. The implementation is designed to be compatible with both glibc and musl libc, making it suitable for Alpine Linux and other musl-based distributions.

## Core Platform Architecture

### Operating System Detection and Feature Flags

#### Musl vs Glibc Compatibility

The implementation avoids glibc-specific functions to ensure compatibility with Alpine Linux and other musl-based distributions:

```rust
// Portable errno handling instead of glibc-specific __errno_location()
use errno::{errno, set_errno, Errno};

// Helper function for portable errno access
pub fn get_last_errno() -> i32 {
    errno().0
}

pub fn clear_errno() {
    set_errno(Errno(0));
}

// Feature detection works on both glibc and musl
#[cfg(target_env = "gnu")]
const IS_GLIBC: bool = true;

#[cfg(target_env = "musl")]
const IS_MUSL: bool = true;
```

#### Dependencies for Musl Compatibility

```toml
[dependencies]
libc = "0.2"
errno = "0.3"  # For portable errno handling across glibc and musl
```

#### Compile-Time Platform Detection

```rust
// Platform feature detection
use errno::{errno, set_errno, Errno};
#[cfg(target_os = "linux")]
pub const PLATFORM: &str = "linux";
#[cfg(target_os = "macos")]
pub const PLATFORM: &str = "macos";
#[cfg(target_os = "freebsd")]
pub const PLATFORM: &str = "freebsd";
#[cfg(target_os = "openbsd")]
pub const PLATFORM: &str = "openbsd";
#[cfg(target_os = "netbsd")]
pub const PLATFORM: &str = "netbsd";

// Feature availability detection
pub mod features {
    // Extended attributes support
    #[cfg(any(target_os = "linux", target_os = "macos", target_os = "freebsd"))]
    pub const HAS_XATTR: bool = true;
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "freebsd")))]
    pub const HAS_XATTR: bool = false;
    
    // Advanced file operations
    #[cfg(target_os = "linux")]
    pub const HAS_SPLICE: bool = true;
    #[cfg(not(target_os = "linux"))]
    pub const HAS_SPLICE: bool = false;
    
    #[cfg(target_os = "linux")]
    pub const HAS_SENDFILE: bool = true;
    #[cfg(any(target_os = "freebsd", target_os = "macos"))]
    pub const HAS_SENDFILE: bool = true;
    #[cfg(not(any(target_os = "linux", target_os = "freebsd", target_os = "macos")))]
    pub const HAS_SENDFILE: bool = false;
    
    // Copy-on-write support
    #[cfg(target_os = "linux")]
    pub const HAS_COPY_FILE_RANGE: bool = true;
    #[cfg(not(target_os = "linux"))]
    pub const HAS_COPY_FILE_RANGE: bool = false;
    
    #[cfg(target_os = "macos")]
    pub const HAS_CLONEFILE: bool = true;
    #[cfg(not(target_os = "macos"))]
    pub const HAS_CLONEFILE: bool = false;
    
    // File locking
    #[cfg(any(target_os = "linux", target_os = "macos", target_os = "freebsd"))]
    pub const HAS_FLOCK: bool = true;
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "freebsd")))]
    pub const HAS_FLOCK: bool = false;
    
    // Directory monitoring
    #[cfg(target_os = "linux")]
    pub const HAS_INOTIFY: bool = true;
    #[cfg(not(target_os = "linux"))]
    pub const HAS_INOTIFY: bool = false;
    
    #[cfg(target_os = "macos")]
    pub const HAS_KQUEUE: bool = true;
    #[cfg(any(target_os = "freebsd", target_os = "openbsd", target_os = "netbsd"))]
    pub const HAS_KQUEUE: bool = true;
    #[cfg(not(any(target_os = "macos", target_os = "freebsd", target_os = "openbsd", target_os = "netbsd")))]
    pub const HAS_KQUEUE: bool = false;
}

// Runtime feature detection
pub struct PlatformCapabilities {
    pub splice_available: bool,
    pub sendfile_available: bool,
    pub copy_file_range_available: bool,
    pub clonefile_available: bool,
    pub xattr_available: bool,
    pub flock_available: bool,
    pub max_path_length: usize,
    pub max_filename_length: usize,
    pub filesystem_case_sensitive: bool,
}

impl PlatformCapabilities {
    pub fn detect() -> Self {
        Self {
            splice_available: Self::check_splice(),
            sendfile_available: Self::check_sendfile(),
            copy_file_range_available: Self::check_copy_file_range(),
            clonefile_available: Self::check_clonefile(),
            xattr_available: Self::check_xattr(),
            flock_available: Self::check_flock(),
            max_path_length: Self::get_max_path_length(),
            max_filename_length: Self::get_max_filename_length(),
            filesystem_case_sensitive: Self::check_case_sensitivity(),
        }
    }
    
    #[cfg(target_os = "linux")]
    fn check_splice() -> bool {
        // Try to create a pipe and use splice
        unsafe {
            let mut pipes = [0i32; 2];
            if libc::pipe(pipes.as_mut_ptr()) == 0 {
                let result = libc::splice(
                    pipes[0], std::ptr::null_mut(),
                    pipes[1], std::ptr::null_mut(),
                    0, libc::SPLICE_F_NONBLOCK
                );
                libc::close(pipes[0]);
                libc::close(pipes[1]);
                // Use portable errno check instead of glibc-specific __errno_location
                result != -1 || std::io::Error::last_os_error().raw_os_error() != Some(libc::ENOSYS)
            } else {
                false
            }
        }
    }
    
    #[cfg(not(target_os = "linux"))]
    fn check_splice() -> bool {
        false
    }
    
    #[cfg(any(target_os = "linux", target_os = "freebsd", target_os = "macos"))]
    fn check_sendfile() -> bool {
        // Platform has sendfile, assume it works
        true
    }
    
    #[cfg(not(any(target_os = "linux", target_os = "freebsd", target_os = "macos")))]
    fn check_sendfile() -> bool {
        false
    }
    
    #[cfg(target_os = "linux")]
    fn check_copy_file_range() -> bool {
        // Check kernel version or try the syscall
        std::fs::read_to_string("/proc/version")
            .map(|version| version.contains("Linux"))
            .unwrap_or(false)
    }
    
    #[cfg(not(target_os = "linux"))]
    fn check_copy_file_range() -> bool {
        false
    }
    
    #[cfg(target_os = "macos")]
    fn check_clonefile() -> bool {
        // macOS 10.12+ has clonefile
        let version = Self::get_macos_version();
        version.0 > 10 || (version.0 == 10 && version.1 >= 12)
    }
    
    #[cfg(not(target_os = "macos"))]
    fn check_clonefile() -> bool {
        false
    }
    
    #[cfg(any(target_os = "linux", target_os = "macos", target_os = "freebsd"))]
    fn check_xattr() -> bool {
        // Try to get xattr on a temporary file
        use std::ffi::CString;
        let temp_path = CString::new("/tmp/.xattr_test").unwrap();
        unsafe {
            let fd = libc::open(temp_path.as_ptr(), libc::O_CREAT | libc::O_WRONLY, 0o600);
            if fd >= 0 {
                let test_name = CString::new("user.test").unwrap();
                let result = libc::getxattr(
                    temp_path.as_ptr(),
                    test_name.as_ptr(),
                    std::ptr::null_mut(),
                    0
                );
                libc::close(fd);
                libc::unlink(temp_path.as_ptr());
                // Use portable errno check instead of glibc-specific __errno_location
                result >= 0 || std::io::Error::last_os_error().raw_os_error() != Some(libc::ENOSYS)
            } else {
                false
            }
        }
    }
    
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "freebsd")))]
    fn check_xattr() -> bool {
        false
    }
    
    fn check_flock() -> bool {
        features::HAS_FLOCK
    }
    
    #[cfg(target_os = "macos")]
    fn get_macos_version() -> (u32, u32) {
        use std::ffi::CString;
        use std::mem;
        
        unsafe {
            let mut size = 0;
            let name = CString::new("kern.osrelease").unwrap();
            libc::sysctlbyname(
                name.as_ptr(),
                std::ptr::null_mut(),
                &mut size,
                std::ptr::null_mut(),
                0
            );
            
            let mut buffer = vec![0u8; size];
            libc::sysctlbyname(
                name.as_ptr(),
                buffer.as_mut_ptr() as *mut libc::c_void,
                &mut size,
                std::ptr::null_mut(),
                0
            );
            
            let version_str = String::from_utf8_lossy(&buffer);
            let parts: Vec<&str> = version_str.trim_end_matches('\0').split('.').collect();
            
            if parts.len() >= 2 {
                let major = parts[0].parse().unwrap_or(0);
                let minor = parts[1].parse().unwrap_or(0);
                (major, minor)
            } else {
                (0, 0)
            }
        }
    }
    
    fn get_max_path_length() -> usize {
        unsafe { libc::pathconf(b"/\0".as_ptr() as *const i8, libc::_PC_PATH_MAX) as usize }
    }
    
    fn get_max_filename_length() -> usize {
        unsafe { libc::pathconf(b"/\0".as_ptr() as *const i8, libc::_PC_NAME_MAX) as usize }
    }
    
    fn check_case_sensitivity() -> bool {
        // Create a test file and try to access it with different case
        let test_path = "/tmp/CaseSensitivityTest";
        let test_path_lower = "/tmp/casesensitivitytest";
        
        if std::fs::write(test_path, "test").is_ok() {
            let case_sensitive = !std::path::Path::new(test_path_lower).exists();
            let _ = std::fs::remove_file(test_path);
            case_sensitive
        } else {
            true // Assume case-sensitive by default
        }
    }
}

// Global capabilities instance
use std::sync::OnceLock;
static PLATFORM_CAPABILITIES: OnceLock<PlatformCapabilities> = OnceLock::new();

pub fn get_platform_capabilities() -> &'static PlatformCapabilities {
    PLATFORM_CAPABILITIES.get_or_init(PlatformCapabilities::detect)
}
```

### Filesystem Operations Abstraction

#### Cross-Platform File Operations

```rust
use std::path::Path;
use std::os::unix::io::RawFd;

pub trait FileSystemOps {
    type Error: std::error::Error + Send + Sync + 'static;
    
    // Basic file operations
    fn open(&self, path: &Path, flags: i32, mode: u32) -> Result<RawFd, Self::Error>;
    fn close(&self, fd: RawFd) -> Result<(), Self::Error>;
    fn read(&self, fd: RawFd, buf: &mut [u8], offset: u64) -> Result<usize, Self::Error>;
    fn write(&self, fd: RawFd, buf: &[u8], offset: u64) -> Result<usize, Self::Error>;
    fn fsync(&self, fd: RawFd) -> Result<(), Self::Error>;
    fn ftruncate(&self, fd: RawFd, size: u64) -> Result<(), Self::Error>;
    
    // File metadata
    fn stat(&self, path: &Path) -> Result<FileStat, Self::Error>;
    fn lstat(&self, path: &Path) -> Result<FileStat, Self::Error>;
    fn fstat(&self, fd: RawFd) -> Result<FileStat, Self::Error>;
    fn utimes(&self, path: &Path, atime: u64, mtime: u64) -> Result<(), Self::Error>;
    fn chmod(&self, path: &Path, mode: u32) -> Result<(), Self::Error>;
    fn chown(&self, path: &Path, uid: u32, gid: u32) -> Result<(), Self::Error>;
    
    // Directory operations
    fn mkdir(&self, path: &Path, mode: u32) -> Result<(), Self::Error>;
    fn rmdir(&self, path: &Path) -> Result<(), Self::Error>;
    fn readdir(&self, path: &Path) -> Result<Vec<DirEntry>, Self::Error>;
    
    // Link operations
    fn link(&self, old_path: &Path, new_path: &Path) -> Result<(), Self::Error>;
    fn unlink(&self, path: &Path) -> Result<(), Self::Error>;
    fn symlink(&self, target: &Path, link_path: &Path) -> Result<(), Self::Error>;
    fn readlink(&self, path: &Path) -> Result<std::path::PathBuf, Self::Error>;
    fn rename(&self, from: &Path, to: &Path) -> Result<(), Self::Error>;
    
    // Extended attributes (optional)
    fn getxattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, Self::Error>;
    fn setxattr(&self, path: &Path, name: &str, value: &[u8]) -> Result<(), Self::Error>;
    fn removexattr(&self, path: &Path, name: &str) -> Result<(), Self::Error>;
    fn listxattr(&self, path: &Path) -> Result<Vec<String>, Self::Error>;
    
    // Platform-specific optimizations
    fn copy_file_fast(&self, src: &Path, dst: &Path) -> Result<(), Self::Error>;
    fn copy_file_range(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error>;
}

#[derive(Debug, Clone)]
pub struct FileStat {
    pub size: u64,
    pub mode: u32,
    pub uid: u32,
    pub gid: u32,
    pub atime: u64,
    pub mtime: u64,
    pub ctime: u64,
    pub inode: u64,
    pub device: u64,
    pub nlinks: u64,
    pub blksize: u32,
    pub blocks: u64,
}

#[derive(Debug, Clone)]
pub struct DirEntry {
    pub name: String,
    pub file_type: FileType,
    pub inode: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileType {
    RegularFile,
    Directory,
    SymbolicLink,
    CharacterDevice,
    BlockDevice,
    Fifo,
    Socket,
    Unknown,
}

// Platform-specific implementations
#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;
#[cfg(target_os = "freebsd")]
pub mod freebsd;

// Default implementation using standard library
pub struct StdFileSystemOps;

impl FileSystemOps for StdFileSystemOps {
    type Error = std::io::Error;
    
    fn open(&self, path: &Path, flags: i32, mode: u32) -> Result<RawFd, Self::Error> {
        use std::ffi::CString;
        let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
        
        let fd = unsafe { libc::open(path_cstr.as_ptr(), flags, mode) };
        if fd < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(fd)
        }
    }
    
    fn close(&self, fd: RawFd) -> Result<(), Self::Error> {
        let result = unsafe { libc::close(fd) };
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    
    fn read(&self, fd: RawFd, buf: &mut [u8], offset: u64) -> Result<usize, Self::Error> {
        let result = unsafe {
            libc::pread(
                fd,
                buf.as_mut_ptr() as *mut libc::c_void,
                buf.len(),
                offset as libc::off_t,
            )
        };
        
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(result as usize)
        }
    }
    
    fn write(&self, fd: RawFd, buf: &[u8], offset: u64) -> Result<usize, Self::Error> {
        let result = unsafe {
            libc::pwrite(
                fd,
                buf.as_ptr() as *const libc::c_void,
                buf.len(),
                offset as libc::off_t,
            )
        };
        
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(result as usize)
        }
    }
    
    fn fsync(&self, fd: RawFd) -> Result<(), Self::Error> {
        let result = unsafe { libc::fsync(fd) };
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    
    fn ftruncate(&self, fd: RawFd, size: u64) -> Result<(), Self::Error> {
        let result = unsafe { libc::ftruncate(fd, size as libc::off_t) };
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    
    fn stat(&self, path: &Path) -> Result<FileStat, Self::Error> {
        use std::ffi::CString;
        use std::mem::MaybeUninit;
        
        let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
        let mut stat_buf: MaybeUninit<libc::stat> = MaybeUninit::uninit();
        
        let result = unsafe {
            libc::stat(path_cstr.as_ptr(), stat_buf.as_mut_ptr())
        };
        
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            let stat = unsafe { stat_buf.assume_init() };
            Ok(FileStat::from_libc_stat(stat))
        }
    }
    
    fn lstat(&self, path: &Path) -> Result<FileStat, Self::Error> {
        use std::ffi::CString;
        use std::mem::MaybeUninit;
        
        let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
        let mut stat_buf: MaybeUninit<libc::stat> = MaybeUninit::uninit();
        
        let result = unsafe {
            libc::lstat(path_cstr.as_ptr(), stat_buf.as_mut_ptr())
        };
        
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            let stat = unsafe { stat_buf.assume_init() };
            Ok(FileStat::from_libc_stat(stat))
        }
    }
    
    fn fstat(&self, fd: RawFd) -> Result<FileStat, Self::Error> {
        use std::mem::MaybeUninit;
        
        let mut stat_buf: MaybeUninit<libc::stat> = MaybeUninit::uninit();
        let result = unsafe { libc::fstat(fd, stat_buf.as_mut_ptr()) };
        
        if result < 0 {
            Err(std::io::Error::last_os_error())
        } else {
            let stat = unsafe { stat_buf.assume_init() };
            Ok(FileStat::from_libc_stat(stat))
        }
    }
    
    // Implementation continues with other methods...
    fn copy_file_fast(&self, src: &Path, dst: &Path) -> Result<(), Self::Error> {
        // Fallback to standard copy
        std::fs::copy(src, dst).map(|_| ())
    }
    
    fn copy_file_range(&self, _src_fd: RawFd, _dst_fd: RawFd, _len: u64) -> Result<u64, Self::Error> {
        Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "copy_file_range not supported on this platform"
        ))
    }
    
    // ... other method implementations
}

impl FileStat {
    fn from_libc_stat(stat: libc::stat) -> Self {
        Self {
            size: stat.st_size as u64,
            mode: stat.st_mode,
            uid: stat.st_uid,
            gid: stat.st_gid,
            atime: stat.st_atime as u64,
            mtime: stat.st_mtime as u64,
            ctime: stat.st_ctime as u64,
            inode: stat.st_ino,
            device: stat.st_dev,
            nlinks: stat.st_nlink,
            blksize: stat.st_blksize as u32,
            blocks: stat.st_blocks as u64,
        }
    }
}
```

### Linux-Specific Optimizations

#### Linux Platform Implementation

```rust
#[cfg(target_os = "linux")]
pub mod linux {
    use super::*;
    use std::ffi::CString;
    use std::os::unix::io::RawFd;
    
    pub struct LinuxFileSystemOps {
        base: StdFileSystemOps,
        capabilities: &'static PlatformCapabilities,
    }
    
    impl LinuxFileSystemOps {
        pub fn new() -> Self {
            Self {
                base: StdFileSystemOps,
                capabilities: get_platform_capabilities(),
            }
        }
    }
    
    impl FileSystemOps for LinuxFileSystemOps {
        type Error = std::io::Error;
        
        // Delegate most operations to base implementation
        fn open(&self, path: &Path, flags: i32, mode: u32) -> Result<RawFd, Self::Error> {
            self.base.open(path, flags, mode)
        }
        
        fn close(&self, fd: RawFd) -> Result<(), Self::Error> {
            self.base.close(fd)
        }
        
        fn read(&self, fd: RawFd, buf: &mut [u8], offset: u64) -> Result<usize, Self::Error> {
            self.base.read(fd, buf, offset)
        }
        
        fn write(&self, fd: RawFd, buf: &[u8], offset: u64) -> Result<usize, Self::Error> {
            self.base.write(fd, buf, offset)
        }
        
        // Linux-specific optimized implementations
        fn copy_file_range(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error> {
            if !self.capabilities.copy_file_range_available {
                return self.fallback_copy_file_range(src_fd, dst_fd, len);
            }
            
            let result = unsafe {
                libc::syscall(
                    libc::SYS_copy_file_range,
                    src_fd,
                    std::ptr::null_mut::<libc::off_t>(), // src_off
                    dst_fd,
                    std::ptr::null_mut::<libc::off_t>(), // dst_off
                    len,
                    0u32, // flags
                )
            };
            
            if result < 0 {
                let errno = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
                if errno == libc::ENOSYS || errno == libc::EXDEV {
                    // Fallback for unsupported operation or cross-device
                    self.fallback_copy_file_range(src_fd, dst_fd, len)
                } else {
                    Err(std::io::Error::last_os_error())
                }
            } else {
                Ok(result as u64)
            }
        }
        
        fn copy_file_fast(&self, src: &Path, dst: &Path) -> Result<(), Self::Error> {
            // Try copy_file_range first
            let src_fd = self.open(src, libc::O_RDONLY, 0)?;
            let dst_fd = self.open(dst, libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC, 0o644)?;
            
            let src_stat = self.fstat(src_fd)?;
            let mut remaining = src_stat.size;
            let mut total_copied = 0u64;
            
            while remaining > 0 {
                let to_copy = remaining.min(1024 * 1024); // 1MB chunks
                match self.copy_file_range(src_fd, dst_fd, to_copy) {
                    Ok(copied) => {
                        if copied == 0 {
                            break; // No more data
                        }
                        total_copied += copied;
                        remaining -= copied;
                    }
                    Err(_) => {
                        // Fallback to splice or sendfile
                        self.close(src_fd)?;
                        self.close(dst_fd)?;
                        return self.fallback_copy_file(src, dst);
                    }
                }
            }
            
            self.close(src_fd)?;
            self.close(dst_fd)?;
            Ok(())
        }
        
        // Extended attributes with Linux-specific optimizations
        fn getxattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, Self::Error> {
            if !self.capabilities.xattr_available {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::Unsupported,
                    "Extended attributes not supported"
                ));
            }
            
            let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
            let name_cstr = CString::new(name)?;
            
            // Get size first
            let size = unsafe {
                libc::getxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    std::ptr::null_mut(),
                    0
                )
            };
            
            if size < 0 {
                return Err(std::io::Error::last_os_error());
            }
            
            if size == 0 {
                return Ok(Vec::new());
            }
            
            // Get actual data
            let mut buffer = vec![0u8; size as usize];
            let actual_size = unsafe {
                libc::getxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    buffer.as_mut_ptr() as *mut libc::c_void,
                    size as usize
                )
            };
            
            if actual_size < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                buffer.truncate(actual_size as usize);
                Ok(buffer)
            }
        }
        
        fn setxattr(&self, path: &Path, name: &str, value: &[u8]) -> Result<(), Self::Error> {
            if !self.capabilities.xattr_available {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::Unsupported,
                    "Extended attributes not supported"
                ));
            }
            
            let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
            let name_cstr = CString::new(name)?;
            
            let result = unsafe {
                libc::setxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    value.as_ptr() as *const libc::c_void,
                    value.len(),
                    0
                )
            };
            
            if result < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(())
            }
        }
        
        // ... other FileSystemOps methods
    }
    
    impl LinuxFileSystemOps {
        fn fallback_copy_file_range(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error> {
            if self.capabilities.splice_available {
                self.splice_copy(src_fd, dst_fd, len)
            } else if self.capabilities.sendfile_available {
                self.sendfile_copy(src_fd, dst_fd, len)
            } else {
                self.buffer_copy(src_fd, dst_fd, len)
            }
        }
        
        fn splice_copy(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error> {
            // Create pipe for splice operation
            let mut pipes = [0i32; 2];
            let pipe_result = unsafe { libc::pipe(pipes.as_mut_ptr()) };
            if pipe_result < 0 {
                return Err(std::io::Error::last_os_error());
            }
            
            let pipe_read = pipes[0];
            let pipe_write = pipes[1];
            
            let mut total_copied = 0u64;
            let mut remaining = len;
            
            while remaining > 0 {
                let chunk_size = remaining.min(65536); // 64KB chunks
                
                // Splice from source to pipe
                let to_pipe = unsafe {
                    libc::splice(
                        src_fd,
                        std::ptr::null_mut(),
                        pipe_write,
                        std::ptr::null_mut(),
                        chunk_size as usize,
                        libc::SPLICE_F_MOVE
                    )
                };
                
                if to_pipe <= 0 {
                    break;
                }
                
                // Splice from pipe to destination
                let to_dst = unsafe {
                    libc::splice(
                        pipe_read,
                        std::ptr::null_mut(),
                        dst_fd,
                        std::ptr::null_mut(),
                        to_pipe as usize,
                        libc::SPLICE_F_MOVE
                    )
                };
                
                if to_dst <= 0 {
                    break;
                }
                
                total_copied += to_dst as u64;
                remaining -= to_dst as u64;
            }
            
            unsafe {
                libc::close(pipe_read);
                libc::close(pipe_write);
            }
            
            Ok(total_copied)
        }
        
        fn sendfile_copy(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error> {
            let mut total_copied = 0u64;
            let mut remaining = len;
            
            while remaining > 0 {
                let chunk_size = remaining.min(1024 * 1024); // 1MB chunks
                
                let copied = unsafe {
                    libc::sendfile(
                        dst_fd,
                        src_fd,
                        std::ptr::null_mut(),
                        chunk_size as usize
                    )
                };
                
                if copied <= 0 {
                    if copied < 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                    break;
                }
                
                total_copied += copied as u64;
                remaining -= copied as u64;
            }
            
            Ok(total_copied)
        }
        
        fn buffer_copy(&self, src_fd: RawFd, dst_fd: RawFd, len: u64) -> Result<u64, Self::Error> {
            let mut buffer = vec![0u8; 65536]; // 64KB buffer
            let mut total_copied = 0u64;
            let mut remaining = len;
            
            while remaining > 0 {
                let to_read = remaining.min(buffer.len() as u64) as usize;
                
                let bytes_read = unsafe {
                    libc::read(
                        src_fd,
                        buffer.as_mut_ptr() as *mut libc::c_void,
                        to_read
                    )
                };
                
                if bytes_read <= 0 {
                    if bytes_read < 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                    break;
                }
                
                let bytes_written = unsafe {
                    libc::write(
                        dst_fd,
                        buffer.as_ptr() as *const libc::c_void,
                        bytes_read as usize
                    )
                };
                
                if bytes_written != bytes_read {
                    return Err(std::io::Error::last_os_error());
                }
                
                total_copied += bytes_written as u64;
                remaining -= bytes_written as u64;
            }
            
            Ok(total_copied)
        }
        
        fn fallback_copy_file(&self, src: &Path, dst: &Path) -> Result<(), Self::Error> {
            std::fs::copy(src, dst).map(|_| ())
        }
    }
}
```

### macOS-Specific Optimizations

#### macOS Platform Implementation

```rust
#[cfg(target_os = "macos")]
pub mod macos {
    use super::*;
    use std::ffi::CString;
    use std::os::unix::io::RawFd;
    
    extern "C" {
        fn clonefile(src: *const libc::c_char, dst: *const libc::c_char, flags: u32) -> libc::c_int;
        fn fcopyfile(src_fd: libc::c_int, dst_fd: libc::c_int, state: *mut libc::c_void, flags: u32) -> libc::c_int;
    }
    
    const CLONE_NOFOLLOW: u32 = 0x0001;
    const CLONE_NOOWNERCOPY: u32 = 0x0002;
    
    const COPYFILE_DATA: u32 = 1 << 1;
    const COPYFILE_METADATA: u32 = 1 << 3;
    const COPYFILE_ALL: u32 = COPYFILE_DATA | COPYFILE_METADATA;
    
    pub struct MacOSFileSystemOps {
        base: StdFileSystemOps,
        capabilities: &'static PlatformCapabilities,
    }
    
    impl MacOSFileSystemOps {
        pub fn new() -> Self {
            Self {
                base: StdFileSystemOps,
                capabilities: get_platform_capabilities(),
            }
        }
    }
    
    impl FileSystemOps for MacOSFileSystemOps {
        type Error = std::io::Error;
        
        // Delegate basic operations to base
        fn open(&self, path: &Path, flags: i32, mode: u32) -> Result<RawFd, Self::Error> {
            self.base.open(path, flags, mode)
        }
        
        fn close(&self, fd: RawFd) -> Result<(), Self::Error> {
            self.base.close(fd)
        }
        
        // macOS-specific optimized copy
        fn copy_file_fast(&self, src: &Path, dst: &Path) -> Result<(), Self::Error> {
            if self.capabilities.clonefile_available {
                // Try clonefile first (copy-on-write)
                let src_cstr = CString::new(src.to_string_lossy().as_ref())?;
                let dst_cstr = CString::new(dst.to_string_lossy().as_ref())?;
                
                let result = unsafe {
                    clonefile(src_cstr.as_ptr(), dst_cstr.as_ptr(), CLONE_NOFOLLOW)
                };
                
                if result == 0 {
                    return Ok(());
                }
                
                // If clonefile fails, fall back to copyfile
            }
            
            // Use copyfile API
            let src_fd = self.open(src, libc::O_RDONLY, 0)?;
            let dst_fd = self.open(dst, libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC, 0o644)?;
            
            let result = unsafe {
                fcopyfile(src_fd, dst_fd, std::ptr::null_mut(), COPYFILE_ALL)
            };
            
            self.close(src_fd)?;
            self.close(dst_fd)?;
            
            if result == 0 {
                Ok(())
            } else {
                // Final fallback
                std::fs::copy(src, dst).map(|_| ())
            }
        }
        
        fn copy_file_range(&self, src_fd: RawFd, dst_fd: RawFd, _len: u64) -> Result<u64, Self::Error> {
            // macOS doesn't have copy_file_range, use fcopyfile
            let result = unsafe {
                fcopyfile(src_fd, dst_fd, std::ptr::null_mut(), COPYFILE_DATA)
            };
            
            if result == 0 {
                // Get file size to return bytes copied
                let stat = self.fstat(src_fd)?;
                Ok(stat.size)
            } else {
                Err(std::io::Error::last_os_error())
            }
        }
        
        // macOS extended attributes implementation
        fn getxattr(&self, path: &Path, name: &str) -> Result<Vec<u8>, Self::Error> {
            if !self.capabilities.xattr_available {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::Unsupported,
                    "Extended attributes not supported"
                ));
            }
            
            let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
            let name_cstr = CString::new(name)?;
            
            // Get size first
            let size = unsafe {
                libc::getxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    std::ptr::null_mut(),
                    0,
                    0, // position
                    libc::XATTR_NOFOLLOW
                )
            };
            
            if size < 0 {
                return Err(std::io::Error::last_os_error());
            }
            
            if size == 0 {
                return Ok(Vec::new());
            }
            
            // Get actual data
            let mut buffer = vec![0u8; size as usize];
            let actual_size = unsafe {
                libc::getxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    buffer.as_mut_ptr() as *mut libc::c_void,
                    size as usize,
                    0, // position
                    libc::XATTR_NOFOLLOW
                )
            };
            
            if actual_size < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                buffer.truncate(actual_size as usize);
                Ok(buffer)
            }
        }
        
        fn setxattr(&self, path: &Path, name: &str, value: &[u8]) -> Result<(), Self::Error> {
            if !self.capabilities.xattr_available {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::Unsupported,
                    "Extended attributes not supported"
                ));
            }
            
            let path_cstr = CString::new(path.to_string_lossy().as_ref())?;
            let name_cstr = CString::new(name)?;
            
            let result = unsafe {
                libc::setxattr(
                    path_cstr.as_ptr(),
                    name_cstr.as_ptr(),
                    value.as_ptr() as *const libc::c_void,
                    value.len(),
                    0, // position
                    libc::XATTR_NOFOLLOW
                )
            };
            
            if result < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(())
            }
        }
        
        // ... other methods delegated to base or macOS-specific implementations
    }
}
```

### Unified Platform Interface

#### Platform Factory and Selection

```rust
use std::sync::Arc;

pub trait PlatformFactory {
    fn create_filesystem_ops() -> Arc<dyn FileSystemOps<Error = std::io::Error>>;
    fn platform_name() -> &'static str;
    fn supported_features() -> Vec<&'static str>;
}

#[cfg(target_os = "linux")]
pub struct LinuxPlatformFactory;

#[cfg(target_os = "linux")]
impl PlatformFactory for LinuxPlatformFactory {
    fn create_filesystem_ops() -> Arc<dyn FileSystemOps<Error = std::io::Error>> {
        Arc::new(linux::LinuxFileSystemOps::new())
    }
    
    fn platform_name() -> &'static str {
        "Linux"
    }
    
    fn supported_features() -> Vec<&'static str> {
        let mut features = vec!["basic_ops", "xattr"];
        let caps = get_platform_capabilities();
        
        if caps.splice_available {
            features.push("splice");
        }
        if caps.sendfile_available {
            features.push("sendfile");
        }
        if caps.copy_file_range_available {
            features.push("copy_file_range");
        }
        
        features
    }
}

#[cfg(target_os = "macos")]
pub struct MacOSPlatformFactory;

#[cfg(target_os = "macos")]
impl PlatformFactory for MacOSPlatformFactory {
    fn create_filesystem_ops() -> Arc<dyn FileSystemOps<Error = std::io::Error>> {
        Arc::new(macos::MacOSFileSystemOps::new())
    }
    
    fn platform_name() -> &'static str {
        "macOS"
    }
    
    fn supported_features() -> Vec<&'static str> {
        let mut features = vec!["basic_ops", "xattr"];
        let caps = get_platform_capabilities();
        
        if caps.clonefile_available {
            features.push("clonefile");
        }
        if caps.sendfile_available {
            features.push("sendfile");
        }
        
        features
    }
}

// Default factory for unsupported platforms
pub struct DefaultPlatformFactory;

impl PlatformFactory for DefaultPlatformFactory {
    fn create_filesystem_ops() -> Arc<dyn FileSystemOps<Error = std::io::Error>> {
        Arc::new(StdFileSystemOps)
    }
    
    fn platform_name() -> &'static str {
        "Generic Unix"
    }
    
    fn supported_features() -> Vec<&'static str> {
        vec!["basic_ops"]
    }
}

// Platform selection at compile time
#[cfg(target_os = "linux")]
pub type CurrentPlatform = LinuxPlatformFactory;

#[cfg(target_os = "macos")]
pub type CurrentPlatform = MacOSPlatformFactory;

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
pub type CurrentPlatform = DefaultPlatformFactory;

// Convenience function for creating platform-specific filesystem ops
pub fn create_platform_filesystem() -> Arc<dyn FileSystemOps<Error = std::io::Error>> {
    CurrentPlatform::create_filesystem_ops()
}

// Platform information
pub fn get_platform_info() -> PlatformInfo {
    PlatformInfo {
        name: CurrentPlatform::platform_name().to_string(),
        features: CurrentPlatform::supported_features()
            .into_iter()
            .map(|s| s.to_string())
            .collect(),
        capabilities: get_platform_capabilities().clone(),
    }
}

#[derive(Debug, Clone)]
pub struct PlatformInfo {
    pub name: String,
    pub features: Vec<String>,
    pub capabilities: PlatformCapabilities,
}
```

### Performance Optimization Layer

#### Platform-Aware Buffer Management

```rust
use std::sync::Arc;

pub struct PlatformBuffer {
    data: Vec<u8>,
    alignment: usize,
    capabilities: &'static PlatformCapabilities,
}

impl PlatformBuffer {
    pub fn new(size: usize) -> Self {
        let capabilities = get_platform_capabilities();
        let alignment = Self::get_optimal_alignment(capabilities);
        
        // Allocate aligned buffer for optimal I/O performance
        let mut data = Vec::with_capacity(size + alignment);
        unsafe {
            let ptr = data.as_mut_ptr();
            let aligned_ptr = Self::align_pointer(ptr, alignment);
            let offset = aligned_ptr as usize - ptr as usize;
            data.set_len(size + offset);
        }
        
        Self {
            data,
            alignment,
            capabilities,
        }
    }
    
    fn get_optimal_alignment(capabilities: &PlatformCapabilities) -> usize {
        // Use page size for direct I/O on most platforms
        #[cfg(target_os = "linux")]
        {
            if capabilities.splice_available {
                4096 // Page alignment for splice
            } else {
                512 // Sector alignment
            }
        }
        
        #[cfg(target_os = "macos")]
        {
            4096 // Page alignment for copyfile
        }
        
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        {
            4096 // Default page alignment
        }
    }
    
    fn align_pointer(ptr: *mut u8, alignment: usize) -> *mut u8 {
        let addr = ptr as usize;
        let aligned_addr = (addr + alignment - 1) & !(alignment - 1);
        aligned_addr as *mut u8
    }
    
    pub fn as_slice(&self) -> &[u8] {
        &self.data
    }
    
    pub fn as_mut_slice(&mut self) -> &mut [u8] {
        &mut self.data
    }
    
    pub fn is_aligned(&self) -> bool {
        (self.data.as_ptr() as usize) % self.alignment == 0
    }
}

// Platform-aware I/O operations
pub struct PlatformIO {
    fs_ops: Arc<dyn FileSystemOps<Error = std::io::Error>>,
    capabilities: &'static PlatformCapabilities,
}

impl PlatformIO {
    pub fn new() -> Self {
        Self {
            fs_ops: create_platform_filesystem(),
            capabilities: get_platform_capabilities(),
        }
    }
    
    pub fn copy_file_optimized(&self, src: &Path, dst: &Path) -> Result<u64, std::io::Error> {
        // Use the most efficient copy method available
        if self.capabilities.clonefile_available {
            // CoW copy on macOS
            self.fs_ops.copy_file_fast(src, dst)?;
            let stat = self.fs_ops.stat(src)?;
            Ok(stat.size)
        } else if self.capabilities.copy_file_range_available {
            // Zero-copy on Linux
            let src_fd = self.fs_ops.open(src, libc::O_RDONLY, 0)?;
            let dst_fd = self.fs_ops.open(dst, libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC, 0o644)?;
            let stat = self.fs_ops.fstat(src_fd)?;
            let copied = self.fs_ops.copy_file_range(src_fd, dst_fd, stat.size)?;
            self.fs_ops.close(src_fd)?;
            self.fs_ops.close(dst_fd)?;
            Ok(copied)
        } else {
            // Fallback to standard copy
            self.fs_ops.copy_file_fast(src, dst)?;
            let stat = self.fs_ops.stat(src)?;
            Ok(stat.size)
        }
    }
    
    pub fn read_file_optimized(&self, path: &Path) -> Result<Vec<u8>, std::io::Error> {
        let stat = self.fs_ops.stat(path)?;
        let mut buffer = PlatformBuffer::new(stat.size as usize);
        
        let fd = self.fs_ops.open(path, libc::O_RDONLY, 0)?;
        let bytes_read = self.fs_ops.read(fd, buffer.as_mut_slice(), 0)?;
        self.fs_ops.close(fd)?;
        
        buffer.data.truncate(bytes_read);
        Ok(buffer.data)
    }
    
    pub fn write_file_optimized(&self, path: &Path, data: &[u8]) -> Result<(), std::io::Error> {
        let fd = self.fs_ops.open(path, libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC, 0o644)?;
        
        let mut written = 0;
        while written < data.len() {
            let chunk_size = (data.len() - written).min(self.get_optimal_chunk_size());
            let bytes_written = self.fs_ops.write(fd, &data[written..written + chunk_size], written as u64)?;
            written += bytes_written;
        }
        
        self.fs_ops.fsync(fd)?;
        self.fs_ops.close(fd)?;
        Ok(())
    }
    
    fn get_optimal_chunk_size(&self) -> usize {
        #[cfg(target_os = "linux")]
        {
            if self.capabilities.splice_available {
                64 * 1024 // 64KB for splice
            } else {
                32 * 1024 // 32KB default
            }
        }
        
        #[cfg(target_os = "macos")]
        {
            64 * 1024 // 64KB for macOS
        }
        
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        {
            32 * 1024 // 32KB default
        }
    }
}

// Global platform I/O instance
lazy_static::lazy_static! {
    pub static ref PLATFORM_IO: PlatformIO = PlatformIO::new();
}
```

This comprehensive platform abstraction layer provides:

1. **Compile-time platform detection** with feature flags
2. **Runtime capability detection** for dynamic optimization selection
3. **Cross-platform filesystem operations** with unified interface
4. **Platform-specific optimizations** (Linux splice/copy_file_range, macOS clonefile/copyfile)
5. **Extended attributes support** with platform-specific implementations
6. **Unified factory pattern** for platform selection
7. **Performance-optimized I/O operations** with platform-aware buffer management
8. **Fallback mechanisms** for unsupported operations

The design allows mergerfs to leverage the best available filesystem features on each platform while maintaining a consistent API and graceful degradation on platforms with fewer features.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content":"Create policy engine implementation guide for Rust","status":"completed","priority":"high","id":"1"},{"content":"Create thread safety and concurrency patterns guide","status":"completed","priority":"high","id":"2"},{"content":"Create error handling system design guide","status":"completed","priority":"high","id":"3"},{"content":"Create configuration system implementation guide","status":"completed","priority":"medium","id":"4"},{"content":"Create memory management and data structures guide","status":"completed","priority":"medium","id":"5"},{"content":"Create platform abstraction layer guide","status":"completed","priority":"medium","id":"6"},{"content":"Create FUSE integration patterns guide","status":"pending","priority":"medium","id":"7"},{"content":"Create testing and validation strategy guide","status":"pending","priority":"low","id":"8"}]