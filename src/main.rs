mod branch;
mod config;
mod config_manager;
mod policy;
mod metadata_ops;
mod file_ops;
mod file_handle;
mod xattr;
mod fuse_fs;
mod fs_utils;
mod integration_tests;
mod fuse_integration_tests;
mod directory_ops_tests;
mod rename_ops;

#[cfg(test)]
mod test_utils;
#[cfg(test)]
mod rename_strategy_tests;
#[cfg(test)]
mod rename_minimal_test;
#[cfg(test)]
mod rename_edge_case_tests;
#[cfg(test)]
mod symlink_tests;
#[cfg(test)]
mod link_tests;

use std::env;
use std::path::PathBuf;
use std::sync::Arc;

use branch::{Branch, BranchMode};
use file_ops::FileManager;
use fuse_fs::MergerFS;
use policy::{FirstFoundCreatePolicy, MostFreeSpaceCreatePolicy, LeastFreeSpaceCreatePolicy, RandomCreatePolicy, CreatePolicy};

fn parse_args(args: &[String]) -> (String, PathBuf, Vec<PathBuf>) {
    let mut create_policy = "ff".to_string();
    let mut i = 1;
    
    // Parse options
    while i < args.len() {
        if args[i] == "-o" && i + 1 < args.len() {
            let option = &args[i + 1];
            if let Some(policy_part) = option.strip_prefix("func.create=") {
                create_policy = policy_part.to_string();
            }
            i += 2;
        } else {
            break;
        }
    }
    
    // Remaining arguments should be mountpoint and branches
    if i + 1 >= args.len() {
        eprintln!("Error: Missing mountpoint and branch directories");
        std::process::exit(1);
    }
    
    let mountpoint = PathBuf::from(&args[i]);
    let branch_paths: Vec<PathBuf> = args[i + 1..].iter().map(PathBuf::from).collect();
    
    (create_policy, mountpoint, branch_paths)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    
    if args.len() < 3 {
        println!("mergerfs-rs - Test-driven FUSE union filesystem");
        println!("");
        println!("Usage: {} [options] <mountpoint> <branch1> [branch2] [branch3] ...", args[0]);
        println!("");
        println!("Options:");
        println!("  -o func.create=POLICY    Create policy (ff|mfs|lfs) [default: ff]");
        println!("");
        println!("Create Policies:");
        println!("  ff   - FirstFound: Create files in first writable branch");
        println!("  mfs  - MostFreeSpace: Create files in branch with most free space");
        println!("  lfs  - LeastFreeSpace: Create files in branch with least free space");
        println!("");
        println!("Example:");
        println!("  {} /tmp/merged /tmp/branch1 /tmp/branch2", args[0]);
        println!("  {} -o func.create=mfs /tmp/merged /tmp/branch1 /tmp/branch2", args[0]);
        println!("  {} -o func.create=lfs /tmp/merged /tmp/branch1 /tmp/branch2", args[0]);
        println!("");
        println!("This will mount a union filesystem at /tmp/merged that combines");
        println!("the contents of /tmp/branch1 and /tmp/branch2");
        println!("");
        println!("Features implemented:");
        println!("  - File creation/deletion with configurable policies (ff, mfs, lfs)");
        println!("  - Directory creation/removal with policy support");
        println!("  - File and directory reading from any branch");
        println!("  - Union directory listings (merged view)");
        println!("  - Metadata operations (chmod, chown, utimens) with action policies");
        println!("  - Cross-branch metadata consistency");
        println!("  - Readonly branch support");
        println!("  - Nested directory creation");
        println!("  - FUSE operations: getattr, setattr, open, read, create, write, mkdir, rmdir, unlink, readdir");
        return;
    }

    // Parse command line arguments
    let (create_policy, mountpoint, branch_paths) = parse_args(&args);
    
    let mut branches = Vec::new();
    for branch_path in branch_paths.iter() {
        if !branch_path.exists() {
            eprintln!("Error: Branch directory {} does not exist", branch_path.display());
            std::process::exit(1);
        }
        
        let branch = Arc::new(Branch::new(branch_path.clone(), BranchMode::ReadWrite));
        branches.push(branch);
    }
    
    if branches.is_empty() {
        eprintln!("Error: At least one branch directory is required");
        std::process::exit(1);
    }
    
    // Initialize the filesystem with selected policy
    let (_policy_name, policy): (&str, Box<dyn CreatePolicy>) = match create_policy.as_str() {
        "mfs" => ("MostFreeSpace", Box::new(MostFreeSpaceCreatePolicy::new())),
        "lfs" => ("LeastFreeSpace", Box::new(LeastFreeSpaceCreatePolicy::new())),
        "rand" => ("Random", Box::new(RandomCreatePolicy::new())),
        _ => ("FirstFound", Box::new(FirstFoundCreatePolicy::new())),
    };
    
    let file_manager = FileManager::new(branches, policy);
    let fs = MergerFS::new(file_manager);
    
    // Mount the filesystem
    let options = vec![
        fuser::MountOption::RW,
        fuser::MountOption::FSName("mergerfs-rs".to_string()),
        fuser::MountOption::AutoUnmount,
    ];
    
    match fuser::mount2(fs, &mountpoint, &options) {
        Ok(()) => {
            // Filesystem unmounted successfully
        }
        Err(e) => {
            eprintln!("Mount failed: {}", e);
            std::process::exit(1);
        }
    }
}
