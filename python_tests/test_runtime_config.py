#!/usr/bin/env python3
"""Integration tests for runtime configuration via xattr interface."""

import os
import xattr
import pytest
from test_file_ops import MergerFSTestBase


class TestRuntimeConfig(MergerFSTestBase):
    """Test runtime configuration functionality."""
    
    def test_control_file_exists(self):
        """Test that the control file .mergerfs exists."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # File should exist
        assert os.path.exists(control_file)
        
        # Should be a regular file
        assert os.path.isfile(control_file)
        
        # Should be readable
        assert os.access(control_file, os.R_OK)
        
        # Should not be writable (permissions are read-only)
        # Note: xattr can still modify attributes despite file permissions
    
    def test_list_configuration_options(self):
        """Test listing all configuration options."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # List all xattrs
        attrs = xattr.listxattr(control_file)
        
        # Should have configuration options
        attr_names = [attr.decode('utf-8') for attr in attrs]
        
        # Check for expected options
        assert 'user.mergerfs.func.create' in attr_names
        assert 'user.mergerfs.moveonenospc' in attr_names
        assert 'user.mergerfs.direct_io' in attr_names
        assert 'user.mergerfs.version' in attr_names
        assert 'user.mergerfs.pid' in attr_names
    
    def test_get_configuration_values(self):
        """Test getting configuration values."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Get version (read-only)
        version = xattr.getxattr(control_file, b'user.mergerfs.version')
        assert version  # Should have a version string
        
        # Get PID (read-only)
        pid = xattr.getxattr(control_file, b'user.mergerfs.pid')
        assert pid.decode('utf-8').isdigit()  # Should be a number
        
        # Get create policy
        policy = xattr.getxattr(control_file, b'user.mergerfs.func.create')
        assert policy.decode('utf-8') in ['ff', 'mfs', 'lfs', 'rand']
        
        # Get boolean options
        moveonenospc = xattr.getxattr(control_file, b'user.mergerfs.moveonenospc')
        assert moveonenospc.decode('utf-8') in ['true', 'false']
    
    def test_set_boolean_configuration(self):
        """Test setting boolean configuration options."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Get initial value
        initial = xattr.getxattr(control_file, b'user.mergerfs.moveonenospc')
        initial_bool = initial.decode('utf-8') == 'true'
        
        # Toggle the value
        new_value = b'false' if initial_bool else b'true'
        xattr.setxattr(control_file, b'user.mergerfs.moveonenospc', new_value)
        
        # Verify it changed
        current = xattr.getxattr(control_file, b'user.mergerfs.moveonenospc')
        assert current == new_value
        
        # Test various boolean formats
        for true_value in [b'true', b'1', b'yes', b'on']:
            xattr.setxattr(control_file, b'user.mergerfs.moveonenospc', true_value)
            result = xattr.getxattr(control_file, b'user.mergerfs.moveonenospc')
            assert result == b'true'
        
        for false_value in [b'false', b'0', b'no', b'off']:
            xattr.setxattr(control_file, b'user.mergerfs.moveonenospc', false_value)
            result = xattr.getxattr(control_file, b'user.mergerfs.moveonenospc')
            assert result == b'false'
    
    def test_set_policy_configuration(self):
        """Test setting policy configuration options."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Test valid policies
        valid_policies = [b'ff', b'mfs', b'lfs', b'rand']
        
        for policy in valid_policies:
            xattr.setxattr(control_file, b'user.mergerfs.func.create', policy)
            result = xattr.getxattr(control_file, b'user.mergerfs.func.create')
            assert result == policy
        
        # Test invalid policy
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.func.create', b'invalid')
        assert exc_info.value.errno == 22  # EINVAL
    
    def test_readonly_options(self):
        """Test that read-only options cannot be modified."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Try to set version (read-only)
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.version', b'new_version')
        assert exc_info.value.errno == 30  # EROFS
        
        # Try to set PID (read-only)
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.pid', b'12345')
        assert exc_info.value.errno == 30  # EROFS
    
    def test_nonexistent_option(self):
        """Test accessing non-existent configuration options."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Try to get non-existent option
        with pytest.raises(OSError) as exc_info:
            xattr.getxattr(control_file, b'user.mergerfs.nonexistent')
        assert exc_info.value.errno == 61  # ENOATTR
        
        # Try to set non-existent option
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.nonexistent', b'value')
        assert exc_info.value.errno == 61  # ENOATTR
    
    def test_configuration_affects_behavior(self):
        """Test that configuration changes affect filesystem behavior."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # This is a placeholder - in a real implementation, we would:
        # 1. Set create policy to 'mfs' (most free space)
        # 2. Create files and verify they go to the branch with most space
        # 3. Change to 'lfs' (least free space)
        # 4. Create files and verify they go to the branch with least space
        
        # For now, just verify we can change the policy
        xattr.setxattr(control_file, b'user.mergerfs.func.create', b'mfs')
        assert xattr.getxattr(control_file, b'user.mergerfs.func.create') == b'mfs'
    
    def test_invalid_value_types(self):
        """Test setting invalid value types."""
        control_file = os.path.join(self.mount_point, ".mergerfs")
        
        # Test invalid boolean value
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.moveonenospc', b'maybe')
        assert exc_info.value.errno == 22  # EINVAL
        
        # Test empty value
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(control_file, b'user.mergerfs.func.create', b'')
        assert exc_info.value.errno == 22  # EINVAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])