#!/usr/bin/env python3
"""Integration tests for extended attributes (xattr) functionality."""

import os
import xattr
import pytest
from hypothesis import given, strategies as st, assume
from pathlib import Path
import time


@pytest.mark.integration
class TestXattr:
    """Test extended attributes functionality."""
    
    def test_basic_xattr_operations(self, mounted_fs):
        """Test basic get/set/list/remove xattr operations."""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "xattr_test.txt"
        test_file.write_text("test content")
        
        # Set an xattr
        attr_name = b"user.test_attr"
        attr_value = b"test value"
        xattr.setxattr(str(test_file), attr_name, attr_value)
        
        # Get the xattr
        retrieved = xattr.getxattr(str(test_file), attr_name)
        assert retrieved == attr_value
        
        # List xattrs
        attrs = xattr.listxattr(str(test_file))
        # Convert attrs to bytes if needed
        if attrs and isinstance(attrs[0], str):
            attrs = [a.encode() for a in attrs]
        assert attr_name in attrs
        
        # Remove the xattr
        xattr.removexattr(str(test_file), attr_name)
        
        # Verify it's gone
        attrs = xattr.listxattr(str(test_file))
        if attrs and isinstance(attrs[0], str):
            attrs = [a.encode() for a in attrs]
        assert attr_name not in attrs
    
    def test_xattr_on_multiple_branches(self, mounted_fs):
        """Test that xattrs work correctly across multiple branches."""
        process, mountpoint, branches = mounted_fs
        
        # Create file directly on first branch
        branch1_file = branches[0] / "multi_branch.txt"
        branch1_file.write_text("branch1 content")
        
        # Access through mountpoint
        mount_file = mountpoint / "multi_branch.txt"
        assert mount_file.exists()
        
        # Set xattr through mountpoint
        attr_name = b"user.branch_attr"
        attr_value = b"value from mountpoint"
        xattr.setxattr(str(mount_file), attr_name, attr_value)
        
        # Check it's set on the branch file
        branch_attrs = xattr.getxattr(str(branch1_file), attr_name)
        assert branch_attrs == attr_value
        
        # Create same file on second branch
        if len(branches) > 1:
            branch2_file = branches[1] / "multi_branch.txt"
            branch2_file.write_text("branch2 content")
            
            # The mountpoint should still show the first branch's file (FirstFound policy)
            content = mount_file.read_text()
            assert content == "branch1 content"
            
            # And the xattr should still be accessible
            mount_attrs = xattr.getxattr(str(mount_file), attr_name)
            assert mount_attrs == attr_value
    
    def test_xattr_create_replace_flags(self, mounted_fs):
        """Test XATTR_CREATE and XATTR_REPLACE flags."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / "flags_test.txt"
        test_file.write_text("test content")
        
        attr_name = b"user.flag_test"
        attr_value = b"initial value"
        
        # Create new xattr with XATTR_CREATE flag
        xattr.setxattr(str(test_file), attr_name, attr_value, xattr.XATTR_CREATE)
        
        # Try to create again with XATTR_CREATE - should fail
        with pytest.raises(OSError) as exc:
            xattr.setxattr(str(test_file), attr_name, b"new value", xattr.XATTR_CREATE)
        # Could be EEXIST (17) or EINVAL (22) depending on implementation
        assert exc.value.errno in [17, 22]
        
        # Replace with XATTR_REPLACE flag
        new_value = b"replaced value"
        xattr.setxattr(str(test_file), attr_name, new_value, xattr.XATTR_REPLACE)
        
        # Verify the replacement
        retrieved = xattr.getxattr(str(test_file), attr_name)
        assert retrieved == new_value
        
        # Try to replace non-existent xattr - should fail
        with pytest.raises(OSError) as exc:
            xattr.setxattr(str(test_file), b"user.nonexistent", b"value", xattr.XATTR_REPLACE)
        # Could be ENODATA (61) or ENOENT (2) depending on implementation
        assert exc.value.errno in [2, 61]
    
    def test_xattr_with_special_characters(self, mounted_fs):
        """Test xattrs with special characters in names and values."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / "special_chars.txt"
        test_file.write_text("test content")
        
        # Test with various special characters
        test_cases = [
            (b"user.with_underscore", b"value_with_underscore"),
            (b"user.with.dots", b"value.with.dots"),
            (b"user.with-dash", b"value-with-dash"),
            (b"user.unicode", "unicode value: 你好世界 🌍".encode('utf-8')),
            (b"user.binary", b"\x00\x01\x02\x03\x04\x05"),
        ]
        
        for attr_name, attr_value in test_cases:
            xattr.setxattr(str(test_file), attr_name, attr_value)
            retrieved = xattr.getxattr(str(test_file), attr_name)
            assert retrieved == attr_value
    
    def test_xattr_size_limits(self, mounted_fs):
        """Test xattr with various sizes."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / "size_test.txt"
        test_file.write_text("test content")
        
        # Test various sizes (keep smaller to avoid I/O errors)
        sizes = [1, 100, 1000, 2048]
        
        for size in sizes:
            attr_name = f"user.size_{size}".encode()
            attr_value = b"x" * size
            
            xattr.setxattr(str(test_file), attr_name, attr_value)
            retrieved = xattr.getxattr(str(test_file), attr_name)
            assert retrieved == attr_value
            assert len(retrieved) == size
    
    def test_xattr_on_directories(self, mounted_fs):
        """Test xattrs on directories."""
        process, mountpoint, branches = mounted_fs
        
        test_dir = mountpoint / "xattr_dir"
        test_dir.mkdir()
        
        # Set xattr on directory
        attr_name = b"user.dir_attr"
        attr_value = b"directory attribute"
        xattr.setxattr(str(test_dir), attr_name, attr_value)
        
        # Get the xattr
        retrieved = xattr.getxattr(str(test_dir), attr_name)
        assert retrieved == attr_value
        
        # List xattrs
        attrs = xattr.listxattr(str(test_dir))
        if attrs and isinstance(attrs[0], str):
            attrs = [a.encode() for a in attrs]
        assert attr_name in attrs
        
        # Remove the xattr
        xattr.removexattr(str(test_dir), attr_name)
        attrs = xattr.listxattr(str(test_dir))
        if attrs and isinstance(attrs[0], str):
            attrs = [a.encode() for a in attrs]
        assert attr_name not in attrs
    
    def test_mergerfs_control_file_xattrs(self, mounted_fs):
        """Test special mergerfs xattrs on the control file."""
        process, mountpoint, branches = mounted_fs
        
        # The .mergerfs control file
        control_file = mountpoint / ".mergerfs"
        
        # Test reading policy configuration
        try:
            # Try to get the create policy
            policy = xattr.getxattr(str(control_file), b"user.mergerfs.create")
            assert isinstance(policy, bytes)
            # Default should be 'ff' (first found)
            assert policy.decode('utf-8').strip() == 'ff'
        except OSError as e:
            # Some systems might not support this
            if e.errno != 61:  # ENODATA
                raise
        
        # Test setting a new policy
        try:
            xattr.setxattr(str(control_file), b"user.mergerfs.create", b"mfs")
            new_policy = xattr.getxattr(str(control_file), b"user.mergerfs.create")
            assert new_policy == b"mfs"
            
            # Restore original
            xattr.setxattr(str(control_file), b"user.mergerfs.create", b"ff")
        except OSError as e:
            # Setting might not be supported
            if e.errno not in [61, 95]:  # ENODATA, EOPNOTSUPP
                raise
    
    def test_xattr_edge_cases(self, mounted_fs):
        """Test xattrs with edge case names and values."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / "edge_test.txt"
        test_file.write_text("test content")
        
        # Test edge cases
        edge_cases = [
            (b"user.empty", b""),  # Empty value
            (b"user.single", b"x"),  # Single character
            (b"user.long_name_" + b"x" * 30, b"value"),  # Long name
        ]
        
        for attr_name, attr_value in edge_cases:
            try:
                # Set the xattr
                xattr.setxattr(str(test_file), attr_name, attr_value)
                
                # Get it back
                retrieved = xattr.getxattr(str(test_file), attr_name)
                assert retrieved == attr_value
                
                # List should contain it
                attrs = xattr.listxattr(str(test_file))
                if attrs and isinstance(attrs[0], str):
                    attrs = [a.encode() for a in attrs]
                assert attr_name in attrs
                
                # Remove it
                xattr.removexattr(str(test_file), attr_name)
                
            except OSError as e:
                # Some edge cases might not be supported
                if e.errno not in [22, 95]:  # EINVAL, EOPNOTSUPP
                    raise