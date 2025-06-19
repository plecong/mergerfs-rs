#!/usr/bin/env python3
"""Simple test for runtime configuration to debug issues."""

import os
import xattr
import pytest
from pathlib import Path


@pytest.mark.integration
class TestSimpleRuntimeConfig:
    """Simple runtime configuration test."""
    
    def test_get_version(self, mounted_fs):
        """Test getting version attribute."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test getting version
        try:
            version = xattr.getxattr(str(control_file), "user.mergerfs.version").decode()
            print(f"Version: {version}")
            assert version  # Should have some version string
        except Exception as e:
            print(f"Error getting version: {e}")
            assert False, f"Failed to get version: {e}"
    
    def test_get_create_policy(self, mounted_fs):
        """Test getting create policy."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test getting create policy
        try:
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            print(f"Create policy: {policy}")
            assert policy in ["ff", "mfs", "lfs", "lus", "rand", "epmfs", "eplfs", "pfrd"]
        except Exception as e:
            print(f"Error getting create policy: {e}")
            assert False, f"Failed to get create policy: {e}"
    
    def test_set_create_policy(self, mounted_fs):
        """Test setting create policy."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test setting create policy
        try:
            # Set to mfs
            xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"mfs")
            
            # Verify it was set
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            print(f"Policy after setting to mfs: {policy}")
            assert policy == "mfs"
            
            # Set back to ff
            xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"ff")
            
            # Verify it was set
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            print(f"Policy after setting to ff: {policy}")
            assert policy == "ff"
            
        except Exception as e:
            print(f"Error setting create policy: {e}")
            assert False, f"Failed to set create policy: {e}"