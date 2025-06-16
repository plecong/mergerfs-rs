#!/usr/bin/env python3
"""
Demonstration of the enhanced trace monitoring infrastructure.

This test shows how to use trace monitoring to intelligently wait for FUSE operations
instead of using hardcoded sleep() calls.
"""

import os
import time
import pytest
from pathlib import Path
from lib.timing_utils import OperationStatus


@pytest.mark.integration
class TestTraceDemo:
    """Demonstrate trace-based waiting vs hardcoded sleeps."""
    
    def test_traditional_sleep_approach(self, mounted_fs):
        """Example of traditional approach with hardcoded sleeps."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
            trace_monitor = None
            
        # Traditional approach: create file and wait with sleep
        test_file = mountpoint / "test_traditional.txt"
        
        start_time = time.time()
        
        # Write file
        test_file.write_text("Hello, world!")
        
        # Traditional hardcoded sleep to ensure write completes
        time.sleep(0.5)  # This is what we want to avoid!
        
        # Verify file exists
        assert test_file.exists()
        content = test_file.read_text()
        assert content == "Hello, world!"
        
        elapsed = time.time() - start_time
        print(f"Traditional approach took {elapsed:.3f}s (includes 0.5s sleep)")
        
    def test_trace_based_approach(self, mounted_fs_with_trace, smart_wait):
        """Example of trace-based intelligent waiting."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        if not trace_monitor:
            pytest.skip("Trace monitoring not available")
            
        test_file = mountpoint / "test_traced.txt"
        
        start_time = time.time()
        
        # Clear any previous operations
        trace_monitor.clear_completed()
        
        # Write file
        test_file.write_text("Hello, traced world!")
        
        # Smart wait: wait for the actual write operation to complete
        success = smart_wait.wait_for_write_complete(test_file, timeout=2.0)
        assert success, "Write operation did not complete in time"
        
        # Verify file exists
        assert test_file.exists()
        content = test_file.read_text()
        assert content == "Hello, traced world!"
        
        elapsed = time.time() - start_time
        print(f"Trace-based approach took {elapsed:.3f}s (no hardcoded sleep!)")
        
        # Show what operations were tracked
        write_ops = [op for op in trace_monitor.completed_operations 
                     if op.operation == 'write']
        print(f"Tracked {len(write_ops)} write operations")
        
    def test_directory_operations_with_trace(self, mounted_fs_with_trace, smart_wait):
        """Demonstrate waiting for directory operations."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        if not trace_monitor:
            pytest.skip("Trace monitoring not available")
            
        test_dir = mountpoint / "test_dir"
        
        # Create directory and wait for it
        test_dir.mkdir()
        
        # Wait for mkdir operation
        success = smart_wait.wait_for_dir_visible(test_dir, timeout=2.0)
        assert success, "Directory creation did not complete"
        
        # Verify directory exists
        assert test_dir.is_dir()
        
        # Create a file in the directory
        test_file = test_dir / "file.txt"
        test_file.write_text("Content")
        
        # Wait for file creation
        success = smart_wait.wait_for_file_visible(test_file, timeout=2.0)
        assert success, "File creation did not complete"
        
        # Delete the file and wait
        test_file.unlink()
        success = smart_wait.wait_for_deletion(test_file, timeout=2.0)
        assert success, "File deletion did not complete"
        
        assert not test_file.exists()
        
    def test_concurrent_operations_tracking(self, mounted_fs_with_trace):
        """Show how trace monitoring helps with concurrent operations."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        if not trace_monitor:
            pytest.skip("Trace monitoring not available")
            
        # Clear previous operations
        trace_monitor.clear_completed()
        
        # Create multiple files
        files = []
        for i in range(5):
            f = mountpoint / f"concurrent_{i}.txt"
            f.write_text(f"File {i}")
            files.append(f)
            
        # Wait for all create operations to complete
        create_ops = trace_monitor.wait_for_operations(
            ['create'] * 5,  # Wait for 5 create operations
            timeout=3.0,
            all_required=True
        )
        
        assert len(create_ops) >= 5, f"Expected at least 5 create operations, got {len(create_ops)}"
        
        # Verify all files exist
        for f in files:
            assert f.exists()
            
        # Show operation statistics
        print(f"\nOperation Statistics:")
        print(f"Total completed operations: {len(trace_monitor.completed_operations)}")
        
        op_counts = {}
        for op in trace_monitor.completed_operations:
            op_counts[op.operation] = op_counts.get(op.operation, 0) + 1
            
        for op_type, count in sorted(op_counts.items()):
            print(f"  {op_type}: {count}")
            
    def test_error_handling_with_trace(self, mounted_fs_with_trace):
        """Demonstrate how trace monitoring helps identify errors."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        if not trace_monitor:
            pytest.skip("Trace monitoring not available")
            
        # Try to create a file in a non-existent directory
        bad_file = mountpoint / "nonexistent" / "file.txt"
        
        # This should fail
        with pytest.raises(FileNotFoundError):
            bad_file.write_text("This should fail")
            
        # Wait a moment for the operation to be logged
        time.sleep(0.1)
        
        # Check for failed operations
        failed_ops = trace_monitor.get_failed_operations()
        
        # There should be at least one failed operation
        if failed_ops:
            print(f"\nDetected {len(failed_ops)} failed operations:")
            for op in failed_ops:
                print(f"  {op.operation} - error code: {op.error_code}")
                
    def test_xattr_operations_with_trace(self, mounted_fs_with_trace, smart_wait):
        """Test extended attribute operations with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        if not trace_monitor:
            pytest.skip("Trace monitoring not available")
            
        import xattr
        
        test_file = mountpoint / "xattr_test.txt"
        test_file.write_text("Test content")
        
        # Wait for file to be created
        smart_wait.wait_for_file_visible(test_file, timeout=2.0)
        
        # Set an extended attribute
        xattr.setxattr(str(test_file), "user.test", b"test_value")
        
        # Wait for setxattr operation
        success = smart_wait.wait_for_xattr_operation(test_file, 'setxattr', timeout=2.0)
        assert success, "setxattr operation did not complete"
        
        # Verify the xattr was set
        value = xattr.getxattr(str(test_file), "user.test")
        assert value == b"test_value"
        
        # List xattrs
        attrs = xattr.listxattr(str(test_file))
        assert "user.test" in attrs or b"user.test" in attrs


