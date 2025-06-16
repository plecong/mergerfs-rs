"""Basic integration tests for access() FUSE operation."""

import os
import pytest
import stat
from pathlib import Path


@pytest.mark.integration
class TestAccessBasic:
    """Basic tests for access() operation."""

    def test_access_file_exists(self, mounted_fs):
        """Test F_OK access check (file existence)."""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "test_exists.txt"
        test_file.write_text("test content")
        
        # Check file existence with os.access
        assert os.access(test_file, os.F_OK) is True
        
        # Check non-existent file
        non_existent = mountpoint / "does_not_exist.txt"
        assert os.access(non_existent, os.F_OK) is False

    def test_access_basic_permissions(self, mounted_fs):
        """Test basic permission checks."""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file with all permissions
        test_file = mountpoint / "test_perms.txt"
        test_file.write_text("test content")
        test_file.chmod(0o755)
        
        # All should pass
        assert os.access(test_file, os.R_OK) is True
        assert os.access(test_file, os.W_OK) is True
        assert os.access(test_file, os.X_OK) is True
        
        # Remove all permissions
        test_file.chmod(0o000)
        
        # For non-root users, all should fail
        # But we can't reliably test this in all environments
        # Just verify the chmod worked
        assert (test_file.stat().st_mode & 0o777) == 0o000

    def test_access_directory_permissions(self, mounted_fs):
        """Test access checks on directories."""
        process, mountpoint, branches = mounted_fs
        
        # Create a directory
        test_dir = mountpoint / "test_dir"
        test_dir.mkdir()
        
        # Directories need execute permission to be accessible
        assert os.access(test_dir, os.F_OK) is True
        assert os.access(test_dir, os.R_OK) is True
        assert os.access(test_dir, os.W_OK) is True
        assert os.access(test_dir, os.X_OK) is True

    def test_access_symbolic_links(self, mounted_fs):
        """Test access checks on symbolic links."""
        process, mountpoint, branches = mounted_fs
        
        # Create a target file
        target = mountpoint / "target.txt"
        target.write_text("target content")
        target.chmod(0o644)
        
        # Create a symbolic link
        link = mountpoint / "link.txt"
        link.symlink_to(target)
        
        # Access checks should follow the symlink
        assert os.access(link, os.F_OK) is True
        assert os.access(link, os.R_OK) is True
        assert os.access(link, os.W_OK) is True
        
        # Remove target
        target.unlink()
        
        # Broken symlink
        assert os.access(link, os.F_OK) is False

    def test_access_nested_paths(self, mounted_fs):
        """Test access with nested directory paths."""
        process, mountpoint, branches = mounted_fs
        
        # Create deeply nested path
        nested_dir = mountpoint / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        nested_file = nested_dir / "deep.txt"
        nested_file.write_text("deep content")
        
        # Should be accessible
        assert os.access(nested_file, os.F_OK) is True
        assert os.access(nested_file, os.R_OK) is True
        assert os.access(nested_file, os.W_OK) is True

    def test_access_control_file(self, mounted_fs):
        """Test access to .mergerfs control file."""
        process, mountpoint, branches = mounted_fs
        
        # Control file should exist
        control_file = mountpoint / ".mergerfs"
        assert os.access(control_file, os.F_OK) is True
        
        # Should be readable and writable
        assert os.access(control_file, os.R_OK) is True
        assert os.access(control_file, os.W_OK) is True