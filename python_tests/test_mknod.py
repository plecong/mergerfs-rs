"""Test mknod operations for special file creation."""

import os
import stat
import pytest
from pathlib import Path


@pytest.mark.integration
class TestMknod:
    """Test mknod functionality for creating special files."""

    def test_create_fifo_basic(self, mounted_fs_with_trace, smart_wait):
        """Test creating a FIFO (named pipe) file."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a FIFO
        fifo_path = mountpoint / "test.fifo"
        os.mkfifo(str(fifo_path))
        
        # Wait for FIFO to be visible
        assert smart_wait.wait_for_file_visible(fifo_path)
        
        # Verify it exists and is a FIFO
        assert fifo_path.exists()
        file_stat = fifo_path.stat()
        assert stat.S_ISFIFO(file_stat.st_mode)
        
        # Check it was created in the first branch
        branch_path = branches[0] / "test.fifo"
        assert branch_path.exists()
        assert stat.S_ISFIFO(branch_path.stat().st_mode)

    def test_create_fifo_with_permissions(self, mounted_fs_with_trace, smart_wait):
        """Test creating a FIFO with specific permissions."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a FIFO with specific permissions
        fifo_path = mountpoint / "test_perms.fifo"
        os.mkfifo(str(fifo_path), 0o600)
        
        # Wait for FIFO to be visible
        assert smart_wait.wait_for_file_visible(fifo_path)
        
        # Verify permissions (may be affected by umask)
        file_stat = fifo_path.stat()
        # Check that at least owner read/write are set
        assert file_stat.st_mode & 0o600 == 0o600

    def test_create_fifo_in_subdirectory(self, mounted_fs_with_trace, smart_wait):
        """Test creating a FIFO in a subdirectory."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a subdirectory first
        subdir = mountpoint / "subdir"
        subdir.mkdir()
        assert smart_wait.wait_for_dir_visible(subdir)
        
        # Create a FIFO in the subdirectory
        fifo_path = subdir / "test.fifo"
        os.mkfifo(str(fifo_path))
        
        # Wait for FIFO to be visible
        assert smart_wait.wait_for_file_visible(fifo_path)
        
        # Verify it exists
        assert fifo_path.exists()
        assert stat.S_ISFIFO(fifo_path.stat().st_mode)

    def test_create_fifo_with_path_creation(self, mounted_fs_with_trace, smart_wait):
        """Test creating a FIFO where parent directory needs to be created."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create directory structure in one branch
        branch1_dir = branches[0] / "existing" / "path"
        branch1_dir.mkdir(parents=True)
        
        # Create a FIFO in a new subdirectory that should clone the path
        fifo_path = mountpoint / "existing" / "path" / "new" / "test.fifo"
        
        # First create the parent directory
        fifo_path.parent.mkdir(parents=True, exist_ok=True)
        assert smart_wait.wait_for_dir_visible(fifo_path.parent)
        
        # Now create the FIFO
        os.mkfifo(str(fifo_path))
        assert smart_wait.wait_for_file_visible(fifo_path)
        
        # Verify it exists
        assert fifo_path.exists()
        assert stat.S_ISFIFO(fifo_path.stat().st_mode)

    def test_create_multiple_fifos(self, mounted_fs_with_trace, smart_wait):
        """Test creating multiple FIFOs."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create multiple FIFOs
        fifos = []
        for i in range(3):
            fifo_path = mountpoint / f"fifo_{i}.pipe"
            os.mkfifo(str(fifo_path))
            fifos.append(fifo_path)
        
        # Wait for all to be visible
        for fifo in fifos:
            assert smart_wait.wait_for_file_visible(fifo)
            assert fifo.exists()
            assert stat.S_ISFIFO(fifo.stat().st_mode)

    def test_create_fifo_existing_name(self, mounted_fs_with_trace, smart_wait):
        """Test creating a FIFO with a name that already exists."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a regular file first
        file_path = mountpoint / "exists.txt"
        file_path.write_text("content")
        assert smart_wait.wait_for_file_visible(file_path)
        
        # Try to create a FIFO with the same name
        with pytest.raises(FileExistsError):
            os.mkfifo(str(file_path))

    def test_regular_file_via_mknod(self, mounted_fs_with_trace, smart_wait):
        """Test creating a regular file using mknod (if supported)."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Note: Creating device files typically requires root privileges
        # We can test regular file creation through mknod API
        file_path = mountpoint / "mknod_regular.txt"
        
        # Create a regular file with mknod (mode includes S_IFREG)
        # This tests the mknod path for regular files
        try:
            # Try using os.mknod if available (requires Python 3.3+)
            if hasattr(os, 'mknod'):
                os.mknod(str(file_path), stat.S_IFREG | 0o644)
                assert smart_wait.wait_for_file_visible(file_path)
                assert file_path.exists()
                assert file_path.is_file()
        except AttributeError:
            # os.mknod not available on this platform
            pytest.skip("os.mknod not available")

    def test_fifo_cross_branch_visibility(self, mounted_fs_with_trace, smart_wait):
        """Test that FIFOs are visible across branches."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a FIFO
        fifo_path = mountpoint / "cross_branch.fifo"
        os.mkfifo(str(fifo_path))
        assert smart_wait.wait_for_file_visible(fifo_path)
        
        # It should be in the first branch based on FirstFound policy
        branch1_fifo = branches[0] / "cross_branch.fifo"
        assert branch1_fifo.exists()
        assert stat.S_ISFIFO(branch1_fifo.stat().st_mode)
        
        # Should not be in the second branch
        branch2_fifo = branches[1] / "cross_branch.fifo"
        assert not branch2_fifo.exists()

    @pytest.mark.skipif(os.geteuid() != 0, reason="Requires root privileges")
    def test_create_device_file(self, mounted_fs_with_trace, smart_wait):
        """Test creating device files (requires root)."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create a character device (null device)
        device_path = mountpoint / "test_null"
        os.mknod(str(device_path), stat.S_IFCHR | 0o666, os.makedev(1, 3))
        
        assert smart_wait.wait_for_file_visible(device_path)
        assert device_path.exists()
        
        file_stat = device_path.stat()
        assert stat.S_ISCHR(file_stat.st_mode)
        assert file_stat.st_rdev == os.makedev(1, 3)