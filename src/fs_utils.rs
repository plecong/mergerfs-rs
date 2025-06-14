use std::fs;
use std::io;
use std::path::Path;
use filetime::{set_file_times, FileTime};

/// Clone a directory path from source to destination, preserving metadata
/// 
/// This function creates the directory structure at the destination, copying
/// permissions and timestamps from the source directories.
pub fn clone_path(src_base: &Path, dst_base: &Path, relative_path: &Path) -> io::Result<()> {
    // Build the full paths
    let dst_full = dst_base.join(relative_path);
    
    // If destination already exists, we're done
    if dst_full.exists() {
        return Ok(());
    }
    
    // Get all parent components we need to create
    let mut components = Vec::new();
    let mut current = relative_path;
    
    while let Some(parent) = current.parent() {
        if parent.as_os_str().is_empty() {
            break;
        }
        components.push(parent);
        current = parent;
    }
    
    // Create directories from root to leaf
    components.reverse();
    components.push(relative_path);
    
    for component in components {
        let src_dir = src_base.join(component);
        let dst_dir = dst_base.join(component);
        
        if dst_dir.exists() {
            continue;
        }
        
        // Get source metadata
        let src_metadata = match src_dir.metadata() {
            Ok(m) => m,
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                // Source doesn't exist, create with default permissions
                fs::create_dir(&dst_dir)?;
                continue;
            }
            Err(e) => return Err(e),
        };
        
        // Create directory
        fs::create_dir(&dst_dir)?;
        
        // Copy permissions
        let permissions = src_metadata.permissions();
        fs::set_permissions(&dst_dir, permissions)?;
        
        // Copy timestamps
        if let (Ok(accessed), Ok(modified)) = (src_metadata.accessed(), src_metadata.modified()) {
            let atime = FileTime::from_system_time(accessed);
            let mtime = FileTime::from_system_time(modified);
            let _ = set_file_times(&dst_dir, atime, mtime);
        }
        
        // Note: Extended attributes (xattr) and ownership changes would require
        // additional dependencies and potentially elevated privileges
    }
    
    Ok(())
}

/// Clone a directory path ensuring the parent directory exists
/// Returns true if the parent was created, false if it already existed
pub fn ensure_parent_cloned(src_base: &Path, dst_base: &Path, file_path: &Path) -> io::Result<bool> {
    if let Some(parent) = file_path.parent() {
        if parent.as_os_str().is_empty() {
            return Ok(false);
        }
        
        let dst_parent = dst_base.join(parent);
        if !dst_parent.exists() {
            clone_path(src_base, dst_base, parent)?;
            Ok(true)
        } else {
            Ok(false)
        }
    } else {
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use std::os::unix::fs::PermissionsExt;
    
    #[test]
    fn test_clone_simple_path() {
        let src_temp = TempDir::new().unwrap();
        let dst_temp = TempDir::new().unwrap();
        
        let src_base = src_temp.path();
        let dst_base = dst_temp.path();
        
        // Create source directory with specific permissions
        let src_dir = src_base.join("test_dir");
        fs::create_dir(&src_dir).unwrap();
        
        let mut perms = fs::metadata(&src_dir).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&src_dir, perms).unwrap();
        
        // Clone the path
        clone_path(src_base, dst_base, Path::new("test_dir")).unwrap();
        
        // Verify destination exists with same permissions
        let dst_dir = dst_base.join("test_dir");
        assert!(dst_dir.exists());
        assert!(dst_dir.is_dir());
        
        let dst_perms = fs::metadata(&dst_dir).unwrap().permissions();
        assert_eq!(dst_perms.mode() & 0o777, 0o755);
    }
    
    #[test]
    fn test_clone_nested_path() {
        let src_temp = TempDir::new().unwrap();
        let dst_temp = TempDir::new().unwrap();
        
        let src_base = src_temp.path();
        let dst_base = dst_temp.path();
        
        // Create nested source structure
        let nested_path = Path::new("a/b/c");
        let src_nested = src_base.join(nested_path);
        fs::create_dir_all(&src_nested).unwrap();
        
        // Set different permissions at each level
        let mut perms = fs::metadata(src_base.join("a")).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(src_base.join("a"), perms.clone()).unwrap();
        
        perms.set_mode(0o750);
        fs::set_permissions(src_base.join("a/b"), perms.clone()).unwrap();
        
        perms.set_mode(0o700);
        fs::set_permissions(src_base.join("a/b/c"), perms).unwrap();
        
        // Clone the nested path
        clone_path(src_base, dst_base, nested_path).unwrap();
        
        // Verify all levels exist with correct permissions
        assert!(dst_base.join("a").exists());
        assert!(dst_base.join("a/b").exists());
        assert!(dst_base.join("a/b/c").exists());
        
        assert_eq!(fs::metadata(dst_base.join("a")).unwrap().permissions().mode() & 0o777, 0o755);
        assert_eq!(fs::metadata(dst_base.join("a/b")).unwrap().permissions().mode() & 0o777, 0o750);
        assert_eq!(fs::metadata(dst_base.join("a/b/c")).unwrap().permissions().mode() & 0o777, 0o700);
    }
    
    #[test]
    fn test_ensure_parent_cloned() {
        let src_temp = TempDir::new().unwrap();
        let dst_temp = TempDir::new().unwrap();
        
        let src_base = src_temp.path();
        let dst_base = dst_temp.path();
        
        // Create source directory
        fs::create_dir_all(src_base.join("parent/subdir")).unwrap();
        
        // Ensure parent for a file path
        let created = ensure_parent_cloned(src_base, dst_base, Path::new("parent/subdir/file.txt")).unwrap();
        assert!(created);
        assert!(dst_base.join("parent").exists());
        assert!(dst_base.join("parent/subdir").exists());
        
        // Second call should return false (already exists)
        let created = ensure_parent_cloned(src_base, dst_base, Path::new("parent/subdir/file2.txt")).unwrap();
        assert!(!created);
    }
}