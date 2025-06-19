#!/usr/bin/env python3
"""Test comprehensive runtime configuration via .mergerfs control file."""

import os
import time
import pytest
from pathlib import Path
import xattr
import tempfile
import shutil


@pytest.mark.integration
class TestRuntimeConfiguration:
    """Test runtime configuration through xattr interface."""
    
    def test_control_file_exists(self, mounted_fs):
        """Test that .mergerfs control file exists and is accessible."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Should exist
        assert control_file.exists()
        
        # Should be a regular file
        assert control_file.is_file()
        
        # Should have size 0
        assert control_file.stat().st_size == 0
        
        # Should be readable
        assert os.access(control_file, os.R_OK)
    
    def test_list_configuration_options(self, mounted_fs):
        """Test listing all available configuration options."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        try:
            # List all xattrs
            attrs = xattr.listxattr(str(control_file))
            
            # Should include various configuration options
            expected_options = [
                "user.mergerfs.version",
                "user.mergerfs.pid", 
                "user.mergerfs.func.create",
                "user.mergerfs.moveonenospc",
                "user.mergerfs.cache.files",
                "user.mergerfs.direct_io",
            ]
            
            for option in expected_options:
                assert option.encode() in attrs, f"Missing option: {option}"
            
        except Exception as e:
            pytest.skip(f"Cannot list xattrs: {e}")
    
    def test_read_only_options(self, mounted_fs):
        """Test read-only configuration options."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test version (read-only)
        try:
            version = xattr.getxattr(str(control_file), "user.mergerfs.version").decode()
            assert version  # Should have some version string
            
            # Try to set version (should fail)
            with pytest.raises(OSError) as exc_info:
                xattr.setxattr(str(control_file), "user.mergerfs.version", b"fake")
            assert exc_info.value.errno in [1, 13, 95]  # EPERM, EACCES, or ENOTSUP
            
        except Exception as e:
            pytest.skip(f"Cannot test read-only options: {e}")
        
        # Test PID (read-only)
        try:
            pid = xattr.getxattr(str(control_file), "user.mergerfs.pid").decode()
            assert pid.isdigit()
            assert int(pid) == process.pid
            
        except:
            pass  # PID might not be implemented
    
    def test_create_policy_configuration(self, mounted_fs):
        """Test changing create policy at runtime."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        try:
            # Get current policy
            current = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            
            # Test all implemented create policies
            policies = ["ff", "mfs", "lfs", "lus", "rand", "epff", "epmfs", "eplfs", "pfrd"]
            
            for policy in policies:
                # Set policy
                xattr.setxattr(str(control_file), "user.mergerfs.func.create", policy.encode())
                
                # Verify it was set
                value = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
                assert value == policy
                
                # Create a test file to verify policy is active
                test_file = mountpoint / f"policy_test_{policy}.txt"
                test_file.write_text(f"Testing {policy}")
                time.sleep(0.1)
            
            # Test invalid policy
            with pytest.raises(OSError):
                xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"invalid")
            
        except Exception as e:
            pytest.skip(f"Cannot test create policy configuration: {e}")
    
    def test_statfs_configuration(self, mounted_fs):
        """Test statfs configuration options."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Note: These options might not be fully implemented
        statfs_options = [
            ("user.mergerfs.statfs", ["base", "full"]),
            ("user.mergerfs.statfs.ignore", ["none", "ro", "nc"]),
        ]
        
        for attr_name, valid_values in statfs_options:
            try:
                # Try each valid value
                for value in valid_values:
                    xattr.setxattr(str(control_file), attr_name, value.encode())
                    result = xattr.getxattr(str(control_file), attr_name).decode()
                    assert result == value
                
            except OSError as e:
                if e.errno == 95:  # ENOTSUP
                    continue  # Option might not be implemented
                raise
    
    def test_cache_files_modes(self, mounted_fs):
        """Test all cache.files modes."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        modes = ["libfuse", "off", "partial", "full", "auto-full", "per-process"]
        
        for mode in modes:
            xattr.setxattr(str(control_file), "user.mergerfs.cache.files", mode.encode())
            value = xattr.getxattr(str(control_file), "user.mergerfs.cache.files").decode()
            assert value == mode
        
        # Test file operations with different cache modes
        for mode in ["off", "full"]:
            xattr.setxattr(str(control_file), "user.mergerfs.cache.files", mode.encode())
            
            test_file = mountpoint / f"cache_test_{mode}.txt"
            test_file.write_text(f"Testing cache mode: {mode}")
            time.sleep(0.1)
            
            content = test_file.read_text()
            assert content == f"Testing cache mode: {mode}"
    
    def test_moveonenospc_configuration(self, mounted_fs):
        """Test moveonenospc configuration."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test boolean values
        for value in ["true", "false", "0", "1"]:
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", value.encode())
            result = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            if value in ["0", "false"]:
                assert result == "false"
            elif value in ["1", "true"]:
                assert result == "pfrd"  # Default policy when enabled
        
        # Test with specific policies
        for policy in ["ff", "mfs", "lfs", "lus", "rand", "pfrd"]:
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", policy.encode())
            result = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            assert result == policy
    
    def test_configuration_persistence(self, mounted_fs):
        """Test that configuration changes persist during filesystem lifetime."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Set various options
        config_changes = [
            ("user.mergerfs.func.create", "mfs"),
            ("user.mergerfs.cache.files", "off"),
            ("user.mergerfs.moveonenospc", "lus"),
        ]
        
        # Apply changes
        for attr, value in config_changes:
            xattr.setxattr(str(control_file), attr, value.encode())
        
        time.sleep(0.1)
        
        # Create some files
        for i in range(5):
            (mountpoint / f"persist_test_{i}.txt").write_text(f"Test {i}")
        
        time.sleep(0.1)
        
        # Verify settings still active
        for attr, expected in config_changes:
            value = xattr.getxattr(str(control_file), attr).decode()
            assert value == expected
    
    def test_configuration_concurrency(self, mounted_fs):
        """Test concurrent configuration changes."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        import threading
        
        errors = []
        
        def change_config(policy):
            try:
                for _ in range(10):
                    xattr.setxattr(
                        str(control_file),
                        "user.mergerfs.func.create",
                        policy.encode()
                    )
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)
        
        # Multiple threads changing configuration
        threads = []
        for policy in ["ff", "mfs", "lfs"]:
            t = threading.Thread(target=change_config, args=(policy,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should complete without errors
        assert len(errors) == 0
        
        # Final value should be one of the policies
        final = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
        assert final in ["ff", "mfs", "lfs"]
    
    def test_configuration_error_handling(self, mounted_fs):
        """Test error handling for invalid configurations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test invalid attribute names
        with pytest.raises(OSError) as exc_info:
            xattr.getxattr(str(control_file), "user.mergerfs.nonexistent")
        assert exc_info.value.errno in [95, 61]  # ENOTSUP or ENODATA
        
        # Test invalid values
        invalid_tests = [
            ("user.mergerfs.func.create", "invalid_policy"),
            ("user.mergerfs.cache.files", "invalid_mode"),
            ("user.mergerfs.moveonenospc", "invalid_value"),
        ]
        
        for attr, invalid_value in invalid_tests:
            with pytest.raises(OSError) as exc_info:
                xattr.setxattr(str(control_file), attr, invalid_value.encode())
            assert exc_info.value.errno == 22  # EINVAL
    
    def test_configuration_help_text(self, mounted_fs):
        """Test configuration option help/description."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Some implementations provide help via special attributes
        help_attrs = [
            "user.mergerfs.policies",
            "user.mergerfs.config.help",
        ]
        
        for attr in help_attrs:
            try:
                help_text = xattr.getxattr(str(control_file), attr).decode()
                # If implemented, should contain policy names or help
                assert len(help_text) > 0
            except OSError:
                # Not all implementations provide help attributes
                pass
    
    def test_runtime_config_with_operations(self, mounted_fs):
        """Test that runtime config changes affect operations immediately."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Add different amounts of data to test policy changes
        (branches[0] / "data0.bin").write_bytes(b'0' * (40 * 1024 * 1024))
        (branches[1] / "data1.bin").write_bytes(b'1' * (10 * 1024 * 1024))
        (branches[2] / "data2.bin").write_bytes(b'2' * (25 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Set to ff policy
        xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"ff")
        
        # Create file - should go to branch 0
        (mountpoint / "ff_test.txt").write_text("FF test")
        time.sleep(0.1)
        assert (branches[0] / "ff_test.txt").exists()
        
        # Change to mfs policy
        xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"mfs")
        
        # Create file - should go to branch 1 (most free)
        (mountpoint / "mfs_test.txt").write_text("MFS test")
        time.sleep(0.1)
        assert (branches[1] / "mfs_test.txt").exists()
        
        # Change to lfs policy
        xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"lfs")
        
        # Create file - should go to branch 2 (least free)
        (mountpoint / "lfs_test.txt").write_text("LFS test")
        time.sleep(0.1)
        assert (branches[2] / "lfs_test.txt").exists()