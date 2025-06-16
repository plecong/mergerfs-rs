#!/usr/bin/env python3
"""
Enhanced integration tests for runtime configuration via xattr interface.

This version uses trace monitoring instead of hardcoded sleeps for better reliability
and faster test execution.
"""

import os
import xattr
import pytest
from pathlib import Path
from typing import Tuple, List


@pytest.mark.integration
class TestRuntimeConfigEnhanced:
    """Test runtime configuration functionality with trace monitoring."""
    
    def test_control_file_exists_traced(self, mounted_fs_with_trace, smart_wait):
        """Test that the control file .mergerfs exists (trace-monitored version)."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        # No need for sleep - trace monitoring ensures mount is ready
        
        # File should exist
        assert control_file.exists()
        
        # Should be a regular file
        assert control_file.is_file()
        
        # Check file stats
        stat_info = control_file.stat()
        # Check if readable (0o444 = readable by all)
        assert stat_info.st_mode & 0o400
        
        # If trace monitor available, show what operations occurred
        if trace_monitor:
            lookup_count = trace_monitor.get_operation_count('lookup')
            getattr_count = trace_monitor.get_operation_count('getattr')
            print(f"Operations: {lookup_count} lookups, {getattr_count} getattrs")
    
    def test_list_configuration_options_traced(self, mounted_fs_with_trace, smart_wait):
        """Test listing all configuration options with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        # Clear previous operations if trace available
        if trace_monitor:
            trace_monitor.clear_completed()
        
        # List all xattrs
        attrs = xattr.listxattr(str(control_file))
        
        # Wait for listxattr operation to complete if trace available
        if trace_monitor:
            success = smart_wait.wait_for_xattr_operation(control_file, 'listxattr', timeout=2.0)
            assert success, "listxattr operation did not complete"
        
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
        
        if trace_monitor:
            print(f"Listed {len(attr_names)} attributes via {trace_monitor.get_operation_count('listxattr')} operations")
    
    def test_get_configuration_values_traced(self, mounted_fs_with_trace, smart_wait):
        """Test getting configuration values with operation tracking."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        # Track getxattr operations
        if trace_monitor:
            trace_monitor.clear_completed()
        
        # Get version (read-only)
        version = xattr.getxattr(str(control_file), b'user.mergerfs.version')
        assert version  # Should have a version string
        
        # Get PID (read-only)
        pid = xattr.getxattr(str(control_file), b'user.mergerfs.pid')
        assert pid.decode('utf-8').isdigit()  # Should be a number
        
        # Get create policy
        policy = xattr.getxattr(str(control_file), b'user.mergerfs.func.create')
        assert policy.decode('utf-8') in ['ff', 'mfs', 'lfs', 'rand', 'epmfs']
        
        # Get boolean options
        moveonenospc = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        assert moveonenospc.decode('utf-8') in ['true', 'false']
        
        if trace_monitor:
            getxattr_count = trace_monitor.get_operation_count('getxattr')
            print(f"Performed {getxattr_count} getxattr operations")
            
            # Check for any failed operations
            failed_ops = trace_monitor.get_failed_operations()
            if failed_ops:
                print(f"Warning: {len(failed_ops)} operations failed")
    
    def test_set_boolean_configuration_traced(self, mounted_fs_with_trace, smart_wait):
        """Test setting boolean configuration options with trace verification."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        # Get initial value
        initial = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        initial_bool = initial.decode('utf-8') == 'true'
        
        # Clear operations before the set
        if trace_monitor:
            trace_monitor.clear_completed()
        
        # Toggle the value
        new_value = b'false' if initial_bool else b'true'
        xattr.setxattr(str(control_file), b'user.mergerfs.moveonenospc', new_value)
        
        # Wait for setxattr to complete
        if trace_monitor:
            success = smart_wait.wait_for_xattr_operation(control_file, 'setxattr', timeout=2.0)
            assert success, "setxattr operation did not complete"
        
        # Verify it changed
        current = xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc')
        assert current == new_value
        
        if trace_monitor:
            # Verify the operations occurred in the right order
            ops = trace_monitor.completed_operations
            setxattr_ops = [op for op in ops if op.operation == 'setxattr']
            getxattr_ops = [op for op in ops if op.operation == 'getxattr']
            
            assert len(setxattr_ops) >= 1, "Expected at least one setxattr operation"
            assert len(getxattr_ops) >= 1, "Expected at least one getxattr operation after set"
            
            print(f"Configuration change verified with {len(setxattr_ops)} set and {len(getxattr_ops)} get operations")
    
    def test_set_create_policy_traced(self, mounted_fs_with_trace, smart_wait):
        """Test changing create policy at runtime with operation verification."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        # Test different policies
        policies = [b'ff', b'mfs', b'lfs', b'rand']
        
        for policy in policies:
            if trace_monitor:
                trace_monitor.clear_completed()
                
            # Set the policy
            xattr.setxattr(str(control_file), b'user.mergerfs.func.create', policy)
            
            # Wait for operation if trace available
            if trace_monitor:
                success = smart_wait.wait_for_xattr_operation(control_file, 'setxattr', timeout=2.0)
                assert success, f"Failed to set policy to {policy}"
            
            # Verify it was set
            current = xattr.getxattr(str(control_file), b'user.mergerfs.func.create')
            assert current == policy, f"Policy mismatch: expected {policy}, got {current}"
            
        if trace_monitor:
            total_sets = sum(1 for op in trace_monitor.completed_operations if op.operation == 'setxattr')
            print(f"Successfully changed policy {len(policies)} times with {total_sets} total setxattr operations")
    
    def test_concurrent_config_changes_traced(self, mounted_fs_with_trace):
        """Test multiple configuration changes with trace monitoring."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        control_file = mountpoint / ".mergerfs"
        
        if trace_monitor:
            trace_monitor.clear_completed()
        
        # Make multiple configuration changes rapidly
        changes = [
            (b'user.mergerfs.moveonenospc', b'true'),
            (b'user.mergerfs.direct_io', b'false'),
            (b'user.mergerfs.func.create', b'mfs'),
            (b'user.mergerfs.func.create', b'ff'),
            (b'user.mergerfs.moveonenospc', b'false'),
        ]
        
        for attr, value in changes:
            xattr.setxattr(str(control_file), attr, value)
            
        if trace_monitor:
            # Wait for all setxattr operations to complete
            ops = trace_monitor.wait_for_operations(['setxattr'] * len(changes), timeout=3.0)
            assert len(ops) >= len(changes), f"Expected {len(changes)} operations, got {len(ops)}"
            
            # Verify no operations failed
            failed = trace_monitor.get_failed_operations()
            assert len(failed) == 0, f"Found {len(failed)} failed operations"
            
            print(f"Successfully completed {len(changes)} concurrent configuration changes")
        
        # Verify final values
        assert xattr.getxattr(str(control_file), b'user.mergerfs.moveonenospc') == b'false'
        assert xattr.getxattr(str(control_file), b'user.mergerfs.func.create') == b'ff'


def test_trace_monitoring_benefits():
    """Demonstrate the benefits of trace monitoring for config tests."""
    print("\n" + "="*60)
    print("BENEFITS OF TRACE MONITORING FOR CONFIG TESTS")
    print("="*60)
    print("\n1. No hardcoded sleeps needed:")
    print("   - Mount readiness detected automatically")
    print("   - Operations complete as fast as possible")
    print("\n2. Better debugging:")
    print("   - See exact FUSE operations performed")
    print("   - Identify failed operations immediately")
    print("\n3. Verification of operation order:")
    print("   - Ensure setxattr happens before getxattr")
    print("   - Track concurrent operations")
    print("\n4. Performance insights:")
    print("   - Count operations performed")
    print("   - Identify unexpected operations")
    print("\nTo enable: export FUSE_TRACE=1")
    print("="*60)


if __name__ == "__main__":
    # Run with trace monitoring
    os.environ['FUSE_TRACE'] = '1'
    pytest.main([__file__, "-v", "-s"])