use crate::config_manager::ConfigManager;
use fuser::{FileAttr, FileType, ReplyAttr, ReplyData, ReplyEmpty, ReplyXattr};
use std::ffi::OsStr;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

// Constants
pub const CONTROL_FILE_INO: u64 = u64::MAX; // Special inode for /.mergerfs
const TTL: Duration = Duration::from_secs(1);
const EINVAL: i32 = 22;
const ENOTSUP: i32 = 95;
const EACCES: i32 = 13;
const ERANGE: i32 = 34;

/// Handles all operations related to the .mergerfs control file
pub struct ControlFileHandler {
    config_manager: Arc<ConfigManager>,
}

impl ControlFileHandler {
    pub fn new(config_manager: Arc<ConfigManager>) -> Self {
        Self { config_manager }
    }
    
    /// Check if a path is the control file
    pub fn is_control_file(path: &str) -> bool {
        path == "/.mergerfs"
    }
    
    /// Get attributes for the control file
    pub fn get_attr(&self) -> FileAttr {
        FileAttr {
            ino: CONTROL_FILE_INO,
            size: 0,
            blocks: 0,
            atime: SystemTime::now(),
            mtime: SystemTime::now(),
            ctime: SystemTime::now(),
            crtime: SystemTime::now(),
            kind: FileType::RegularFile,
            perm: 0o444, // Read-only for all
            nlink: 1,
            uid: 0, // Owned by root
            gid: 0,
            rdev: 0,
            flags: 0,
            blksize: 512,
        }
    }
    
    /// Handle getattr for control file
    pub fn handle_getattr(&self, reply: ReplyAttr) {
        let attr = self.get_attr();
        reply.attr(&TTL, &attr);
    }
    
    /// Handle open for control file - returns Ok(()) for success or error code
    pub fn handle_open(&self, flags: i32) -> Result<(), i32> {
        // Control file is always available and read-only
        if flags & 0x03 != 0 {  // O_RDONLY is 0, so check for write flags
            Err(EACCES)
        } else {
            Ok(())
        }
    }
    
    /// Handle read for control file
    pub fn handle_read(&self, reply: ReplyData) {
        // Control file is always empty
        reply.data(&[]);
    }
    
    /// Handle getxattr for control file
    pub fn handle_getxattr(&self, name: &OsStr, size: u32, reply: ReplyXattr) {
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        // Handle config option getxattr
        if name_str.starts_with("user.mergerfs.") {
            let option_name = &name_str["user.mergerfs.".len()..];
            match self.config_manager.get_option(option_name) {
                Ok(value) => {
                    let value_bytes = value.as_bytes();
                    if size == 0 {
                        reply.size(value_bytes.len() as u32);
                    } else if size < value_bytes.len() as u32 {
                        reply.error(ERANGE);
                    } else {
                        reply.data(value_bytes);
                    }
                }
                Err(_) => {
                    reply.error(ENOTSUP);
                }
            }
        } else {
            reply.error(ENOTSUP);
        }
    }
    
    /// Handle setxattr for control file
    pub fn handle_setxattr(&self, name: &OsStr, value: &[u8], reply: ReplyEmpty) {
        let name_str = match name.to_str() {
            Some(s) => s,
            None => {
                reply.error(EINVAL);
                return;
            }
        };
        
        // Handle config option setxattr
        if name_str.starts_with("user.mergerfs.") {
            let option_name = &name_str["user.mergerfs.".len()..];
            let value_str = match std::str::from_utf8(value) {
                Ok(s) => s,
                Err(_) => {
                    reply.error(EINVAL);
                    return;
                }
            };
            
            eprintln!("DEBUG CONTROL FILE: Setting option {} to {}", option_name, value_str);
            match self.config_manager.set_option(option_name, value_str) {
                Ok(()) => {
                    reply.ok();
                }
                Err(e) => {
                    reply.error(e.errno());
                }
            }
        } else {
            reply.error(ENOTSUP);
        }
    }
    
    /// Handle listxattr for control file
    pub fn handle_listxattr(&self, size: u32, reply: ReplyXattr) {
        // List all available config options
        let options = self.config_manager.list_options();
        let mut buffer = Vec::new();
        
        for option in options {
            buffer.extend_from_slice(option.as_bytes());
            buffer.push(0); // null terminator
        }
        
        if size == 0 {
            // Caller wants to know the size
            reply.size(buffer.len() as u32);
        } else if size < buffer.len() as u32 {
            // Buffer too small
            reply.error(ERANGE);
        } else {
            // Return the list
            reply.data(&buffer);
        }
    }
    
    /// Handle removexattr for control file
    pub fn handle_removexattr(&self, reply: ReplyEmpty) {
        // Removing attributes from control file is not supported
        reply.error(ENOTSUP);
    }
    
    /// Handle access for control file
    pub fn handle_access(&self, mask: i32, reply: ReplyEmpty) {
        // Control file is readable for all
        if mask & 2 != 0 || mask & 4 != 0 {
            // Write or execute requested
            reply.error(EACCES);
        } else {
            reply.ok();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;
    
    #[test]
    fn test_is_control_file() {
        assert!(ControlFileHandler::is_control_file("/.mergerfs"));
        assert!(!ControlFileHandler::is_control_file("/mergerfs"));
        assert!(!ControlFileHandler::is_control_file("/.mergerfs2"));
        assert!(!ControlFileHandler::is_control_file("/test/.mergerfs"));
    }
    
    #[test]
    fn test_control_file_attributes() {
        let config = config::create_config();
        let config_manager = ConfigManager::new(config);
        let handler = ControlFileHandler::new(Arc::new(config_manager));
        
        let attr = handler.get_attr();
        assert_eq!(attr.ino, CONTROL_FILE_INO);
        assert_eq!(attr.size, 0);
        assert_eq!(attr.kind, FileType::RegularFile);
        assert_eq!(attr.perm, 0o444);
        assert_eq!(attr.uid, 0);
        assert_eq!(attr.gid, 0);
    }
}