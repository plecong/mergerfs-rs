#!/usr/bin/env python3
"""Integration tests for extended attributes (xattr) functionality."""

import os
import xattr
import pytest
from hypothesis import given, strategies as st, assume
from test_file_ops import MergerFSTestBase


class TestXattr(MergerFSTestBase):
    """Test extended attributes functionality."""
    
    def test_basic_xattr_operations(self):
        """Test basic get/set/list/remove xattr operations."""
        # Create a test file
        test_file = os.path.join(self.mount_point, "xattr_test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        # Set an xattr
        attr_name = b"user.test_attr"
        attr_value = b"test value"
        xattr.setxattr(test_file, attr_name, attr_value)
        
        # Get the xattr
        retrieved = xattr.getxattr(test_file, attr_name)
        assert retrieved == attr_value
        
        # List xattrs
        attrs = xattr.listxattr(test_file)
        assert attr_name in attrs
        
        # Remove xattr
        xattr.removexattr(test_file, attr_name)
        
        # Verify it's gone
        with pytest.raises(OSError):
            xattr.getxattr(test_file, attr_name)
    
    def test_xattr_multiple_branches(self):
        """Test that xattrs are applied to all branches with the file."""
        # Create file in first branch only
        branch1_file = os.path.join(self.branch1, "multi_branch.txt")
        with open(branch1_file, 'w') as f:
            f.write("branch1 content")
        
        # Access through mount point
        mount_file = os.path.join(self.mount_point, "multi_branch.txt")
        
        # Set xattr through mount point
        attr_name = b"user.multi_attr"
        attr_value = b"multi value"
        xattr.setxattr(mount_file, attr_name, attr_value)
        
        # Verify xattr exists on branch1
        assert xattr.getxattr(branch1_file, attr_name) == attr_value
        
        # Create file in branch2
        branch2_file = os.path.join(self.branch2, "multi_branch.txt")
        with open(branch2_file, 'w') as f:
            f.write("branch2 content")
        
        # Set another xattr through mount point - should affect both branches
        attr2_name = b"user.multi_attr2"
        attr2_value = b"another value"
        xattr.setxattr(mount_file, attr2_name, attr2_value)
        
        # Both branches should have the new attribute
        assert xattr.getxattr(branch1_file, attr2_name) == attr2_value
        assert xattr.getxattr(branch2_file, attr2_name) == attr2_value
    
    def test_xattr_create_replace_flags(self):
        """Test XATTR_CREATE and XATTR_REPLACE flags."""
        test_file = os.path.join(self.mount_point, "flags_test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        attr_name = b"user.flag_attr"
        value1 = b"value1"
        value2 = b"value2"
        
        # Create new attribute
        xattr.setxattr(test_file, attr_name, value1, xattr.XATTR_CREATE)
        assert xattr.getxattr(test_file, attr_name) == value1
        
        # Try to create again - should fail
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(test_file, attr_name, value2, xattr.XATTR_CREATE)
        assert exc_info.value.errno == 17  # EEXIST
        
        # Replace should work
        xattr.setxattr(test_file, attr_name, value2, xattr.XATTR_REPLACE)
        assert xattr.getxattr(test_file, attr_name) == value2
        
        # Try to replace non-existent - should fail
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(test_file, b"user.nonexistent", b"data", xattr.XATTR_REPLACE)
        assert exc_info.value.errno == 61  # ENODATA
    
    def test_xattr_special_chars(self):
        """Test xattrs with special characters in names and values."""
        test_file = os.path.join(self.mount_point, "special_chars.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        # Test various special characters
        test_cases = [
            (b"user.with_spaces", b"value with spaces"),
            (b"user.with_newline", b"value\nwith\nnewlines"),
            (b"user.with_nulls", b"value\x00with\x00nulls"),
            (b"user.unicode", "unicode_value_🎉".encode('utf-8')),
        ]
        
        for attr_name, attr_value in test_cases:
            xattr.setxattr(test_file, attr_name, attr_value)
            retrieved = xattr.getxattr(test_file, attr_name)
            assert retrieved == attr_value
    
    def test_xattr_size_limits(self):
        """Test xattr size limits."""
        test_file = os.path.join(self.mount_point, "size_test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        # Test large value (64KB)
        large_value = b"X" * 65536
        xattr.setxattr(test_file, b"user.large", large_value)
        retrieved = xattr.getxattr(test_file, b"user.large")
        assert len(retrieved) == 65536
        assert retrieved == large_value
        
        # Test empty value
        xattr.setxattr(test_file, b"user.empty", b"")
        retrieved = xattr.getxattr(test_file, b"user.empty")
        assert len(retrieved) == 0
    
    def test_xattr_on_directories(self):
        """Test xattrs on directories."""
        test_dir = os.path.join(self.mount_point, "xattr_dir")
        os.mkdir(test_dir)
        
        # Set xattr on directory
        attr_name = b"user.dir_attr"
        attr_value = b"directory attribute"
        xattr.setxattr(test_dir, attr_name, attr_value)
        
        # Get xattr from directory
        retrieved = xattr.getxattr(test_dir, attr_name)
        assert retrieved == attr_value
        
        # List directory xattrs
        attrs = xattr.listxattr(test_dir)
        assert attr_name in attrs
        
        # Remove directory xattr
        xattr.removexattr(test_dir, attr_name)
        with pytest.raises(OSError):
            xattr.getxattr(test_dir, attr_name)
    
    def test_xattr_mergerfs_special_attrs_blocked(self):
        """Test that mergerfs special attributes are blocked from modification."""
        test_file = os.path.join(self.mount_point, "special_test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        # Try to set mergerfs special attributes - should fail
        special_attrs = [
            b"user.mergerfs.basepath",
            b"user.mergerfs.relpath",
            b"user.mergerfs.fullpath",
            b"user.mergerfs.allpaths",
        ]
        
        for attr_name in special_attrs:
            with pytest.raises(OSError) as exc_info:
                xattr.setxattr(test_file, attr_name, b"should fail")
            assert exc_info.value.errno == 13  # EACCES
            
            with pytest.raises(OSError) as exc_info:
                xattr.removexattr(test_file, attr_name)
            assert exc_info.value.errno == 13  # EACCES
    
    @pytest.mark.slow
    @given(
        attr_names=st.lists(
            st.text(min_size=1, max_size=100).map(lambda s: f"user.{s}".encode()),
            min_size=1,
            max_size=10,
            unique=True
        ),
        attr_values=st.lists(
            st.binary(min_size=0, max_size=1000),
            min_size=1,
            max_size=10
        )
    )
    def test_xattr_property_based(self, attr_names, attr_values):
        """Property-based testing for xattr operations."""
        # Ensure we have same number of names and values
        assume(len(attr_names) == len(attr_values))
        
        # Filter out invalid attribute names
        attr_names = [name for name in attr_names if b'\x00' not in name and len(name) < 256]
        if not attr_names:
            return
        
        test_file = os.path.join(self.mount_point, "prop_test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        # Set all attributes
        attrs_set = {}
        for name, value in zip(attr_names, attr_values):
            try:
                xattr.setxattr(test_file, name, value)
                attrs_set[name] = value
            except OSError:
                # Some names might be invalid
                pass
        
        # Verify all set attributes
        for name, expected_value in attrs_set.items():
            retrieved = xattr.getxattr(test_file, name)
            assert retrieved == expected_value
        
        # List should contain all our attributes
        listed = xattr.listxattr(test_file)
        for name in attrs_set:
            assert name in listed
        
        # Remove all attributes
        for name in attrs_set:
            xattr.removexattr(test_file, name)
            with pytest.raises(OSError):
                xattr.getxattr(test_file, name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])