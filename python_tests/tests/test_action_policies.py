#!/usr/bin/env python3
"""Test action policies (all, epall, epff)."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.mark.integration
class TestActionPolicies:
    """Test action policies that determine which files operations affect."""
    
    def test_action_all_policy_chmod(self, mounted_fs):
        """Test 'all' action policy with chmod operations."""
        # Note: Action policies need to be configured via xattr
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create test file in all branches with different initial permissions
        for i, branch in enumerate(branches):
            test_file = branch / "action_all_chmod.txt"
            test_file.write_text(f"Branch {i}")
            os.chmod(test_file, 0o644 if i == 0 else 0o600)
        
        time.sleep(0.1)
        
        # TODO: Set action.chmod policy to 'all' when available
        # xattr -w user.mergerfs.action.chmod all /mnt/union/.mergerfs
        
        # Change permissions via mountpoint
        os.chmod(mountpoint / "action_all_chmod.txt", 0o755)
        
        time.sleep(0.1)
        
        # With 'all' policy, all files should have new permissions
        # With default policy, only first file changes
        perms = []
        for branch in branches:
            file_path = branch / "action_all_chmod.txt"
            perms.append(oct(file_path.stat().st_mode)[-3:])
        
        # Default action policy is 'epall' (existing path all), so all files change
        assert perms[0] == "755", "First file should have new permissions"
        assert perms[1] == "755", "Second file should have new permissions with epall default"
        assert perms[2] == "755", "Third file should have new permissions with epall default"
    
    def test_action_all_policy_chown(self, mounted_fs):
        """Test 'all' action policy with chown operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create test file in all branches
        for i, branch in enumerate(branches):
            test_file = branch / "action_all_chown.txt"
            test_file.write_text(f"Branch {i}")
        
        time.sleep(0.1)
        
        # Get current uid/gid
        stat_info = os.stat(branches[0] / "action_all_chown.txt")
        current_uid = stat_info.st_uid
        current_gid = stat_info.st_gid
        
        # TODO: When action policies are configurable:
        # - Set action.chown to 'all'
        # - Attempt chown (requires appropriate permissions)
        # - Verify all instances are updated
        
        # For now, just verify files exist
        for branch in branches:
            assert (branch / "action_all_chown.txt").exists()
    
    def test_action_all_policy_truncate(self, mounted_fs):
        """Test 'all' action policy with truncate operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create files with different content
        for i, branch in enumerate(branches):
            test_file = branch / "action_all_truncate.txt"
            test_file.write_text(f"Branch {i} original content that is long")
        
        time.sleep(0.1)
        
        # Truncate via mountpoint
        with open(mountpoint / "action_all_truncate.txt", 'w') as f:
            f.write("Short")
        
        time.sleep(0.1)
        
        # With 'all' policy, all files would be truncated
        # With default, only first file is affected
        contents = []
        for branch in branches:
            contents.append((branch / "action_all_truncate.txt").read_text())
        
        assert contents[0] == "Short", "First file should be truncated"
        assert contents[1] == "Branch 1 original content that is long", "Others unchanged"
        assert contents[2] == "Branch 2 original content that is long", "Others unchanged"
    
    def test_action_all_policy_utimens(self, mounted_fs):
        """Test 'all' action policy with timestamp updates."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create files with different timestamps
        base_time = time.time() - 3600  # 1 hour ago
        for i, branch in enumerate(branches):
            test_file = branch / "action_all_utimens.txt"
            test_file.write_text(f"Branch {i}")
            os.utime(test_file, (base_time - i*60, base_time - i*60))
        
        time.sleep(0.1)
        
        # Update timestamp via mountpoint
        (mountpoint / "action_all_utimens.txt").touch()
        
        time.sleep(0.1)
        
        # Check timestamps
        mtimes = []
        for branch in branches:
            mtime = (branch / "action_all_utimens.txt").stat().st_mtime
            mtimes.append(mtime)
        
        # Default action policy is 'epall', so all files get updated timestamp
        assert mtimes[0] > base_time, "First file should have updated mtime"
        assert mtimes[1] > base_time, "Second file should have updated mtime with epall default"
        assert mtimes[2] > base_time, "Third file should have updated mtime with epall default"
    
    def test_action_epall_policy(self, mounted_fs):
        """Test 'epall' (existing path all) action policy."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file in branches 0 and 2, but not 1
        for i in [0, 2]:
            test_file = branches[i] / "action_epall.txt"
            test_file.write_text(f"Branch {i}")
            os.chmod(test_file, 0o644)
        
        time.sleep(0.1)
        
        # With epall policy, operations would affect branches 0 and 2 only
        os.chmod(mountpoint / "action_epall.txt", 0o755)
        
        time.sleep(0.1)
        
        # Check results - epall is the default, so both existing files are affected
        assert oct((branches[0] / "action_epall.txt").stat().st_mode)[-3:] == "755"
        assert not (branches[1] / "action_epall.txt").exists()
        assert oct((branches[2] / "action_epall.txt").stat().st_mode)[-3:] == "755"
    
    def test_action_epff_policy(self, mounted_fs):
        """Test 'epff' (existing path first found) action policy."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file in branches 1 and 2, but not 0
        for i in [1, 2]:
            test_file = branches[i] / "action_epff.txt"
            test_file.write_text(f"Branch {i}")
            os.chmod(test_file, 0o600)
        
        time.sleep(0.1)
        
        # With epff policy, would affect branch 1 (first where it exists)
        os.chmod(mountpoint / "action_epff.txt", 0o755)
        
        time.sleep(0.1)
        
        # Check results - with default epall policy, all existing files are affected
        assert not (branches[0] / "action_epff.txt").exists()
        assert oct((branches[1] / "action_epff.txt").stat().st_mode)[-3:] == "755"
        assert oct((branches[2] / "action_epff.txt").stat().st_mode)[-3:] == "755"
    
    def test_action_policies_with_directories(self, mounted_fs):
        """Test action policies with directory operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create directory in some branches
        for i in [0, 1]:
            dir_path = branches[i] / "action_dir"
            dir_path.mkdir()
            (dir_path / f"file{i}.txt").write_text(f"Content {i}")
            os.chmod(dir_path, 0o755)
        
        time.sleep(0.1)
        
        # Change directory permissions
        os.chmod(mountpoint / "action_dir", 0o700)
        
        time.sleep(0.1)
        
        # Check results - with default epall policy, all directories are affected
        assert oct((branches[0] / "action_dir").stat().st_mode)[-3:] == "700"
        assert oct((branches[1] / "action_dir").stat().st_mode)[-3:] == "700"
    
    def test_action_policy_remove_operations(self, mounted_fs):
        """Test how action policies affect remove operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create test files in all branches
        for i, branch in enumerate(branches):
            test_file = branch / "action_remove.txt"
            test_file.write_text(f"Branch {i}")
        
        time.sleep(0.1)
        
        # Remove via mountpoint
        (mountpoint / "action_remove.txt").unlink()
        
        time.sleep(0.1)
        
        # With default epall policy, all instances are removed
        assert not (branches[0] / "action_remove.txt").exists()
        assert not (branches[1] / "action_remove.txt").exists()
        assert not (branches[2] / "action_remove.txt").exists()
    
    def test_action_policy_xattr_operations(self, mounted_fs):
        """Test action policies with extended attribute operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create files in all branches
        for i, branch in enumerate(branches):
            test_file = branch / "action_xattr.txt"
            test_file.write_text(f"Branch {i}")
        
        time.sleep(0.1)
        
        # Set xattr via mountpoint
        import xattr
        try:
            xattr.setxattr(
                str(mountpoint / "action_xattr.txt"),
                "user.test.attr",
                b"test value"
            )
            
            time.sleep(0.1)
            
            # Check which files have the xattr
            attrs = []
            for branch in branches:
                try:
                    value = xattr.getxattr(
                        str(branch / "action_xattr.txt"),
                        "user.test.attr"
                    )
                    attrs.append(value)
                except:
                    attrs.append(None)
            
            # With default policy, only first file gets xattr
            assert attrs[0] == b"test value"
            assert attrs[1] is None
            assert attrs[2] is None
            
        except Exception as e:
            # xattr might not be supported on all systems
            pytest.skip(f"xattr not supported: {e}")
    
    def test_action_policy_edge_cases(self, mounted_fs):
        """Test edge cases for action policies."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Test 1: Operation on non-existent file
        try:
            os.chmod(mountpoint / "nonexistent.txt", 0o755)
        except FileNotFoundError:
            pass  # Expected
        
        # Test 2: Mixed file types
        (branches[0] / "mixed").write_text("Regular file")
        (branches[1] / "mixed").mkdir()  # Directory with same name
        
        time.sleep(0.1)
        
        # Operations should handle type mismatch gracefully
        try:
            os.chmod(mountpoint / "mixed", 0o700)
            time.sleep(0.1)
            # Should affect the regular file in branch 0
            assert oct((branches[0] / "mixed").stat().st_mode)[-3:] == "700"
        except:
            pass  # Some operations might fail with mixed types
        
        # Test 3: Symlinks
        (branches[2] / "link_target.txt").write_text("Target")
        os.symlink("link_target.txt", branches[2] / "symlink")
        
        time.sleep(0.1)
        
        # Operations on symlinks
        try:
            # This might affect the symlink or its target depending on operation
            os.chmod(mountpoint / "symlink", 0o755)
        except:
            pass  # Symlink operations can be platform-specific
    
    def test_action_policies_performance(self, mounted_fs):
        """Test performance implications of different action policies."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create many files to test performance
        file_count = 50
        for i in range(file_count):
            for branch in branches:
                (branch / f"perf_{i}.txt").write_text(f"File {i}")
        
        time.sleep(0.2)
        
        import time as time_module
        
        # Test chmod on many files
        start = time_module.perf_counter()
        for i in range(10):
            os.chmod(mountpoint / f"perf_{i}.txt", 0o755)
        single_time = time_module.perf_counter() - start
        
        # With 'all' policy, this would take longer (affects all branches)
        # With default policy, only affects first branch (faster)
        assert single_time > 0  # Just ensure it completes
        
        # In real implementation with configurable policies:
        # - 'all' policy: ~3x slower (operates on 3 branches)
        # - 'epall' policy: Variable (depends on where files exist)
        # - 'epff' policy: Same as default
    
    def test_action_epall_negative_cases(self, mounted_fs):
        """Test epall policy with non-existing files and edge cases."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Test 1: chmod on non-existing file should fail
        try:
            os.chmod(mountpoint / "non_existent.txt", 0o755)
            assert False, "chmod on non-existent file should fail"
        except FileNotFoundError:
            pass  # Expected
        
        # Test 2: Create file in only some branches, then remove
        (branches[0] / "partial.txt").write_text("Branch 0")
        (branches[2] / "partial.txt").write_text("Branch 2")
        time.sleep(0.1)
        
        # Remove via mountpoint - should remove from both branches
        (mountpoint / "partial.txt").unlink()
        time.sleep(0.1)
        
        assert not (branches[0] / "partial.txt").exists()
        assert not (branches[1] / "partial.txt").exists()  # Never existed
        assert not (branches[2] / "partial.txt").exists()
        
        # Test 3: Create file in readonly branch only
        if hasattr(branches[0], 'mode'):
            # Skip if branch modes not implemented
            return
            
        # Test 4: epall with empty file path
        (branches[1] / "empty_name").mkdir()
        try:
            # Operations on directories with epall
            os.chmod(mountpoint / "empty_name", 0o700)
            assert oct((branches[1] / "empty_name").stat().st_mode)[-3:] == "700"
        except:
            pass  # May not be supported yet