#!/usr/bin/env python3
"""
Test to demonstrate improved timing diagnostics for FUSE operations.
"""

import os
import time
from pathlib import Path
from lib.fuse_manager import FuseManager, FuseConfig
from lib.timing_utils import TimingAnalyzer


def test_timing_diagnostics():
    """Test FUSE operations with timing diagnostics."""
    # Enable debug logging for detailed timing
    os.environ['RUST_LOG'] = 'debug'
    os.environ['FUSE_DEBUG_LOGS'] = '1'
    
    manager = FuseManager()
    analyzer = TimingAnalyzer()
    
    # Create branches and mountpoint
    branches = manager.create_temp_dirs(3)
    mountpoint = manager.create_temp_mountpoint()
    
    print(f"Branches: {branches}")
    print(f"Mountpoint: {mountpoint}")
    
    config = FuseConfig(policy="mfs", branches=branches, mountpoint=mountpoint)
    
    try:
        print("\n=== Mount Timing ===")
        mount_start = time.time()
        process = manager.mount(config)
        mount_time = time.time() - mount_start
        print(f"Total mount time: {mount_time:.3f}s")
        
        # Perform various operations to measure timing
        print("\n=== Operation Timing ===")
        
        # 1. Directory creation
        dir_start = time.time()
        test_dir = mountpoint / "test_dir"
        test_dir.mkdir()
        dir_time = time.time() - dir_start
        print(f"mkdir: {dir_time*1000:.2f}ms")
        
        # 2. File creation
        create_start = time.time()
        test_file = mountpoint / "test_file.txt"
        test_file.write_text("Test content")
        create_time = time.time() - create_start
        print(f"create + write: {create_time*1000:.2f}ms")
        
        # 3. File read
        read_start = time.time()
        content = test_file.read_text()
        read_time = time.time() - read_start
        print(f"read: {read_time*1000:.2f}ms")
        
        # 4. Directory listing
        list_start = time.time()
        items = list(mountpoint.iterdir())
        list_time = time.time() - list_start
        print(f"readdir: {list_time*1000:.2f}ms ({len(items)} items)")
        
        # 5. Stat operation
        stat_start = time.time()
        stat_info = test_file.stat()
        stat_time = time.time() - stat_start
        print(f"stat: {stat_time*1000:.2f}ms")
        
        # 6. Multiple file writes (measure policy overhead)
        print("\n=== Policy Performance (MFS) ===")
        write_times = []
        for i in range(10):
            file_path = mountpoint / f"mfs_test_{i}.txt"
            write_start = time.time()
            file_path.write_text(f"Content {i}")
            write_time = time.time() - write_start
            write_times.append(write_time * 1000)
            
        avg_write = sum(write_times) / len(write_times)
        min_write = min(write_times)
        max_write = max(write_times)
        print(f"File writes: avg={avg_write:.2f}ms, min={min_write:.2f}ms, max={max_write:.2f}ms")
        
        # Check branch distribution
        print("\n=== Branch Distribution ===")
        for i, branch in enumerate(branches):
            files = list(branch.glob("mfs_test_*.txt"))
            print(f"Branch {i}: {len(files)} files")
            
    finally:
        print("\n=== Unmount Timing ===")
        unmount_start = time.time()
        manager.unmount(mountpoint)
        unmount_time = time.time() - unmount_start
        print(f"Unmount time: {unmount_time:.3f}s")
        
        manager.cleanup()


if __name__ == "__main__":
    test_timing_diagnostics()