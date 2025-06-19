#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::*;
    use crate::branch::{Branch, BranchMode};
    use crate::file_ops::FileManager;
    use crate::policy::create::FirstFoundCreatePolicy;
    use crate::config::{Config, ConfigRef};
    use crate::config_manager::ConfigManager;
    use crate::inode::InodeCalc;
    use crate::fuse_fs::MergerFS;
    use std::sync::Arc;
    use std::path::Path;
    use parking_lot::RwLock;
    use tempfile::TempDir;
    use std::fs;

    fn setup_with_inode_calc(mode: InodeCalc) -> (TempDir, TempDir, Arc<MergerFS>) {
        let branch1 = TempDir::new().unwrap();
        let branch2 = TempDir::new().unwrap();
        
        let branches = vec![
            Arc::new(Branch::new(branch1.path().to_path_buf(), BranchMode::ReadWrite)),
            Arc::new(Branch::new(branch2.path().to_path_buf(), BranchMode::ReadWrite)),
        ];
        
        let file_manager = FileManager::new(
            branches,
            Box::new(FirstFoundCreatePolicy::new()),
        );
        
        let merger_fs = Arc::new(MergerFS::new(file_manager));
        
        // Set the inode calculation mode
        {
            let mut config = merger_fs.config_manager.config().write();
            config.inodecalc = mode;
        }
        
        (branch1, branch2, merger_fs)
    }

    #[test]
    fn test_hard_links_share_inodes_with_devino_hash() {
        let (_branch1, _branch2, merger_fs) = setup_with_inode_calc(InodeCalc::DevinoHash);
        
        // Create a file and a hard link to it
        let file_path = Path::new("/test.txt");
        let link_path = Path::new("/link.txt");
        
        // Create the original file
        merger_fs.file_manager.create_file(file_path, b"test content").unwrap();
        
        // Create a hard link
        merger_fs.file_manager.create_hard_link(file_path, link_path).unwrap();
        
        // Get attributes for both
        let file_attr = merger_fs.create_file_attr(file_path).unwrap();
        let link_attr = merger_fs.create_file_attr(link_path).unwrap();
        
        // With devino-hash, they should have the same inode
        assert_eq!(file_attr.ino, link_attr.ino);
        assert_eq!(file_attr.nlink, 2);
        assert_eq!(link_attr.nlink, 2);
    }
    
    #[test]
    fn test_hard_links_different_inodes_with_path_hash() {
        let (_branch1, _branch2, merger_fs) = setup_with_inode_calc(InodeCalc::PathHash);
        
        // Create a file and a hard link to it
        let file_path = Path::new("/test.txt");
        let link_path = Path::new("/link.txt");
        
        // Create the original file
        merger_fs.file_manager.create_file(file_path, b"test content").unwrap();
        
        // Create a hard link
        merger_fs.file_manager.create_hard_link(file_path, link_path).unwrap();
        
        // Get attributes for both
        let file_attr = merger_fs.create_file_attr(file_path).unwrap();
        let link_attr = merger_fs.create_file_attr(link_path).unwrap();
        
        // With path-hash, they should have different inodes
        assert_ne!(file_attr.ino, link_attr.ino);
        // But still share nlink count
        assert_eq!(file_attr.nlink, 2);
        assert_eq!(link_attr.nlink, 2);
    }
    
    #[test]
    fn test_passthrough_mode() {
        let (_branch1, _branch2, merger_fs) = setup_with_inode_calc(InodeCalc::Passthrough);
        
        // Create a file
        let file_path = Path::new("/test.txt");
        merger_fs.file_manager.create_file(file_path, b"test content").unwrap();
        
        // Get the underlying inode
        let (branch, metadata) = merger_fs.file_manager.find_file_with_metadata(file_path).unwrap();
        let full_path = branch.full_path(file_path);
        
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let original_ino = metadata.ino();
            
            let file_attr = merger_fs.create_file_attr(file_path).unwrap();
            
            // With passthrough, the inode should be the same as the underlying filesystem
            assert_eq!(file_attr.ino, original_ino);
        }
    }
    
    #[test]
    fn test_hybrid_hash_directory_vs_file() {
        let (_branch1, _branch2, merger_fs) = setup_with_inode_calc(InodeCalc::HybridHash);
        
        // Create a directory and a file
        let dir_path = Path::new("/testdir");
        let file_path = Path::new("/testfile.txt");
        
        merger_fs.file_manager.create_directory(dir_path).unwrap();
        merger_fs.file_manager.create_file(file_path, b"test").unwrap();
        
        // Get attributes
        let dir_attr = merger_fs.create_file_attr(dir_path).unwrap();
        let file_attr = merger_fs.create_file_attr(file_path).unwrap();
        
        // For the same branch and original inode, check that directory uses path hash
        // and file uses devino hash. We can't directly verify this, but we can at least
        // check that they have different inodes
        assert_ne!(dir_attr.ino, file_attr.ino);
    }
    
    #[test]
    fn test_inode_consistency_across_operations() {
        let (_branch1, _branch2, merger_fs) = setup_with_inode_calc(InodeCalc::DevinoHash);
        
        // Create a file
        let file_path = Path::new("/test.txt");
        merger_fs.file_manager.create_file(file_path, b"test content").unwrap();
        
        // Get initial inode
        let initial_attr = merger_fs.create_file_attr(file_path).unwrap();
        let initial_ino = initial_attr.ino;
        
        // Modify the file
        merger_fs.file_manager.write_to_file(file_path, 0, b"modified").unwrap();
        
        // Get inode after modification
        let after_write_attr = merger_fs.create_file_attr(file_path).unwrap();
        
        // Inode should remain the same
        assert_eq!(initial_ino, after_write_attr.ino);
        
        // Even after metadata operations
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let perms = std::fs::Permissions::from_mode(0o755);
            let (branch, _) = merger_fs.file_manager.find_file_with_metadata(file_path).unwrap();
            fs::set_permissions(branch.full_path(file_path), perms).unwrap();
        }
        
        let after_chmod_attr = merger_fs.create_file_attr(file_path).unwrap();
        assert_eq!(initial_ino, after_chmod_attr.ino);
    }
    
    #[test]
    fn test_cross_branch_file_same_path() {
        let (branch1, branch2, merger_fs) = setup_with_inode_calc(InodeCalc::DevinoHash);
        
        // Create the same file in both branches directly
        let file_path = Path::new("test.txt");
        fs::write(branch1.path().join(file_path), "branch1 content").unwrap();
        fs::write(branch2.path().join(file_path), "branch2 content").unwrap();
        
        // The file manager will find the first one (branch1)
        let attr = merger_fs.create_file_attr(&Path::new("/test.txt")).unwrap();
        
        // Now remove branch1's file
        fs::remove_file(branch1.path().join(file_path)).unwrap();
        
        // Get attributes again - should find branch2's file
        let attr2 = merger_fs.create_file_attr(&Path::new("/test.txt")).unwrap();
        
        // With devino-hash, these should have different inodes because they're 
        // from different branches (different branch paths in the hash)
        assert_ne!(attr.ino, attr2.ino);
    }
}