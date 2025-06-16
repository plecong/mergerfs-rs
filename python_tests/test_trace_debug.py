#!/usr/bin/env python3
"""Debug test for trace monitoring."""

import os
import time
import subprocess
import tempfile
from pathlib import Path


def test_trace_capture():
    """Test basic trace capture functionality."""
    # Create test directories
    mountpoint = Path(tempfile.mkdtemp(prefix="trace_test_mount_"))
    branch1 = Path(tempfile.mkdtemp(prefix="trace_test_branch1_"))
    branch2 = Path(tempfile.mkdtemp(prefix="trace_test_branch2_"))
    
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
        
        print(f"Starting FUSE process: {' '.join(cmd)}")
        print(f"RUST_LOG={env['RUST_LOG']}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        
        # Give it time to start
        time.sleep(0.5)
        
        # Check if process is running
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            print(f"Process exited immediately!")
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            return
            
        print("Process started successfully")
        
        # Try to access the mountpoint
        print(f"Accessing mountpoint: {mountpoint}")
        try:
            files = list(mountpoint.iterdir())
            print(f"Files in mount: {files}")
        except Exception as e:
            print(f"Error accessing mount: {e}")
            
        # Create a test file
        test_file = mountpoint / "test.txt"
        print(f"Creating file: {test_file}")
        test_file.write_text("Hello, trace!")
        
        # Wait a bit
        time.sleep(1.0)
        
        # Terminate the process
        print("Terminating FUSE process...")
        process.terminate()
        
        # Get output
        stdout, stderr = process.communicate(timeout=5.0)
        
        print("\n=== STDOUT ===")
        print(stdout[:1000] if stdout else "(empty)")
        
        print("\n=== STDERR (first 50 lines) ===")
        if stderr:
            lines = stderr.split('\n')
            for i, line in enumerate(lines[:50]):
                print(f"{i+1}: {line}")
        else:
            print("(empty)")
            
        # Look for trace patterns
        if stderr:
            trace_count = stderr.count('TRACE')
            debug_count = stderr.count('DEBUG')
            info_count = stderr.count('INFO')
            span_count = stderr.count('fuse::')
            
            print(f"\n=== Log Analysis ===")
            print(f"TRACE entries: {trace_count}")
            print(f"DEBUG entries: {debug_count}")
            print(f"INFO entries: {info_count}")
            print(f"FUSE spans: {span_count}")
            
    finally:
        # Cleanup
        import shutil
        for d in [mountpoint, branch1, branch2]:
            try:
                shutil.rmtree(d)
            except:
                pass


if __name__ == "__main__":
    test_trace_capture()