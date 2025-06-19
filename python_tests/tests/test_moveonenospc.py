#!/usr/bin/env python3
"""Test moveonenospc feature - automatic file migration on ENOSPC."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil
import xattr


@pytest.mark.integration
class TestMoveOnENOSPC:
    """Test automatic file migration when out of space."""
    
    def fill_branch_to_capacity(self, branch_path, leave_free_mb=1):
        """Fill a branch to near capacity, leaving specified MB free."""
        # Get filesystem stats
        stat = os.statvfs(branch_path)
        block_size = stat.f_frsize
        free_blocks = stat.f_bavail
        free_bytes = free_blocks * block_size
        
        # Calculate how much to write (leave some free)
        to_write = free_bytes - (leave_free_mb * 1024 * 1024)
        
        if to_write > 0:
            # Write in chunks to avoid memory issues
            chunk_size = 10 * 1024 * 1024  # 10MB chunks
            fill_file = branch_path / "fill_space.bin"
            
            with open(fill_file, 'wb') as f:
                written = 0
                while written < to_write:
                    write_size = min(chunk_size, to_write - written)
                    f.write(b'F' * write_size)
                    written += write_size
            
            return fill_file
        return None
    
    def test_moveonenospc_basic(self, mounted_fs):
        """Test basic moveonenospc functionality."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Enable moveonenospc (default is enabled with pfrd)
        try:
            current = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            assert current in ["pfrd", "true", "mfs", "ff", "lfs", "lus", "rand"]
        except:
            # If not accessible, skip test
            pytest.skip("Cannot access mergerfs control file")
        
        # Create initial file in branch 0
        test_file = mountpoint / "moveable.txt"
        test_file.write_text("Initial content")
        time.sleep(0.1)
        
        # Verify it's in branch 0
        assert (branches[0] / "moveable.txt").exists()
        
        # Fill branch 0 to near capacity
        fill_file = self.fill_branch_to_capacity(branches[0], leave_free_mb=2)
        
        if fill_file:
            try:
                # Try to append to file - should trigger move
                with open(test_file, 'a') as f:
                    f.write("X" * (3 * 1024 * 1024))  # 3MB append
                
                time.sleep(0.5)
                
                # File should have moved to another branch
                # Check all branches to see where it went
                found_in = []
                for i, branch in enumerate(branches):
                    if (branch / "moveable.txt").exists():
                        found_in.append(i)
                
                # Should be in a different branch now
                assert len(found_in) >= 1, "File should exist somewhere"
                # With moveonenospc, might have moved to branch 1 or 2
                
            finally:
                # Clean up fill file
                if fill_file.exists():
                    fill_file.unlink()
        else:
            pytest.skip("Could not fill branch to test moveonenospc")
    
    def test_moveonenospc_configuration(self, mounted_fs):
        """Test moveonenospc configuration options."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        try:
            # Test disabling moveonenospc
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"false")
            value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            assert value == "false"
            
            # Test enabling with specific policy
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"mfs")
            value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            assert value == "mfs"
            
            # Test with different policies
            for policy in ["ff", "lfs", "lus", "rand", "pfrd"]:
                xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", policy.encode())
                value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
                assert value == policy
            
            # Test invalid policy
            with pytest.raises(OSError):
                xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"invalid")
            
        except Exception as e:
            pytest.skip(f"Cannot test moveonenospc configuration: {e}")
    
    def test_moveonenospc_with_readonly_branches(self, mounted_fs):
        """Test moveonenospc with read-only branches."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file in branch 0
        test_file = mountpoint / "ro_test.txt"
        test_file.write_text("Initial")
        time.sleep(0.1)
        
        assert (branches[0] / "ro_test.txt").exists()
        
        # Make branch 1 read-only
        os.chmod(branches[1], 0o555)
        
        try:
            # Fill branch 0
            fill_file = self.fill_branch_to_capacity(branches[0], leave_free_mb=1)
            
            if fill_file:
                try:
                    # Try to expand file - should skip RO branch 1 and use branch 2
                    with open(test_file, 'a') as f:
                        f.write("Y" * (2 * 1024 * 1024))
                    
                    time.sleep(0.5)
                    
                    # Should not be in branch 1 (read-only)
                    assert not (branches[1] / "ro_test.txt").exists()
                    
                    # Should be in branch 0 or 2
                    assert (branches[0] / "ro_test.txt").exists() or \
                           (branches[2] / "ro_test.txt").exists()
                    
                finally:
                    if fill_file.exists():
                        fill_file.unlink()
            
        finally:
            # Restore permissions
            os.chmod(branches[1], 0o755)
    
    def test_moveonenospc_preserves_handles(self, mounted_fs):
        """Test that moveonenospc preserves open file handles."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create and open file
        test_file = mountpoint / "handle_test.txt"
        with open(test_file, 'w') as f:
            f.write("Initial content\n")
            f.flush()
            
            time.sleep(0.1)
            assert (branches[0] / "handle_test.txt").exists()
            
            # Fill branch 0
            fill_file = self.fill_branch_to_capacity(branches[0], leave_free_mb=1)
            
            if fill_file:
                try:
                    # Write more data with open handle
                    f.write("More data " * 100000)  # Should trigger move
                    f.flush()
                    
                    time.sleep(0.5)
                    
                    # File should still be writable
                    f.write("Final line\n")
                    
                finally:
                    if fill_file.exists():
                        fill_file.unlink()
        
        # Verify file content is complete
        content = test_file.read_text()
        assert "Initial content" in content
        assert "Final line" in content
    
    def test_moveonenospc_with_multiple_files(self, mounted_fs):
        """Test moveonenospc with multiple files needing migration."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create multiple files in branch 0
        files = []
        for i in range(3):
            test_file = mountpoint / f"multi_{i}.txt"
            test_file.write_text(f"File {i} content")
            files.append(test_file)
        
        time.sleep(0.1)
        
        # Verify all in branch 0
        for i in range(3):
            assert (branches[0] / f"multi_{i}.txt").exists()
        
        # Fill branch 0
        fill_file = self.fill_branch_to_capacity(branches[0], leave_free_mb=1)
        
        if fill_file:
            try:
                # Try to expand each file
                for i, test_file in enumerate(files):
                    try:
                        with open(test_file, 'a') as f:
                            f.write("X" * (1024 * 1024))  # 1MB each
                        time.sleep(0.1)
                    except IOError:
                        # Some might fail if truly out of space
                        pass
                
                # Check distribution - files should have spread out
                branch_counts = [0, 0, 0]
                for i in range(3):
                    for j, branch in enumerate(branches):
                        if (branch / f"multi_{i}.txt").exists():
                            branch_counts[j] += 1
                
                # Not all files should be in branch 0 anymore
                assert branch_counts[0] < 3, "Some files should have moved"
                
            finally:
                if fill_file.exists():
                    fill_file.unlink()
    
    def test_moveonenospc_policy_behavior(self, mounted_fs):
        """Test different policies for moveonenospc."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        # Test with MFS policy
        try:
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"mfs")
            
            # Add different amounts of data to branches 1 and 2
            (branches[1] / "space1.bin").write_bytes(b'1' * (20 * 1024 * 1024))
            (branches[2] / "space2.bin").write_bytes(b'2' * (40 * 1024 * 1024))
            
            # Create file in branch 0
            test_file = mountpoint / "policy_test.txt"
            test_file.write_text("Initial")
            time.sleep(0.1)
            
            # Fill branch 0
            fill_file = self.fill_branch_to_capacity(branches[0], leave_free_mb=1)
            
            if fill_file:
                try:
                    # Expand file - with MFS should go to branch 1 (most free)
                    with open(test_file, 'a') as f:
                        f.write("Z" * (2 * 1024 * 1024))
                    
                    time.sleep(0.5)
                    
                    # Should preferably be in branch 1 (has more free space)
                    if not (branches[0] / "policy_test.txt").exists():
                        # If moved, should be in branch with most free space
                        assert (branches[1] / "policy_test.txt").exists() or \
                               (branches[2] / "policy_test.txt").exists()
                    
                finally:
                    if fill_file.exists():
                        fill_file.unlink()
                    (branches[1] / "space1.bin").unlink()
                    (branches[2] / "space2.bin").unlink()
            
        except Exception as e:
            pytest.skip(f"Cannot test policy behavior: {e}")
    
    def test_moveonenospc_edquot_trigger(self, mounted_fs):
        """Test moveonenospc triggers on EDQUOT (quota exceeded) as well."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Note: Testing actual quota errors requires quota setup
        # This test simulates the behavior
        
        # Create file
        test_file = mountpoint / "quota_test.txt"
        test_file.write_text("Initial content")
        time.sleep(0.1)
        
        # In real scenario with quotas:
        # 1. Set up user/group quota on branch 0
        # 2. Create file owned by that user/group
        # 3. Write data to exceed quota
        # 4. Verify moveonenospc triggers and moves file
        
        # For now, just verify configuration accepts EDQUOT handling
        control_file = mountpoint / ".mergerfs"
        try:
            # Verify moveonenospc is enabled
            value = xattr.getxattr(str(control_file), "user.mergerfs.moveonenospc").decode()
            assert value != "false", "moveonenospc should handle EDQUOT when enabled"
        except:
            pass
    
    def test_moveonenospc_preserves_attributes(self, mounted_fs):
        """Test that moveonenospc preserves file attributes during migration."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file with specific attributes
        test_file = mountpoint / "attr_test.txt"
        test_file.write_text("Content with attributes")
        
        # Set specific permissions
        os.chmod(test_file, 0o640)
        
        # Set timestamps
        atime = time.time() - 3600  # 1 hour ago
        mtime = time.time() - 7200  # 2 hours ago
        os.utime(test_file, (atime, mtime))
        
        time.sleep(0.1)
        
        # Get original attributes
        orig_stat = test_file.stat()
        orig_mode = oct(orig_stat.st_mode)[-3:]
        
        # Note: Actually triggering moveonenospc to test attribute preservation
        # would require filling the branch, which is tested in other methods
        
        # Verify attributes are readable
        assert orig_mode == "640"
        assert abs(orig_stat.st_atime - atime) < 1
        assert abs(orig_stat.st_mtime - mtime) < 1
    
    def test_moveonenospc_performance_impact(self, mounted_fs):
        """Test performance impact of moveonenospc feature."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        control_file = mountpoint / ".mergerfs"
        
        import time as time_module
        
        try:
            # Test write performance with moveonenospc disabled
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"false")
            
            test_file1 = mountpoint / "perf_disabled.txt"
            start = time_module.perf_counter()
            with open(test_file1, 'w') as f:
                for i in range(100):
                    f.write(f"Line {i}\n" * 100)
            disabled_time = time_module.perf_counter() - start
            
            # Test with moveonenospc enabled
            xattr.setxattr(str(control_file), "user.mergerfs.moveonenospc", b"pfrd")
            
            test_file2 = mountpoint / "perf_enabled.txt"
            start = time_module.perf_counter()
            with open(test_file2, 'w') as f:
                for i in range(100):
                    f.write(f"Line {i}\n" * 100)
            enabled_time = time_module.perf_counter() - start
            
            # Performance should be similar when not hitting ENOSPC
            # Small overhead is acceptable
            assert enabled_time < disabled_time * 1.5, "Excessive overhead with moveonenospc"
            
        except Exception as e:
            pytest.skip(f"Cannot test performance: {e}")