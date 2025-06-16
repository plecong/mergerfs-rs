#!/usr/bin/env python3
"""
Demonstration of the simple trace monitoring infrastructure.

This test shows how to use trace monitoring to intelligently wait for FUSE operations
instead of using hardcoded sleep() calls.
"""

import os
import time
import pytest
from pathlib import Path


@pytest.mark.integration
class TestSimpleTraceDemo:
    """Demonstrate simple trace-based waiting vs hardcoded sleeps."""
    
    def test_traditional_vs_trace_approach(self, mounted_fs_with_trace, smart_wait):
        """Compare traditional sleep vs trace-based waiting."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Traditional approach with sleep
        test_file1 = mountpoint / "test_traditional.txt"
        start_time = time.time()
        
        test_file1.write_text("Hello, world!")
        time.sleep(0.5)  # Hardcoded sleep
        assert test_file1.exists()
        
        traditional_time = time.time() - start_time
        print(f"\nTraditional approach: {traditional_time:.3f}s (includes 0.5s sleep)")
        
        # Trace-based approach
        test_file2 = mountpoint / "test_traced.txt"
        start_time = time.time()
        
        test_file2.write_text("Hello, traced world!")
        # Smart wait for file to be visible
        assert smart_wait.wait_for_file_visible(test_file2)
        
        trace_time = time.time() - start_time
        print(f"Trace-based approach: {trace_time:.3f}s (only waits as needed)")
        print(f"Improvement: {((traditional_time - trace_time) / traditional_time * 100):.1f}% faster")
        
    def test_directory_operations(self, mounted_fs_with_trace, smart_wait):
        """Test directory creation with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        test_dir = mountpoint / "test_dir"
        nested_dir = test_dir / "nested"
        
        # Create directory and wait
        test_dir.mkdir()
        assert smart_wait.wait_for_dir_visible(test_dir)
        
        # Create nested directory
        nested_dir.mkdir()
        assert smart_wait.wait_for_dir_visible(nested_dir)
        
        # Create file in directory
        test_file = nested_dir / "test.txt"
        test_file.write_text("content")
        assert smart_wait.wait_for_file_visible(test_file)
        
    def test_file_deletion(self, mounted_fs_with_trace, smart_wait):
        """Test file deletion with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        test_file = mountpoint / "test_delete.txt"
        
        # Create and verify
        test_file.write_text("delete me")
        assert smart_wait.wait_for_file_visible(test_file)
        
        # Delete and verify
        test_file.unlink()
        assert smart_wait.wait_for_deletion(test_file)
        
    def test_xattr_operations(self, mounted_fs_with_trace, smart_wait):
        """Test extended attribute operations with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        import xattr
        
        test_file = mountpoint / "test_xattr.txt"
        test_file.write_text("xattr test")
        assert smart_wait.wait_for_file_visible(test_file)
        
        # Set xattr
        xattr.setxattr(str(test_file), "user.test", b"value")
        smart_wait.wait_for_xattr_operation(test_file, "setxattr")
        
        # Get xattr
        value = xattr.getxattr(str(test_file), "user.test")
        assert value == b"value"
        
    def test_concurrent_operations(self, mounted_fs_with_trace, smart_wait):
        """Test multiple concurrent file operations."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create multiple files quickly
        files = []
        for i in range(5):
            f = mountpoint / f"concurrent_{i}.txt"
            f.write_text(f"content {i}")
            files.append(f)
            
        # Wait for all files to be visible
        for f in files:
            assert smart_wait.wait_for_file_visible(f, timeout=2.0)
            
        # Verify content
        for i, f in enumerate(files):
            assert f.read_text() == f"content {i}"