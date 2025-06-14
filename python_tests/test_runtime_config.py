#!/usr/bin/env python3
"""Integration tests for runtime configuration via xattr interface."""

import os
import time
import xattr
import pytest
from pathlib import Path
from typing import Tuple, List


@pytest.mark.integration
class TestRuntimeConfig:
    """Test runtime configuration functionality."""
    
    @pytest.fixture(autouse=True)
    def setup_method_fixture(self, mounted_fs):
        """Setup method that runs before each test to ensure mount is ready."""
        # Add a small delay to ensure mount is fully ready
        time.sleep(0.5)
    
    def test_control_file_exists(self, mounted_fs):
        """Test that the control file .mergerfs exists."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # File should exist
        assert control_file.exists()
        
        # Should be a regular file
        assert control_file.is_file()
        
        # Check file stats
        stat_info = control_file.stat()
        # Check if readable (0o444 = readable by all)
        assert stat_info.st_mode & 0o400
    
    def test_list_configuration_options(self, mounted_fs):
        """Test listing all configuration options."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # List all xattrs
        attrs = xattr.listxattr(str(control_file))
        
        # Should have configuration options
        # xattr might return strings or bytes depending on version
        attr_names = []
        for attr in attrs:
            if isinstance(attr, bytes):
                attr_names.append(attr.decode('utf-8'))
            else:
                attr_names.append(attr)
        
        # Check for expected options
        assert 'user.mergerfs.func.create' in attr_names
        assert 'user.mergerfs.moveonenospc' in attr_names
        assert 'user.mergerfs.direct_io' in attr_names
        assert 'user.mergerfs.version' in attr_names
        assert 'user.mergerfs.pid' in attr_names
    
    def test_get_configuration_values(self, mounted_fs):
        """Test getting configuration values."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Get version (read-only)
        version = xattr.getxattr(str(control_file), b'user.mergerfs.version')
        assert version  # Should have a version string
        
        # Get PID (read-only)
        pid = xattr.getxattr(str(control_file), b'user.mergerfs.pid')
        assert pid.decode('utf-8').isdigit()  # Should be a number
        
        # Get create policy
        policy = xattr.getxattr(str(control_file), b'user.mergerfs.func.create')
        assert policy.decode('utf-8') in ['ff', 'mfs', 'lfs', 'rand']
        
        # Get boolean options
        moveonenospc = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        assert moveonenospc.decode('utf-8') in ['true', 'false']
    
    def test_set_boolean_configuration(self, mounted_fs):
        """Test setting boolean configuration options."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Get initial value
        initial = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        initial_bool = initial.decode('utf-8') == 'true'
        
        # Toggle the value
        new_value = b'false' if initial_bool else b'true'
        xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', new_value)
        
        # Verify it changed
        current = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        assert current == new_value
        
        # Test various boolean formats
        for true_value in [b'true', b'1', b'yes', b'on']:
            xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', true_value)
            result = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
            assert result == b'true'
        
        for false_value in [b'false', b'0', b'no', b'off']:
            xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', false_value)
            result = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
            assert result == b'false'
    
    def test_set_policy_configuration(self, mounted_fs):
        """Test setting policy configuration options."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Test valid policies
        valid_policies = [b'ff', b'mfs', b'lfs', b'rand']
        
        for policy in valid_policies:
            xattr.setxattr(str(control_file), b'user.mergerfs.func.create', policy)
            result = xattr.getxattr(str(control_file), b'user.mergerfs.func.create')
            assert result == policy
        
        # Test invalid policy
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.func.create', b'invalid')
        assert exc_info.value.errno == 22  # EINVAL
    
    def test_readonly_options(self, mounted_fs):
        """Test that read-only options cannot be modified."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Try to set version (read-only)
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.version', b'new_version')
        assert exc_info.value.errno == 30  # EROFS
        
        # Try to set PID (read-only)
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.pid', b'12345')
        assert exc_info.value.errno == 30  # EROFS
    
    def test_nonexistent_option(self, mounted_fs):
        """Test accessing non-existent configuration options."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Try to get non-existent option
        with pytest.raises(OSError) as exc_info:
            xattr.getxattr(str(control_file), b'user.mergerfs.nonexistent')
        assert exc_info.value.errno == 61  # ENOATTR
        
        # Try to set non-existent option
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.nonexistent', b'value')
        assert exc_info.value.errno == 61  # ENOATTR
    
    def test_configuration_affects_behavior(self, mounted_fs):
        """Test that configuration changes affect filesystem behavior."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # This is a placeholder - in a real implementation, we would:
        # 1. Set create policy to 'mfs' (most free space)
        # 2. Create files and verify they go to the branch with most space
        # 3. Change to 'lfs' (least free space)
        # 4. Create files and verify they go to the branch with least space
        
        # For now, just verify we can change the policy
        xattr.setxattr(str(control_file), b'user.mergerfs.func.create', b'mfs')
        assert xattr.getxattr(str(control_file), b'user.mergerfs.func.create') == b'mfs'
    
    def test_invalid_value_types(self, mounted_fs):
        """Test setting invalid value types."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Test invalid boolean value
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', b'maybe')
        assert exc_info.value.errno == 22  # EINVAL
        
        # Test empty value
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), b'user.mergerfs.func.create', b'')
        assert exc_info.value.errno == 22  # EINVAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])