use std::fs;
use std::io;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct DiskSpace {
    pub total: u64,
    pub available: u64,
    pub used: u64,
}

impl DiskSpace {
    /// Get disk space information for a given path
    /// Uses statvfs to get f_bavail for accurate available space calculation
    /// This matches mergerfs behavior which uses f_bavail to respect filesystem reservations
    pub fn for_path(path: &Path) -> Result<DiskSpace, io::Error> {
        // In test mode, check for mock space markers first
        #[cfg(test)]
        {
            if let Ok(space) = crate::test_utils::get_test_disk_space(path) {
                return Ok(space);
            }
        }
        #[cfg(unix)]
        {
            use nix::sys::statvfs::statvfs;
            
            // Use nix crate for portable statvfs support
            let stat = statvfs(path)
                .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;
            
            // Calculate space using f_bavail (available blocks for unprivileged users)
            // This respects filesystem reservations, unlike f_bfree
            // This matches the C++ mergerfs implementation behavior
            let block_size = stat.fragment_size() as u64;
            let total = stat.blocks() as u64 * block_size;
            let available = stat.blocks_available() as u64 * block_size;  // f_bavail
            let free = stat.blocks_free() as u64 * block_size;  // f_bfree
            let used = total.saturating_sub(free);
            
            tracing::trace!(
                "DiskSpace for {:?}: total={}, available={} (f_bavail), free={} (f_bfree), used={}", 
                path, total, available, free, used
            );
            
            Ok(DiskSpace {
                total,
                available,
                used,
            })
        }
        
        #[cfg(not(unix))]
        {
            // Fallback for non-Unix systems
            let _metadata = fs::metadata(path)?;
            let estimated_used = Self::calculate_directory_size(path).unwrap_or(0);
            let total: u64 = 10 * 1024 * 1024 * 1024; // 10GB total
            let available = total.saturating_sub(estimated_used);
            
            Ok(DiskSpace {
                total,
                available,
                used: estimated_used,
            })
        }
    }
    
    /// Calculate the total size of files in a directory (recursive)
    fn calculate_directory_size(path: &Path) -> Result<u64, io::Error> {
        let mut total_size = 0u64;
        
        if path.is_file() {
            return Ok(path.metadata()?.len());
        }
        
        if path.is_dir() {
            for entry in fs::read_dir(path)? {
                let entry = entry?;
                let entry_path = entry.path();
                
                if entry_path.is_file() {
                    total_size += entry.metadata()?.len();
                } else if entry_path.is_dir() {
                    // Recursively calculate subdirectory size
                    total_size += Self::calculate_directory_size(&entry_path).unwrap_or(0);
                }
            }
        }
        
        Ok(total_size)
    }
}