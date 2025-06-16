"""Integration tests for access() FUSE operation."""

import os
import pytest
import stat
from pathlib import Path


@pytest.mark.integration
class TestAccessOperation:
    """Test access() operation for permission checking."""

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

    def test_access_read_permission(self, mounted_fs):
        """Test R_OK access check (read permission)."""
        process, mountpoint, branches = mounted_fs
        
        # Create a readable file
        readable_file = mountpoint / "readable.txt"
        readable_file.write_text("readable content")
        
        # Should be readable by default
        assert os.access(readable_file, os.R_OK) is True
        
        # Remove read permission (owner read bit)
        current_mode = readable_file.stat().st_mode
        new_mode = current_mode & ~stat.S_IRUSR & ~stat.S_IRGRP & ~stat.S_IROTH
        readable_file.chmod(new_mode)
        
        # Verify the chmod worked
        actual_mode = readable_file.stat().st_mode
        print(f"Changed mode from {oct(current_mode)} to {oct(new_mode)}, actual: {oct(actual_mode)}")
        
        # Should not be readable now (unless running as root)
        # Note: This test may pass if running as root
        if os.getuid() != 0:
            # Check the underlying file permissions too
            for branch in branches:
                branch_file = branch / "readable.txt"
                if branch_file.exists():
                    branch_mode = branch_file.stat().st_mode
                    print(f"Branch {branch} file mode: {oct(branch_mode)}")
            
            # Access should be denied
            result = os.access(readable_file, os.R_OK)
            print(f"Access check result: {result}")
            assert result is False

    def test_access_write_permission(self, mounted_fs):
        """Test W_OK access check (write permission)."""
        process, mountpoint, branches = mounted_fs
        
        # Create a writable file
        writable_file = mountpoint / "writable.txt"
        writable_file.write_text("writable content")
        
        # Should be writable by default
        assert os.access(writable_file, os.W_OK) is True
        
        # Remove write permission
        current_mode = writable_file.stat().st_mode
        writable_file.chmod(current_mode & ~stat.S_IWUSR)
        
        # Should not be writable now (unless running as root)
        if os.getuid() != 0:
            assert os.access(writable_file, os.W_OK) is False

    def test_access_execute_permission(self, mounted_fs):
        """Test X_OK access check (execute permission)."""
        process, mountpoint, branches = mounted_fs
        
        # Create a script file
        script_file = mountpoint / "script.sh"
        script_file.write_text("#!/bin/bash\necho 'Hello World'")
        
        # Make it executable first
        script_file.chmod(0o755)
        
        # Should be executable now
        assert os.access(script_file, os.X_OK) is True
        
        # Remove execute permission
        script_file.chmod(0o644)
        
        # Should not be executable
        assert os.access(script_file, os.X_OK) is False

    def test_access_combined_permissions(self, mounted_fs):
        """Test combined permission checks."""
        process, mountpoint, branches = mounted_fs
        
        # Create a file with specific permissions
        test_file = mountpoint / "combined_perms.txt"
        test_file.write_text("test content")
        
        # Set read and write, but not execute
        test_file.chmod(0o600)
        
        # Check combinations
        assert os.access(test_file, os.R_OK | os.W_OK) is True
        assert os.access(test_file, os.R_OK | os.X_OK) is False
        assert os.access(test_file, os.W_OK | os.X_OK) is False
        assert os.access(test_file, os.R_OK | os.W_OK | os.X_OK) is False

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
        
        # Remove execute permission
        test_dir.chmod(0o600)
        
        # Directory still exists but may not be accessible
        assert os.access(test_dir, os.F_OK) is True
        if os.getuid() != 0:
            assert os.access(test_dir, os.X_OK) is False

    def test_access_with_multiple_branches(self, mounted_fs):
        """Test access checks when file exists in multiple branches."""
        process, mountpoint, branches = mounted_fs
        
        if len(branches) < 2:
            pytest.skip("Need at least 2 branches for this test")
        
        # Create same file in both branches with different permissions
        filename = "multi_branch_file.txt"
        
        # First branch: readable and writable
        file1 = branches[0] / filename
        file1.write_text("branch 1 content")
        file1.chmod(0o644)
        
        # Second branch: read-only
        file2 = branches[1] / filename
        file2.write_text("branch 2 content")
        file2.chmod(0o444)
        
        # Access through mergerfs should check the first found branch
        merged_file = mountpoint / filename
        assert os.access(merged_file, os.F_OK) is True
        assert os.access(merged_file, os.R_OK) is True
        # Write permission depends on which branch is checked first
        # (determined by search policy)

    def test_access_readonly_branch(self, mounted_fs):
        """Test access checks on files in readonly branches."""
        process, mountpoint, branches = mounted_fs
        
        # This test would require setting up a readonly branch
        # For now, we'll create a file and simulate readonly behavior
        test_file = mountpoint / "readonly_test.txt"
        test_file.write_text("readonly content")
        
        # Make file readonly
        test_file.chmod(0o444)
        
        # Should be readable but not writable
        assert os.access(test_file, os.F_OK) is True
        assert os.access(test_file, os.R_OK) is True
        if os.getuid() != 0:
            assert os.access(test_file, os.W_OK) is False

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

    def test_access_special_cases(self, mounted_fs):
        """Test special cases and edge conditions."""
        process, mountpoint, branches = mounted_fs
        
        # Test root directory
        assert os.access(mountpoint, os.F_OK) is True
        assert os.access(mountpoint, os.R_OK) is True
        assert os.access(mountpoint, os.X_OK) is True
        
        # Test with path containing special characters
        special_file = mountpoint / "file with spaces.txt"
        special_file.write_text("content")
        assert os.access(special_file, os.F_OK) is True
        
        # Test deeply nested path
        nested_dir = mountpoint / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        nested_file = nested_dir / "deep.txt"
        nested_file.write_text("deep content")
        assert os.access(nested_file, os.F_OK) is True