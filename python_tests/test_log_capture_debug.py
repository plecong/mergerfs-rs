#!/usr/bin/env python3
"""Debug log capture issues."""

import os
import time
import subprocess
import tempfile
from pathlib import Path
from lib.simple_trace import SimpleTraceMonitor


def test_simple_capture():
    """Test basic log capture."""
    # Create test directories
    mountpoint = Path(tempfile.mkdtemp(prefix="log_test_mount_"))
    branch1 = Path(tempfile.mkdtemp(prefix="log_test_branch1_"))
    branch2 = Path(tempfile.mkdtemp(prefix="log_test_branch2_"))
    
    try:
        # Start FUSE with trace logging
        cmd = [
            str(Path(__file__).parent.parent / "target" / "release" / "mergerfs-rs"),
            str(mountpoint),
            str(branch1),
            str(branch2)
        ]
        
        env = os.environ.copy()
        env['RUST_LOG'] = 'trace'
        
        print(f"Starting FUSE process...")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        
        # Create simple trace monitor
        monitor = SimpleTraceMonitor(process)
        monitor.start_capture()
        
        print("Waiting for mount to be ready...")
        if monitor.wait_for_mount_ready(timeout=10.0):
            print("Mount ready detected!")
        else:
            print("Mount ready not detected in logs")
            
        # Give it time to capture some logs
        time.sleep(2.0)
        
        # Try to access the mount
        try:
            print(f"\nAccessing mount point...")
            files = list(mountpoint.iterdir())
            print(f"Files: {files}")
            
            # Create a file
            test_file = mountpoint / "test.txt"
            print(f"\nCreating file: {test_file}")
            test_file.write_text("Test content")
            
            # Wait for operations
            if monitor.wait_for_pattern('create', timeout=2.0):
                print("Create operation detected!")
            else:
                print("Create operation not detected")
                
            if monitor.wait_for_pattern('write', timeout=2.0):
                print("Write operation detected!")
            else:
                print("Write operation not detected")
                
        except Exception as e:
            print(f"Error accessing mount: {e}")
            
        # Show captured logs
        print(f"\n=== Captured logs (last 20 lines) ===")
        logs = monitor.get_recent_logs(20)
        for i, line in enumerate(logs):
            print(f"{i+1}: {line[:150]}")
            
        print(f"\nTotal captured lines: {len(monitor.log_lines)}")
        
        # Check for specific patterns
        print("\n=== Pattern search ===")
        for name, pattern in monitor.patterns.items():
            count = sum(1 for line in monitor.log_lines if pattern.search(line))
            print(f"{name}: {count} matches")
            
        # Stop monitoring
        monitor.stop_capture()
        
        # Terminate process
        process.terminate()
        process.wait(timeout=5.0)
        
    finally:
        # Cleanup
        import shutil
        for d in [mountpoint, branch1, branch2]:
            try:
                shutil.rmtree(d)
            except:
                pass


if __name__ == "__main__":
    test_simple_capture()