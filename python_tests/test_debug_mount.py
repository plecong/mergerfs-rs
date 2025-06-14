#!/usr/bin/env python3
"""Debug test to check mount behavior."""

import os
import time
import subprocess
from pathlib import Path

def test_manual_mount():
    """Manually test mounting."""
    # Create directories
    branch1 = Path("/tmp/manual_test_branch1")
    branch2 = Path("/tmp/manual_test_branch2")
    mountpoint = Path("/tmp/manual_test_mount")
    
    branch1.mkdir(exist_ok=True)
    branch2.mkdir(exist_ok=True)
    mountpoint.mkdir(exist_ok=True)
    
    # Start mount
    binary = Path(__file__).parent.parent / "target" / "debug" / "mergerfs-rs"
    cmd = [str(binary), str(mountpoint), str(branch1), str(branch2)]
    
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Wait for mount
    time.sleep(2)
    
    # Check directory listing
    print(f"\nDirectory listing of {mountpoint}:")
    for item in mountpoint.iterdir():
        print(f"  {item.name} - exists: {item.exists()}")
    
    # Check control file specifically
    control_file = mountpoint / ".mergerfs"
    print(f"\nControl file {control_file}:")
    print(f"  exists: {control_file.exists()}")
    print(f"  is_file: {control_file.is_file() if control_file.exists() else 'N/A'}")
    
    # Try to stat it
    try:
        stat_info = control_file.stat()
        print(f"  size: {stat_info.st_size}")
        print(f"  mode: {oct(stat_info.st_mode)}")
    except Exception as e:
        print(f"  stat error: {e}")
    
    # Clean up
    process.terminate()
    process.wait()
    
    # Try to clean directories
    for d in [branch1, branch2, mountpoint]:
        try:
            d.rmdir()
        except:
            pass

if __name__ == "__main__":
    test_manual_mount()