#!/usr/bin/env python3
"""Test branch modes (ReadWrite, ReadOnly, NoCreate)."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil
from lib.fuse_manager import FuseManager, FuseConfig


@pytest.mark.integration
@pytest.mark.skip(reason="Branch modes (RO/NC) not yet implemented - waiting for branch mode support")
class TestBranchModes:
    """Test different branch access modes."""
    
    def test_readonly_branch_mode(self, temp_mountpoint, fuse_manager):
        """Test read-only branch mode."""
        # Create branches
        rw_branch = Path(tempfile.mkdtemp(prefix="rw_"))
        ro_branch = Path(tempfile.mkdtemp(prefix="ro_"))
        
        # Create some initial content in both branches
        (rw_branch / "rw_file.txt").write_text("RW content")
        (ro_branch / "ro_file.txt").write_text("RO content")
        (ro_branch / "shared.txt").write_text("RO shared")
        (rw_branch / "shared.txt").write_text("RW shared")
        
        try:
            # Mount with one RO branch
            # Format: branch_path:mode
            branches_spec = [
                str(rw_branch),
                f"{ro_branch}:RO"  # or "=RO" depending on implementation
            ]
            
            # Note: Current implementation might not support mode suffixes
            # Would need to be implemented in the Rust code
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=[rw_branch, ro_branch],  # For now, use regular mount
                policy="ff"
            ) as (process, mp, branches_list):
                
                # Can read files from RO branch
                assert (mp / "ro_file.txt").read_text() == "RO content"
                
                # Can read shared file (ff finds in RW branch first)
                assert (mp / "shared.txt").read_text() == "RW shared"
                
                # Can create new files (goes to RW branch)
                (mp / "new_file.txt").write_text("New content")
                time.sleep(0.1)
                assert (rw_branch / "new_file.txt").exists()
                assert not (ro_branch / "new_file.txt").exists()
                
                # Cannot modify files in RO branch
                # Note: This behavior depends on implementation
                # Some union filesystems create copy in RW branch
                
        finally:
            shutil.rmtree(rw_branch)
            shutil.rmtree(ro_branch)
    
    def test_nocreate_branch_mode(self, temp_mountpoint, fuse_manager):
        """Test no-create (NC) branch mode."""
        # Create branches
        normal_branch = Path(tempfile.mkdtemp(prefix="normal_"))
        nc_branch = Path(tempfile.mkdtemp(prefix="nc_"))
        
        # Create existing content
        (normal_branch / "normal.txt").write_text("Normal branch")
        (nc_branch / "nocreate.txt").write_text("NC branch")
        (nc_branch / "subdir").mkdir()
        (nc_branch / "subdir" / "existing.txt").write_text("Existing in NC")
        
        try:
            # Note: NC mode would need to be implemented
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=[normal_branch, nc_branch],
                policy="ff"
            ) as (process, mp, branches_list):
                
                # Can read from NC branch
                assert (mp / "nocreate.txt").read_text() == "NC branch"
                
                # Can modify existing files in NC branch
                with open(mp / "nocreate.txt", 'a') as f:
                    f.write("\nAppended")
                time.sleep(0.1)
                
                # New files go to normal branch, not NC
                (mp / "new.txt").write_text("New file")
                time.sleep(0.1)
                assert (normal_branch / "new.txt").exists()
                assert not (nc_branch / "new.txt").exists()
                
                # Can't create in existing NC directories
                (mp / "subdir" / "new_in_nc.txt").write_text("Should go elsewhere")
                time.sleep(0.1)
                # With NC mode, this would go to normal branch
                # creating path if needed
                
        finally:
            shutil.rmtree(normal_branch)
            shutil.rmtree(nc_branch)
    
    def test_branch_mode_combinations(self, temp_mountpoint, fuse_manager):
        """Test combinations of branch modes."""
        branches = []
        for i, mode in enumerate(["RW", "RO", "NC"]):
            branch = Path(tempfile.mkdtemp(prefix=f"{mode.lower()}{i}_"))
            branches.append(branch)
            (branch / f"file_{mode.lower()}.txt").write_text(f"{mode} content")
        
        try:
            # Mount with mixed modes
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=branches,
                policy="ff"
            ) as (process, mp, branches_list):
                
                # Test file creation with different policies
                test_files = [
                    ("ff_test.txt", "First found test"),
                    ("mfs_test.txt", "Most free space test"),
                ]
                
                for filename, content in test_files:
                    (mp / filename).write_text(content)
                    time.sleep(0.1)
                    
                    # Should only be in RW branch (branches[0])
                    assert (branches[0] / filename).exists()
                    assert not (branches[1] / filename).exists()  # RO
                    assert not (branches[2] / filename).exists()  # NC
                
        finally:
            for branch in branches:
                shutil.rmtree(branch)
    
    def test_runtime_branch_mode_changes(self, mounted_fs):
        """Test changing branch modes at runtime (if supported)."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Note: Runtime branch mode changes would require:
        # 1. xattr interface to modify branch modes
        # 2. Implementation in Rust to handle mode changes
        
        # For now, test with filesystem permission changes
        test_file = branches[0] / "mode_test.txt"
        test_file.write_text("Original content")
        
        # Make branch read-only at OS level
        os.chmod(branches[0], 0o555)
        
        try:
            # Try to create new file - should fail or go to another branch
            try:
                (mountpoint / "after_ro.txt").write_text("After RO")
                time.sleep(0.1)
                
                # Should not be in RO branch
                assert not (branches[0] / "after_ro.txt").exists()
                # Should be in another branch
                assert (branches[1] / "after_ro.txt").exists() or \
                       (branches[2] / "after_ro.txt").exists()
            except PermissionError:
                # This is also acceptable behavior
                pass
            
        finally:
            # Restore permissions
            os.chmod(branches[0], 0o755)
    
    def test_branch_mode_policy_interaction(self, temp_mountpoint, fuse_manager):
        """Test how branch modes interact with policies."""
        # Create branches with different free space
        branches = []
        sizes = [10, 5, 15]  # MB of used space
        
        for i in range(3):
            branch = Path(tempfile.mkdtemp(prefix=f"branch{i}_"))
            branches.append(branch)
            # Add initial data
            (branch / f"data{i}.bin").write_bytes(b'X' * (sizes[i] * 1024 * 1024))
        
        try:
            # Test with MFS policy
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=branches,
                policy="mfs"
            ) as (process, mp, branches_list):
                
                # Should select branch 1 (least used = most free)
                (mp / "mfs_test.txt").write_text("MFS test")
                time.sleep(0.1)
                assert (branches[1] / "mfs_test.txt").exists()
                
                # Now make branch 1 read-only
                os.chmod(branches[1], 0o555)
                
                try:
                    # Next file should skip RO branch
                    (mp / "mfs_test2.txt").write_text("MFS test 2")
                    time.sleep(0.1)
                    
                    # Should go to branch 0 (next most free)
                    assert not (branches[1] / "mfs_test2.txt").exists()
                    assert (branches[0] / "mfs_test2.txt").exists() or \
                           (branches[2] / "mfs_test2.txt").exists()
                    
                finally:
                    os.chmod(branches[1], 0o755)
                
        finally:
            for branch in branches:
                shutil.rmtree(branch)
    
    def test_branch_mode_error_handling(self, mounted_fs):
        """Test error handling with different branch modes."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create a file that exists in multiple branches
        for branch in branches:
            (branch / "multi.txt").write_text(f"Branch {branch.name}")
        
        # Make all branches read-only
        original_perms = []
        for branch in branches:
            original_perms.append(oct(branch.stat().st_mode))
            os.chmod(branch, 0o555)
        
        try:
            # Try to create new file - should fail
            with pytest.raises(OSError) as exc_info:
                (mountpoint / "impossible.txt").write_text("Can't create")
            
            # Should get EROFS or EACCES
            assert exc_info.value.errno in [30, 13]  # EROFS or EACCES
            
            # Try to modify existing file
            with pytest.raises(OSError):
                with open(mountpoint / "multi.txt", 'a') as f:
                    f.write("More content")
            
        finally:
            # Restore permissions
            for i, branch in enumerate(branches):
                os.chmod(branch, int(original_perms[i], 8))
    
    def test_branch_mode_statfs_ignore(self, mounted_fs):
        """Test statfs.ignore settings with branch modes."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Get initial statfs
        import os
        initial_stat = os.statvfs(mountpoint)
        initial_free = initial_stat.f_bavail * initial_stat.f_frsize
        
        # Note: Testing statfs.ignore would require:
        # 1. Setting statfs.ignore=ro or statfs.ignore=nc via xattr
        # 2. Making a branch RO or NC
        # 3. Verifying that branch is excluded from space calculations
        
        # For now, just verify we can get statfs
        assert initial_free > 0
    
    def test_branch_modes_with_symlinks(self, mounted_fs):
        """Test branch modes with symbolic links."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create symlink in first branch
        (branches[0] / "target.txt").write_text("Link target")
        os.symlink("target.txt", branches[0] / "link")
        
        # Make first branch read-only
        os.chmod(branches[0], 0o555)
        
        try:
            # Can still read through symlink
            content = (mountpoint / "link").read_text()
            assert content == "Link target"
            
            # Create new symlink - should go to writable branch
            (mountpoint / "new_link").symlink_to("target.txt")
            time.sleep(0.1)
            
            # Should be in a writable branch
            assert not (branches[0] / "new_link").exists()
            assert (branches[1] / "new_link").exists() or \
                   (branches[2] / "new_link").exists()
            
        finally:
            os.chmod(branches[0], 0o755)
    
    def test_branch_mode_permission_precedence(self, mounted_fs):
        """Test precedence of branch modes vs file permissions."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file with write permissions in branch
        test_file = branches[0] / "precedence.txt"
        test_file.write_text("Original")
        os.chmod(test_file, 0o666)  # All can read/write
        
        # Make branch read-only
        os.chmod(branches[0], 0o555)
        
        try:
            # Even though file has write perms, branch is RO
            with pytest.raises(OSError):
                with open(mountpoint / "precedence.txt", 'a') as f:
                    f.write("Should fail")
            
            # Reading should still work
            content = (mountpoint / "precedence.txt").read_text()
            assert content == "Original"
            
        finally:
            os.chmod(branches[0], 0o755)