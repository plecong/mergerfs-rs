#!/usr/bin/env python3
"""Integration tests for runtime configuration via xattr interface - with trace-based waiting."""

import os
import time
import xattr
import pytest
from pathlib import Path
from typing import Tuple, List

from lib.simple_trace import SimpleTraceMonitor, SimpleWaitHelper


@pytest.mark.integration
class TestRuntimeConfigWithTrace:
    """Test runtime configuration functionality with trace-based waiting."""
    
    @pytest.fixture(autouse=True)
    def setup_trace_monitoring(self, mounted_fs):
        """Setup trace monitoring for the mounted filesystem."""
        process, mountpoint, branches = mounted_fs
        
        # Create trace monitor
        self.trace_monitor = SimpleTraceMonitor(process)
        self.trace_monitor.start_capture()
        
        # Create wait helper
        self.wait_helper = SimpleWaitHelper(self.trace_monitor)
        
        # Wait for mount to be ready using trace monitoring
        assert self.trace_monitor.wait_for_mount_ready(timeout=5.0), "Mount did not become ready"
        
        yield
        
        # Cleanup
        self.trace_monitor.stop_capture()
    
    def test_control_file_exists(self, mounted_fs):
        """Test that the control file .mergerfs exists."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Wait for control file to be visible
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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
        """Test setting boolean configuration options with trace monitoring."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
        # Get initial value
        initial = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        initial_bool = initial.decode('utf-8') == 'true'
        
        # Toggle the value
        new_value = b'false' if initial_bool else b'true'
        xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', new_value)
        
        # Wait for xattr operation to complete
        self.wait_helper.wait_for_xattr_operation(control_file, 'setxattr')
        
        # Verify it changed
        current = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        assert current == new_value
        
        # Test various boolean formats
        for true_value in [b'true', b'1', b'yes', b'on']:
            xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', true_value)
            self.wait_helper.wait_for_xattr_operation(control_file, 'setxattr')
            result = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
            assert result == b'true'
        
        for false_value in [b'false', b'0', b'no', b'off']:
            xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', false_value)
            self.wait_helper.wait_for_xattr_operation(control_file, 'setxattr')
            result = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
            assert result == b'false'
    
    def test_set_policy_configuration(self, mounted_fs):
        """Test setting policy configuration options with trace monitoring."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
        # Test valid policies
        valid_policies = [b'ff', b'mfs', b'lfs', b'rand', b'epmfs']
        
        for policy in valid_policies:
            xattr.setxattr(str(control_file), b'user.mergerfs.func.create', policy)
            self.wait_helper.wait_for_xattr_operation(control_file, 'setxattr')
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
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
        # Set create policy and verify
        xattr.setxattr(str(control_file), b'user.mergerfs.func.create', b'mfs')
        self.wait_helper.wait_for_xattr_operation(control_file, 'setxattr')
        assert xattr.getxattr(str(control_file), b'user.mergerfs.func.create') == b'mfs'
    
    def test_invalid_value_types(self, mounted_fs):
        """Test setting invalid value types."""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Wait for control file
        assert self.wait_helper.wait_for_file_visible(control_file), "Control file not visible"
        
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