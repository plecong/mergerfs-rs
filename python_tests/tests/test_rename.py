import os
import shutil
import pytest
from pathlib import Path
import tempfile


@pytest.mark.integration
class TestRename:
    """Test rename operations in mergerfs-rs."""
    
    def test_simple_rename_same_directory(self, mounted_fs):
        """Test renaming a file within the same directory."""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "test.txt"
        test_file.write_text("test content")
        
        # Rename the file
        new_file = mountpoint / "renamed.txt"
        os.rename(test_file, new_file)
        
        # Verify old file doesn't exist
        assert not test_file.exists()
        
        # Verify new file exists with same content
        assert new_file.exists()
        assert new_file.read_text() == "test content"
        
        # Verify file exists in first branch
        assert (branches[0] / "renamed.txt").exists()
        assert (branches[0] / "renamed.txt").read_text() == "test content"
    
    def test_rename_across_directories(self, mounted_fs):
        """Test renaming a file across directories."""
        process, mountpoint, branches = mounted_fs
        
        # Create directory structure
        (mountpoint / "dir1").mkdir()
        (mountpoint / "dir2").mkdir()
        
        # Create a test file
        test_file = mountpoint / "dir1" / "test.txt"
        test_file.write_text("test content")
        
        # Rename across directories
        new_file = mountpoint / "dir2" / "renamed.txt"
        os.rename(test_file, new_file)
        
        # Verify old file doesn't exist
        assert not test_file.exists()
        
        # Verify new file exists with same content
        assert new_file.exists()
        assert new_file.read_text() == "test content"
    
    def test_rename_directory(self, mounted_fs):
        """Test renaming a directory."""
        process, mountpoint, branches = mounted_fs
        
        # Create directory with files
        test_dir = mountpoint / "test_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")
        
        # Create subdirectory
        sub_dir = test_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "file3.txt").write_text("content3")
        
        # Rename the directory
        new_dir = mountpoint / "renamed_dir"
        os.rename(test_dir, new_dir)
        
        # Verify old directory doesn't exist
        assert not test_dir.exists()
        
        # Verify new directory exists with all contents
        assert new_dir.exists()
        assert (new_dir / "file1.txt").exists()
        assert (new_dir / "file1.txt").read_text() == "content1"
        assert (new_dir / "file2.txt").exists()
        assert (new_dir / "file2.txt").read_text() == "content2"
        assert (new_dir / "subdir" / "file3.txt").exists()
        assert (new_dir / "subdir" / "file3.txt").read_text() == "content3"
    
    def test_rename_nonexistent_file(self, mounted_fs):
        """Test renaming a non-existent file."""
        process, mountpoint, branches = mounted_fs
        
        # Try to rename non-existent file
        old_file = mountpoint / "nonexistent.txt"
        new_file = mountpoint / "new.txt"
        
        with pytest.raises(FileNotFoundError):
            os.rename(old_file, new_file)
    
    def test_rename_to_existing_file(self, mounted_fs):
        """Test renaming to an existing file (should overwrite)."""
        process, mountpoint, branches = mounted_fs
        
        # Create source and destination files
        source_file = mountpoint / "source.txt"
        source_file.write_text("source content")
        
        dest_file = mountpoint / "dest.txt"
        dest_file.write_text("destination content")
        
        # Rename should overwrite destination
        os.rename(source_file, dest_file)
        
        # Verify source doesn't exist
        assert not source_file.exists()
        
        # Verify destination has source content
        assert dest_file.exists()
        assert dest_file.read_text() == "source content"
    
    def test_rename_multi_branch_file(self, mounted_fs):
        """Test renaming a file that exists on multiple branches."""
        process, mountpoint, branches = mounted_fs
        
        # Create file directly on both branches
        file1 = branches[0] / "multi.txt"
        file1.write_text("content from branch 1")
        
        file2 = branches[1] / "multi.txt"
        file2.write_text("content from branch 2")
        
        # Rename through mountpoint
        old_file = mountpoint / "multi.txt"
        new_file = mountpoint / "renamed_multi.txt"
        os.rename(old_file, new_file)
        
        # Verify old file doesn't exist on either branch
        assert not file1.exists()
        assert not file2.exists()
        
        # Verify new file exists on both branches with original content
        new_file1 = branches[0] / "renamed_multi.txt"
        new_file2 = branches[1] / "renamed_multi.txt"
        
        assert new_file1.exists()
        assert new_file1.read_text() == "content from branch 1"
        
        assert new_file2.exists()
        assert new_file2.read_text() == "content from branch 2"
    
    def test_rename_preserves_permissions(self, mounted_fs):
        """Test that rename preserves file permissions."""
        process, mountpoint, branches = mounted_fs
        
        # Create a file with specific permissions
        test_file = mountpoint / "test.txt"
        test_file.write_text("test content")
        os.chmod(test_file, 0o755)
        
        # Get original permissions
        orig_mode = test_file.stat().st_mode & 0o777
        
        # Rename the file
        new_file = mountpoint / "renamed.txt"
        os.rename(test_file, new_file)
        
        # Verify permissions are preserved
        new_mode = new_file.stat().st_mode & 0o777
        assert new_mode == orig_mode
    
    def test_rename_with_deep_path(self, mounted_fs):
        """Test renaming files in deeply nested directories."""
        process, mountpoint, branches = mounted_fs
        
        # Create deep directory structure
        deep_path = mountpoint / "a" / "b" / "c" / "d"
        deep_path.mkdir(parents=True)
        
        # Create file in deep path
        test_file = deep_path / "test.txt"
        test_file.write_text("deep content")
        
        # Create another deep path
        new_deep_path = mountpoint / "x" / "y" / "z"
        new_deep_path.mkdir(parents=True)
        
        # Rename across deep paths
        new_file = new_deep_path / "renamed.txt"
        os.rename(test_file, new_file)
        
        # Verify
        assert not test_file.exists()
        assert new_file.exists()
        assert new_file.read_text() == "deep content"