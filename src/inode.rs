use std::path::Path;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

/// Inode calculation algorithms
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum InodeCalc {
    /// Use the original inode from the underlying filesystem
    Passthrough,
    /// Hash the FUSE path (virtual path) to generate inode
    PathHash,
    /// 32-bit version of path-hash
    PathHash32,
    /// Hash the branch path + original inode (device+inode)
    DevinoHash,
    /// 32-bit version of devino-hash
    DevinoHash32,
    /// Use path-hash for directories, devino-hash for files (default)
    HybridHash,
    /// 32-bit version of hybrid-hash
    HybridHash32,
}

impl Default for InodeCalc {
    fn default() -> Self {
        InodeCalc::HybridHash
    }
}

impl InodeCalc {
    /// Parse inode calculation mode from string
    pub fn from_str(s: &str) -> Result<Self, String> {
        match s {
            "passthrough" => Ok(InodeCalc::Passthrough),
            "path-hash" => Ok(InodeCalc::PathHash),
            "path-hash32" => Ok(InodeCalc::PathHash32),
            "devino-hash" => Ok(InodeCalc::DevinoHash),
            "devino-hash32" => Ok(InodeCalc::DevinoHash32),
            "hybrid-hash" => Ok(InodeCalc::HybridHash),
            "hybrid-hash32" => Ok(InodeCalc::HybridHash32),
            _ => Err(format!("Invalid inode calculation mode: {}", s)),
        }
    }

    /// Convert to string representation
    pub fn to_string(&self) -> &'static str {
        match self {
            InodeCalc::Passthrough => "passthrough",
            InodeCalc::PathHash => "path-hash",
            InodeCalc::PathHash32 => "path-hash32",
            InodeCalc::DevinoHash => "devino-hash",
            InodeCalc::DevinoHash32 => "devino-hash32",
            InodeCalc::HybridHash => "hybrid-hash",
            InodeCalc::HybridHash32 => "hybrid-hash32",
        }
    }

    /// Calculate inode based on the selected algorithm
    pub fn calc(&self, branch_path: &Path, fuse_path: &Path, mode: u32, original_ino: u64) -> u64 {
        match self {
            InodeCalc::Passthrough => passthrough(branch_path, fuse_path, mode, original_ino),
            InodeCalc::PathHash => path_hash(branch_path, fuse_path, mode, original_ino),
            InodeCalc::PathHash32 => path_hash32(branch_path, fuse_path, mode, original_ino),
            InodeCalc::DevinoHash => devino_hash(branch_path, fuse_path, mode, original_ino),
            InodeCalc::DevinoHash32 => devino_hash32(branch_path, fuse_path, mode, original_ino),
            InodeCalc::HybridHash => hybrid_hash(branch_path, fuse_path, mode, original_ino),
            InodeCalc::HybridHash32 => hybrid_hash32(branch_path, fuse_path, mode, original_ino),
        }
    }
}

/// Convert 64-bit hash to 32-bit
fn h64_to_h32(h: u64) -> u64 {
    let h32 = (h ^ (h >> 32)) as u32;
    let h32 = h32.wrapping_mul(0x9E3779B9);
    h32 as u64
}

/// Simple hash function for paths and data
/// In production, we might want to use a faster hash like xxhash or rapidhash
fn hash_data<T: Hash>(data: T) -> u64 {
    let mut hasher = DefaultHasher::new();
    data.hash(&mut hasher);
    hasher.finish()
}

/// Combine two hash values
fn hash_combine(seed: u64, value: u64) -> u64 {
    // Based on boost::hash_combine
    seed ^ (value.wrapping_add(0x9e3779b9).wrapping_add(seed << 6).wrapping_add(seed >> 2))
}

/// Passthrough - use original inode
fn passthrough(_branch_path: &Path, _fuse_path: &Path, _mode: u32, original_ino: u64) -> u64 {
    original_ino
}

/// Hash the FUSE path
fn path_hash(_branch_path: &Path, fuse_path: &Path, _mode: u32, _original_ino: u64) -> u64 {
    hash_data(fuse_path.to_string_lossy().as_bytes())
}

