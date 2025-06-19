#!/usr/bin/env python3
"""Test direct I/O functionality."""

import os
import time
import pytest
import tempfile
from pathlib import Path
import xattr


@pytest.mark.integration
class TestDirectIO:
    """Test direct I/O configuration and behavior."""
    
    def test_direct_io_configuration(self, mounted_fs):
        """Test cache.files configuration for direct I/O."""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Test default is libfuse (caching enabled)
        control_file = mountpoint / ".mergerfs"
        assert control_file.exists()
        
        # Check default cache.files value
        value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
        assert value == "libfuse"
        
        # Test setting cache.files to off (direct I/O)
        xattr.setxattr(str(control_file), "user.mergerfs.cache.files", b"off")
        value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
        assert value == "off"
        
        # Test setting cache.files to full (kernel caching)
        xattr.setxattr(str(control_file), "user.mergerfs.cache.files", b"full")
        value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
        assert value == "full"
        
        # Test invalid value
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), "user.mergerfs.cache.files", b"invalid")
        assert exc_info.value.errno == 22  # EINVAL
        
        # Value should remain unchanged after invalid set
        value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
        assert value == "full"
    
    def test_direct_io_file_operations(self, mounted_fs):
        """Test file operations with direct I/O mode."""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Enable direct I/O
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.cache.files", b"off")
        
        # Create a test file
        test_file = mountpoint / "direct_io_test.txt"
        test_content = b"Direct I/O test content\n" * 100
        
        # Write file (should use direct I/O)
        test_file.write_bytes(test_content)
        time.sleep(0.1)  # Let filesystem process the write
        
        # Verify file exists in one of the branches
        found = False
        for branch in branches:
            branch_file = branch / "direct_io_test.txt"
            if branch_file.exists():
                found = True
                assert branch_file.read_bytes() == test_content
                break
        assert found, "File should exist in at least one branch"
        
        # Read file (should use direct I/O)
        read_content = test_file.read_bytes()
        assert read_content == test_content
        
        # Append to file
        append_content = b"Appended content\n"
        with open(test_file, 'ab') as f:
            f.write(append_content)
        
        time.sleep(0.1)
        
        # Verify append worked
        final_content = test_file.read_bytes()
        assert final_content == test_content + append_content
    
    def test_cache_files_modes(self, mounted_fs):
        """Test different cache.files modes."""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Test all valid modes
        valid_modes = ["libfuse", "off", "partial", "full", "auto-full", "per-process"]
        
        for mode in valid_modes:
            xattr.setxattr(str(control_file), "user.mergerfs.cache.files", mode.encode())
            value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
            assert value == mode, f"Mode {mode} should be set correctly"
    
    def test_direct_io_with_multiple_files(self, mounted_fs):
        """Test direct I/O with multiple concurrent files."""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Enable direct I/O
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.cache.files", b"off")
        
        # Create multiple files
        files = []
        for i in range(5):
            test_file = mountpoint / f"direct_io_{i}.txt"
            content = f"File {i} content\n".encode() * 10
            test_file.write_bytes(content)
            files.append((test_file, content))
        
        time.sleep(0.2)
        
        # Verify all files
        for test_file, expected_content in files:
            assert test_file.exists()
            assert test_file.read_bytes() == expected_content
    
    def test_legacy_direct_io_option(self, mounted_fs):
        """Test the legacy direct_io boolean option."""
        # Handle both trace and non-trace cases
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # The direct_io option should exist but is deprecated
        # Setting it should not cause errors
        xattr.setxattr(str(control_file), "user.mergerfs.direct_io", b"true")
        value = xattr.getxattr(str(control_file), "user.mergerfs.direct_io").decode()
        assert value in ["true", "false"]  # Implementation may ignore the setting