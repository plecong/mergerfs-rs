"""Test fsyncdir operation."""

import os
import pytest
import errno
from pathlib import Path
import ctypes
import ctypes.util


@pytest.mark.integration
class TestFsyncdir:
    """Test fsyncdir functionality."""
    
    def test_fsyncdir_behavior(self, mounted_fs):
        """Test fsyncdir behavior - it may succeed or return ENOSYS."""
        process, mountpoint, branches = mounted_fs
        
        # Create a test directory
        test_dir = mountpoint / "test_sync_dir"
        test_dir.mkdir()
        
        # Verify directory exists
        assert test_dir.exists()
        assert test_dir.is_dir()
        
        # Open the directory to get a file descriptor
        dir_fd = os.open(str(test_dir), os.O_RDONLY)
        
        try:
            # Try to sync the directory
            # On Linux, fsync on a directory fd may succeed (no-op) or fail with EINVAL/ENOSYS
            # The mergerfs implementation returns ENOSYS, but the kernel may handle it differently
            try:
                os.fsync(dir_fd)
                # If it succeeds, that's OK - kernel may be handling it
            except OSError as e:
                # If it fails, it should be ENOSYS (38) or EINVAL (22)
                assert e.errno in [errno.ENOSYS, errno.EINVAL]
        finally:
            os.close(dir_fd)
    
    def test_fsyncdir_with_files(self, mounted_fs, smart_wait):
        """Test fsyncdir on directory containing files."""
        process, mountpoint, branches = mounted_fs
        
        # Create a directory with some files
        test_dir = mountpoint / "sync_test_dir"
        test_dir.mkdir()
        
        # Create files in the directory
        for i in range(5):
            file_path = test_dir / f"file_{i}.txt"
            file_path.write_text(f"Content {i}")
            assert smart_wait.wait_for_file_visible(file_path)
        
        # Open the directory
        dir_fd = os.open(str(test_dir), os.O_RDONLY)
        
        try:
            # Try to sync
            try:
                os.fsync(dir_fd)
                # Success is OK
            except OSError as e:
                # Failure with ENOSYS or EINVAL is also OK
                assert e.errno in [errno.ENOSYS, errno.EINVAL]
            
            # Verify files are still intact
            for i in range(5):
                file_path = test_dir / f"file_{i}.txt"
                assert file_path.exists()
                assert file_path.read_text() == f"Content {i}"
        finally:
            os.close(dir_fd)
    
    def test_fsyncdir_on_mount_root(self, mounted_fs):
        """Test fsyncdir on the mount root directory."""
        process, mountpoint, branches = mounted_fs
        
        # Open the mount root
        root_fd = os.open(str(mountpoint), os.O_RDONLY)
        
        try:
            # Try to sync the root
            try:
                os.fsync(root_fd)
                # Success is OK
            except OSError as e:
                # Failure with ENOSYS or EINVAL is also OK
                assert e.errno in [errno.ENOSYS, errno.EINVAL]
        finally:
            os.close(root_fd)
    
    def test_directory_operations_without_fsync(self, mounted_fs, smart_wait):
        """Verify directory operations work correctly without explicit fsync."""
        process, mountpoint, branches = mounted_fs
        
        # Create nested directories
        base_dir = mountpoint / "base"
        sub_dir = base_dir / "sub"
        deep_dir = sub_dir / "deep"
        
        base_dir.mkdir()
        sub_dir.mkdir()
        deep_dir.mkdir()
        
        # Create files at different levels
        (base_dir / "base.txt").write_text("base content")
        (sub_dir / "sub.txt").write_text("sub content")
        (deep_dir / "deep.txt").write_text("deep content")
        
        # Wait for visibility
        assert smart_wait.wait_for_file_visible(deep_dir / "deep.txt")
        
        # Verify all files exist in underlying branches
        # Even without fsync, files should be persisted by underlying FS
        for branch in branches:
            branch_base = Path(branch) / "base"
            if branch_base.exists():
                assert (branch_base / "base.txt").exists()
                assert (branch_base / "sub" / "sub.txt").exists()
                assert (branch_base / "sub" / "deep" / "deep.txt").exists()