def test_comparison_summary():
    """Summary comparing traditional vs trace-based approaches."""
    print("\n" + "="*60)
    print("COMPARISON: Traditional Sleep vs Trace-Based Waiting")
    print("="*60)
    print("\nTraditional Approach Problems:")
    print("- Uses hardcoded sleep() calls")
    print("- Wastes time on fast operations")  
    print("- May timeout on slow operations")
    print("- No visibility into actual FUSE operations")
    print("- Difficult to debug timing issues")
    
    print("\nTrace-Based Approach Benefits:")
    print("- Waits for actual operation completion")
    print("- Minimal waiting time")
    print("- Configurable timeouts per operation")
    print("- Full visibility into FUSE operations")
    print("- Easy debugging with operation logs")
    print("- Can detect and report errors")
    
    print("\nUsage:")
    print("1. Enable trace monitoring:")
    print("   export FUSE_TRACE=1")
    print("   pytest test_file.py")
    print("\n2. Use smart_wait fixture in tests:")
    print("   smart_wait.wait_for_file_visible(path)")
    print("   smart_wait.wait_for_write_complete(path)")
    print("   smart_wait.wait_for_deletion(path)")
    print("\n3. Access trace monitor directly for advanced usage:")
    print("   trace_monitor.wait_for_operation('lookup', path='/test')")
    print("   trace_monitor.get_failed_operations()")
    print("="*60)


if __name__ == "__main__":
    # Run with trace monitoring enabled
    os.environ['FUSE_TRACE'] = '1'
    pytest.main([__file__, "-v", "-s"])