/// 32-bit version of path_hash
fn path_hash32(branch_path: &Path, fuse_path: &Path, mode: u32, original_ino: u64) -> u64 {
    h64_to_h32(path_hash(branch_path, fuse_path, mode, original_ino))
}

/// Hash the branch path + original inode
fn devino_hash(branch_path: &Path, _fuse_path: &Path, _mode: u32, original_ino: u64) -> u64 {
    let branch_hash = hash_data(branch_path.to_string_lossy().as_bytes());
    hash_combine(branch_hash, original_ino)
}

/// 32-bit version of devino_hash
fn devino_hash32(branch_path: &Path, fuse_path: &Path, mode: u32, original_ino: u64) -> u64 {
    h64_to_h32(devino_hash(branch_path, fuse_path, mode, original_ino))
}

/// Hybrid hash - use path hash for directories, devino hash for files
fn hybrid_hash(branch_path: &Path, fuse_path: &Path, mode: u32, original_ino: u64) -> u64 {
    // Check if it's a directory (S_IFDIR = 0o040000)
    if mode & 0o040000 != 0 {
        path_hash(branch_path, fuse_path, mode, original_ino)
    } else {
        devino_hash(branch_path, fuse_path, mode, original_ino)
    }
}

/// 32-bit version of hybrid_hash
fn hybrid_hash32(branch_path: &Path, fuse_path: &Path, mode: u32, original_ino: u64) -> u64 {
    h64_to_h32(hybrid_hash(branch_path, fuse_path, mode, original_ino))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_inode_calc_from_str() {
        assert_eq!(InodeCalc::from_str("passthrough").unwrap(), InodeCalc::Passthrough);
        assert_eq!(InodeCalc::from_str("path-hash").unwrap(), InodeCalc::PathHash);
        assert_eq!(InodeCalc::from_str("path-hash32").unwrap(), InodeCalc::PathHash32);
        assert_eq!(InodeCalc::from_str("devino-hash").unwrap(), InodeCalc::DevinoHash);
        assert_eq!(InodeCalc::from_str("devino-hash32").unwrap(), InodeCalc::DevinoHash32);
        assert_eq!(InodeCalc::from_str("hybrid-hash").unwrap(), InodeCalc::HybridHash);
        assert_eq!(InodeCalc::from_str("hybrid-hash32").unwrap(), InodeCalc::HybridHash32);
        assert!(InodeCalc::from_str("invalid").is_err());
    }

    #[test]
    fn test_inode_calc_to_string() {
        assert_eq!(InodeCalc::Passthrough.to_string(), "passthrough");
        assert_eq!(InodeCalc::PathHash.to_string(), "path-hash");
        assert_eq!(InodeCalc::PathHash32.to_string(), "path-hash32");
        assert_eq!(InodeCalc::DevinoHash.to_string(), "devino-hash");
        assert_eq!(InodeCalc::DevinoHash32.to_string(), "devino-hash32");
        assert_eq!(InodeCalc::HybridHash.to_string(), "hybrid-hash");
        assert_eq!(InodeCalc::HybridHash32.to_string(), "hybrid-hash32");
    }

    #[test]
    fn test_passthrough() {
        let branch = PathBuf::from("/mnt/disk1");
        let fuse_path = PathBuf::from("/test.txt");
        let mode = 0o100644; // Regular file
        let original_ino = 12345;

        let result = InodeCalc::Passthrough.calc(&branch, &fuse_path, mode, original_ino);
        assert_eq!(result, original_ino);
    }

    #[test]
    fn test_path_hash_consistency() {
        let branch1 = PathBuf::from("/mnt/disk1");
        let branch2 = PathBuf::from("/mnt/disk2");
        let fuse_path = PathBuf::from("/test.txt");
        let mode = 0o100644;

        // Path hash should be the same regardless of branch or original inode
        let result1 = InodeCalc::PathHash.calc(&branch1, &fuse_path, mode, 111);
        let result2 = InodeCalc::PathHash.calc(&branch2, &fuse_path, mode, 222);
        assert_eq!(result1, result2);
    }

    #[test]
    fn test_devino_hash_different_branches() {
        let branch1 = PathBuf::from("/mnt/disk1");
        let branch2 = PathBuf::from("/mnt/disk2");
        let fuse_path = PathBuf::from("/test.txt");
        let mode = 0o100644;
        let original_ino = 12345;

        // DevIno hash should be different for different branches
        let result1 = InodeCalc::DevinoHash.calc(&branch1, &fuse_path, mode, original_ino);
        let result2 = InodeCalc::DevinoHash.calc(&branch2, &fuse_path, mode, original_ino);
        assert_ne!(result1, result2);
    }

    #[test]
    fn test_devino_hash_same_branch_different_inodes() {
        let branch = PathBuf::from("/mnt/disk1");
        let fuse_path = PathBuf::from("/test.txt");
        let mode = 0o100644;

        // DevIno hash should be different for different original inodes
        let result1 = InodeCalc::DevinoHash.calc(&branch, &fuse_path, mode, 111);
        let result2 = InodeCalc::DevinoHash.calc(&branch, &fuse_path, mode, 222);
        assert_ne!(result1, result2);
    }

    #[test]
    fn test_hybrid_hash_directory_vs_file() {
        let branch = PathBuf::from("/mnt/disk1");
        let dir_path = PathBuf::from("/mydir");
        let file_path = PathBuf::from("/myfile");
        let dir_mode = 0o040755; // Directory
        let file_mode = 0o100644; // Regular file
        let original_ino = 12345;

        // For directories, hybrid should use path hash
        let dir_hybrid = InodeCalc::HybridHash.calc(&branch, &dir_path, dir_mode, original_ino);
        let dir_path_hash = InodeCalc::PathHash.calc(&branch, &dir_path, dir_mode, original_ino);
        assert_eq!(dir_hybrid, dir_path_hash);

        // For files, hybrid should use devino hash
        let file_hybrid = InodeCalc::HybridHash.calc(&branch, &file_path, file_mode, original_ino);
        let file_devino = InodeCalc::DevinoHash.calc(&branch, &file_path, file_mode, original_ino);
        assert_eq!(file_hybrid, file_devino);
    }

    #[test]
    fn test_32bit_variants() {
        let branch = PathBuf::from("/mnt/disk1");
        let fuse_path = PathBuf::from("/test.txt");
        let mode = 0o100644;
        let original_ino = u64::MAX; // Large inode to test 32-bit conversion

        // 32-bit variants should produce values that fit in 32 bits
        let path32 = InodeCalc::PathHash32.calc(&branch, &fuse_path, mode, original_ino);
        let devino32 = InodeCalc::DevinoHash32.calc(&branch, &fuse_path, mode, original_ino);
        let hybrid32 = InodeCalc::HybridHash32.calc(&branch, &fuse_path, mode, original_ino);

        assert!(path32 <= u32::MAX as u64);
        assert!(devino32 <= u32::MAX as u64);
        assert!(hybrid32 <= u32::MAX as u64);
    }

    #[test]
    fn test_hard_link_consistency() {
        // Hard links on the same branch should have the same calculated inode
        let branch = PathBuf::from("/mnt/disk1");
        let link1_path = PathBuf::from("/link1");
        let link2_path = PathBuf::from("/link2");
        let mode = 0o100644;
        let shared_ino = 99999; // Both hard links share this inode on the underlying FS

        // With devino hash, different paths but same branch+inode should give same result
        let link1_devino = InodeCalc::DevinoHash.calc(&branch, &link1_path, mode, shared_ino);
        let link2_devino = InodeCalc::DevinoHash.calc(&branch, &link2_path, mode, shared_ino);
        assert_eq!(link1_devino, link2_devino);

        // With path hash, they would be different
        let link1_path_hash = InodeCalc::PathHash.calc(&branch, &link1_path, mode, shared_ino);
        let link2_path_hash = InodeCalc::PathHash.calc(&branch, &link2_path, mode, shared_ino);
        assert_ne!(link1_path_hash, link2_path_hash);
    }
}