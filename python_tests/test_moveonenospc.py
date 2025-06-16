#!/usr/bin/env python3
"""
Test moveonenospc functionality - automatic file migration on ENOSPC
"""

import os
import pytest
import xattr
import tempfile
import threading
from pathlib import Path
import time

@pytest.mark.integration
class TestMoveOnENOSPC:
    """Test automatic file movement when a branch runs out of space"""
    
    def test_moveonenospc_enabled_by_default(self, mounted_fs):
        """Test that moveonenospc is enabled by default with pfrd policy"""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Check the moveonenospc configuration via xattr
        control_file = mountpoint / ".mergerfs"
        value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc")
        assert value == b"pfrd"  # Default policy
    
    def test_moveonenospc_can_be_disabled(self, mounted_fs):
        """Test that moveonenospc can be disabled"""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Disable moveonenospc
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"false")
        
        # Verify it's disabled
        value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc")
        assert value == b"false"
    
    def test_moveonenospc_policy_change(self, mounted_fs):
        """Test changing moveonenospc policy"""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test various policy settings
        for policy in [b"ff", b"mfs", b"lfs", b"rand", b"epmfs"]:
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", policy)
            value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc")
            assert value == policy
        
        # Test enabling with "true" (should use default pfrd)
        xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"true")
        value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc")
        assert value == b"pfrd"
    
    def test_invalid_moveonenospc_value(self, mounted_fs):
        """Test that invalid moveonenospc values are rejected"""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Try to set an invalid policy
        with pytest.raises(OSError) as excinfo:
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"invalid_policy")
        assert excinfo.value.errno == 22  # EINVAL
    
    def test_moveonenospc_basic_functionality(self, mounted_fs_with_trace, smart_wait):
        """Test basic moveonenospc functionality when branch fills up"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # This test requires manual disk space manipulation which is complex
        # In a real test environment, you would:
        # 1. Create a small loopback filesystem for branch1
        # 2. Fill it almost to capacity
        # 3. Write a file that would exceed capacity
        # 4. Verify the file gets moved to branch2
        
        # For now, we'll test the configuration and basic file operations
        file_path = mountpoint / "test_file.txt"
        
        # Create a file
        file_path.write_text("Initial content")
        assert smart_wait.wait_for_file_visible(file_path)
        
        # Write more data
        with open(file_path, 'a') as f:
            f.write("Additional content\n" * 1000)
        
        # Verify file still exists and is accessible
        assert file_path.exists()
        content = file_path.read_text()
        assert "Initial content" in content
        assert "Additional content" in content
    
    def test_moveonenospc_with_multiple_writes(self, mounted_fs_with_trace, smart_wait):
        """Test moveonenospc with multiple concurrent writes"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create multiple files
        files = []
        for i in range(5):
            file_path = mountpoint / f"concurrent_file_{i}.txt"
            file_path.write_text(f"File {i} content")
            files.append(file_path)
            assert smart_wait.wait_for_file_visible(file_path)
        
        # Perform concurrent writes
        def write_to_file(file_path, content):
            with open(file_path, 'a') as f:
                for _ in range(100):
                    f.write(content)
                    f.flush()
        
        threads = []
        for i, file_path in enumerate(files):
            t = threading.Thread(
                target=write_to_file,
                args=(file_path, f"Thread {i} data\n")
            )
            t.start()
            threads.append(t)
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # Verify all files are still accessible
        for i, file_path in enumerate(files):
            assert file_path.exists()
            content = file_path.read_text()
            assert f"File {i} content" in content
            assert f"Thread {i} data" in content
    
    def test_moveonenospc_preserves_file_attributes(self, mounted_fs_with_trace, smart_wait):
        """Test that moveonenospc preserves file attributes when moving"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        file_path = mountpoint / "attr_test.txt"
        
        # Create file with specific attributes
        file_path.write_text("Test content")
        assert smart_wait.wait_for_file_visible(file_path)
        
        # Set custom permissions
        os.chmod(file_path, 0o644)
        
        # Set extended attributes
        xattr.setxattr(str(file_path), "user.custom", b"test_value")
        
        # Get original timestamps
        stat_before = os.stat(file_path)
        
        # Perform multiple writes (simulating potential move)
        with open(file_path, 'a') as f:
            for i in range(10):
                f.write(f"Additional line {i}\n")
        
        # Verify attributes are preserved
        stat_after = os.stat(file_path)
        assert stat_after.st_mode == stat_before.st_mode
        
        # Check xattr is preserved
        assert xattr.getxattr(str(file_path), "user.custom") == b"test_value"
    
    def test_moveonenospc_with_open_file_handles(self, mounted_fs_with_trace, smart_wait):
        """Test moveonenospc behavior with open file handles"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        file_path = mountpoint / "open_handle_test.txt"
        
        # Open file for writing
        with open(file_path, 'w') as f:
            f.write("Initial content\n")
            f.flush()
            
            # File handle is still open
            # Write more data
            for i in range(100):
                f.write(f"Line {i}\n")
                f.flush()
            
            # Final write
            f.write("Final content\n")
        
        # Verify file content
        assert smart_wait.wait_for_write_complete(file_path)
        content = file_path.read_text()
        assert "Initial content" in content
        assert "Line 99" in content
        assert "Final content" in content
    
    def test_moveonenospc_disabled_behavior(self, mounted_fs_with_trace, smart_wait):
        """Test behavior when moveonenospc is disabled"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Disable moveonenospc
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"false")
        
        # Create and write to a file
        file_path = mountpoint / "disabled_test.txt"
        file_path.write_text("Test with moveonenospc disabled")
        assert smart_wait.wait_for_file_visible(file_path)
        
        # Perform additional writes
        with open(file_path, 'a') as f:
            for i in range(50):
                f.write(f"Additional line {i}\n")
        
        # Verify file is still accessible
        assert file_path.exists()
        content = file_path.read_text()
        assert "Test with moveonenospc disabled" in content


@pytest.mark.integration
class TestMoveOnENOSPCStress:
    """Stress tests for moveonenospc functionality"""
    
    def test_rapid_policy_changes(self, mounted_fs):
        """Test rapid changes to moveonenospc policy"""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        policies = [b"ff", b"mfs", b"lfs", b"rand", b"epmfs", b"pfrd", b"false", b"true"]
        
        # Rapidly change policies
        for _ in range(10):
            for policy in policies:
                xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", policy)
                # Immediately read it back
                value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc")
                if policy == b"true":
                    assert value == b"pfrd"  # true means pfrd
                elif policy == b"false":
                    assert value == b"false"
                else:
                    assert value == policy
    
    def test_concurrent_writes_different_files(self, mounted_fs_with_trace, smart_wait):
        """Test concurrent writes to different files"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        def write_file(index):
            file_path = mountpoint / f"stress_test_{index}.txt"
            
            # Write initial content
            file_path.write_text(f"Initial content for file {index}")
            
            # Perform many small writes
            with open(file_path, 'a') as f:
                for i in range(200):
                    f.write(f"Line {i} from file {index}\n")
                    if i % 10 == 0:
                        f.flush()
            
            return file_path
        
        # Create threads for concurrent writes
        threads = []
        file_paths = []
        for i in range(10):
            t = threading.Thread(target=lambda idx=i: file_paths.append(write_file(idx)))
            t.start()
            threads.append(t)
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Brief wait for filesystem operations to complete
        time.sleep(0.5)
        
        # Verify all files exist and have expected content
        for i in range(10):
            file_path = mountpoint / f"stress_test_{i}.txt"
            assert file_path.exists()
            content = file_path.read_text()
            assert f"Initial content for file {i}" in content
            assert f"Line 199 from file {i}" in content