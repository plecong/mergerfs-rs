#!/usr/bin/env python3
"""
Debug test to check if MFS policy works.
"""

import time
from pathlib import Path
from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState

def test_mfs_policy():
    """Test if MFS policy selects branch with most free space."""
    manager = FuseManager()
    fs_state = FileSystemState()
    
    # Create branches and mountpoint
    branches = manager.create_temp_dirs(3)
    mountpoint = manager.create_temp_mountpoint()
    
    print(f"Branches: {branches}")
    print(f"Mountpoint: {mountpoint}")
    
    # Pre-populate first branch with a large file
    print("\nPre-populating branch 0 with large file...")
    fs_state.create_file_with_size(branches[0] / "large_file.dat", 5000)
    
    config = FuseConfig(policy="mfs", branches=branches, mountpoint=mountpoint)
    
    try:
        process = manager.mount(config)
        
        # Wait a bit for mount to stabilize
        time.sleep(0.5)
        
        print(f"\nProcess running: {process.poll() is None}")
        
        # List the mount
        print(f"\nListing mountpoint:")
        try:
            items = list(mountpoint.iterdir())
            print(f"Items in mount: {items}")
        except Exception as e:
            print(f"Error listing mount: {e}")
        
        # Write a file through the mount
        test_file = mountpoint / "mfs_test.txt"
        test_file.write_text("MFS test content")
        
        print(f"\nFile written through mount: {test_file}")
        print(f"File exists in mount: {test_file.exists()}")
        print(f"Content: {test_file.read_text()}")
        
        # Check if file appears in any branch
        print("\nChecking branches:")
        for i, branch in enumerate(branches):
            branch_file = branch / "mfs_test.txt"
            exists = branch_file.exists()
            print(f"Branch {i}: {branch_file} exists = {exists}")
            if exists:
                print(f"  Content: {branch_file.read_text()}")
        
        # Try with sync
        import os
        os.sync()
        time.sleep(0.5)
        
        print("\nAfter sync:")
        for i, branch in enumerate(branches):
            branch_file = branch / "mfs_test.txt"
            exists = branch_file.exists()
            print(f"Branch {i}: exists = {exists}")
            if exists:
                print(f"  MFS correctly selected branch {i} (not branch 0 with large file)")
            
    finally:
        manager.unmount(mountpoint)
        manager.cleanup()

if __name__ == "__main__":
    test_mfs_policy()