#!/usr/bin/env python3
"""
Debug test to check if files written through FUSE mount appear in branches.
"""

import time
from pathlib import Path
from lib.fuse_manager import FuseManager, FuseConfig

def test_write_through_mount():
    """Test if files written through mount appear in branches."""
    manager = FuseManager()
    
    # Create branches and mountpoint
    branches = manager.create_temp_dirs(3)
    mountpoint = manager.create_temp_mountpoint()
    
    print(f"Branches: {branches}")
    print(f"Mountpoint: {mountpoint}")
    
    config = FuseConfig(policy="ff", branches=branches, mountpoint=mountpoint)
    
    try:
        process = manager.mount(config)
        
        # Check process status
        print(f"\nProcess running: {process.poll() is None}")
        
        # Wait a bit for mount to stabilize
        time.sleep(0.5)
        
        # List the mount to see if it's working
        print(f"\nListing mountpoint before write:")
        try:
            items = list(mountpoint.iterdir())
            print(f"Items in mount: {items}")
        except Exception as e:
            print(f"Error listing mount: {e}")
        
        # Write a file through the mount
        test_file = mountpoint / "test_write.txt"
        test_file.write_text("Test content through FUSE")
        
        print(f"\nFile written through mount: {test_file}")
        print(f"File exists in mount: {test_file.exists()}")
        print(f"Content: {test_file.read_text()}")
        
        # Check if file appears in any branch
        print("\nChecking branches:")
        for i, branch in enumerate(branches):
            branch_file = branch / "test_write.txt"
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
            branch_file = branch / "test_write.txt"
            exists = branch_file.exists()
            print(f"Branch {i}: exists = {exists}")
            
    finally:
        manager.unmount(mountpoint)
        manager.cleanup()

if __name__ == "__main__":
    test_write_through_mount()