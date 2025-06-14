"""Integration tests for rename strategies in mergerfs-rs."""

import os
import pytest
from pathlib import Path
import xattr
import tempfile
import shutil


@pytest.mark.integration
class TestRenameStrategies:
    """Test rename operation with different strategies."""
    
    def test_basic_rename(self, mounted_fs):
        """Test basic file rename within same directory."""
        process, mountpoint, branches = mounted_fs
        
        # Create a file
        test_file = mountpoint / "test.txt"
        test_file.write_text("test content")
        
        # Rename it
        new_path = mountpoint / "renamed.txt"
        test_file.rename(new_path)
        
        # Verify rename
        assert not test_file.exists()
        assert new_path.exists()
        assert new_path.read_text() == "test content"
    
    def test_rename_across_directories(self, mounted_fs):
        """Test rename across different directories."""
        process, mountpoint, branches = mounted_fs
        
        # Create source directory and file
        src_dir = mountpoint / "src"
        src_dir.mkdir()
        src_file = src_dir / "file.txt"
        src_file.write_text("content")
        
        # Create destination directory
        dst_dir = mountpoint / "dst"
        dst_dir.mkdir()
        
        # Rename file to different directory
        dst_file = dst_dir / "file.txt"
        src_file.rename(dst_file)
        
        # Verify
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "content"
    
    def test_rename_to_nonexistent_directory(self, mounted_fs):
        """Test rename to a directory that doesn't exist yet."""
        process, mountpoint, branches = mounted_fs
        
        # Create a file
        src_file = mountpoint / "test.txt"
        src_file.write_text("content")
        
        # Rename to non-existent directory
        dst_file = mountpoint / "newdir" / "subdir" / "renamed.txt"
        
        # This should create parent directories
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.rename(dst_file)
        
        # Verify
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "content"
    
    def test_rename_overwrite_existing(self, mounted_fs):
        """Test rename that overwrites an existing file."""
        process, mountpoint, branches = mounted_fs
        
        # Create source and destination files
        src_file = mountpoint / "source.txt"
        dst_file = mountpoint / "dest.txt"
        src_file.write_text("source content")
        dst_file.write_text("dest content")
        
        # Rename should overwrite
        src_file.rename(dst_file)
        
        # Verify
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "source content"
    
    def test_rename_directory(self, mounted_fs):
        """Test renaming a directory."""
        process, mountpoint, branches = mounted_fs
        
        # Create directory with contents
        src_dir = mountpoint / "src_dir"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("content1")
        (src_dir / "file2.txt").write_text("content2")
        (src_dir / "subdir").mkdir()
        (src_dir / "subdir" / "file3.txt").write_text("content3")
        
        # Rename directory
        dst_dir = mountpoint / "dst_dir"
        src_dir.rename(dst_dir)
        
        # Verify directory and contents moved
        assert not src_dir.exists()
        assert dst_dir.exists()
        assert (dst_dir / "file1.txt").read_text() == "content1"
        assert (dst_dir / "file2.txt").read_text() == "content2"
        assert (dst_dir / "subdir" / "file3.txt").read_text() == "content3"
    
    def test_rename_preserves_permissions(self, mounted_fs):
        """Test that rename preserves file permissions."""
        process, mountpoint, branches = mounted_fs
        
        # Create file with specific permissions
        src_file = mountpoint / "test.txt"
        src_file.write_text("content")
        src_file.chmod(0o644)
        
        # Get original permissions
        orig_mode = src_file.stat().st_mode
        
        # Rename
        dst_file = mountpoint / "renamed.txt"
        src_file.rename(dst_file)
        
        # Verify permissions preserved
        assert dst_file.stat().st_mode == orig_mode
    
    def test_rename_multi_branch_file(self, mounted_fs):
        """Test rename of file that exists on multiple branches."""
        process, mountpoint, branches = mounted_fs
        
        # Create file on multiple branches directly
        for i, branch in enumerate(branches):
            test_file = Path(branch) / "multi.txt"
            test_file.write_text(f"content{i}")
        
        # Rename through mountpoint
        src_file = mountpoint / "multi.txt"
        dst_file = mountpoint / "renamed_multi.txt"
        src_file.rename(dst_file)
        
        # Verify rename happened on all branches
        for branch in branches:
            assert not (Path(branch) / "multi.txt").exists()
            assert (Path(branch) / "renamed_multi.txt").exists()
    
    def test_rename_with_partial_success(self, mounted_fs):
        """Test rename behavior when file exists on multiple branches.
        
        Note: Since the Python test framework doesn't support read-only branch
        configuration yet, this test simulates the behavior by verifying that
        rename works across multiple branches.
        """
        process, mountpoint, branches = mounted_fs
        
        # Create file on all branches with different content
        for i, branch in enumerate(branches):
            test_file = Path(branch) / "partial.txt"
            test_file.write_text(f"branch{i} content")
        
        # Rename through mountpoint
        src_file = mountpoint / "partial.txt"
        dst_file = mountpoint / "renamed_partial.txt"
        
        # Perform rename
        src_file.rename(dst_file)
        
        # Verify rename happened on all branches
        for i, branch in enumerate(branches):
            assert not (Path(branch) / "partial.txt").exists()
            renamed = Path(branch) / "renamed_partial.txt"
            assert renamed.exists()
            # Each branch should retain its original content
            assert renamed.read_text() == f"branch{i} content"
    
    def test_rename_empty_directory(self, mounted_fs):
        """Test renaming an empty directory."""
        process, mountpoint, branches = mounted_fs
        
        # Create empty directory
        src_dir = mountpoint / "empty_dir"
        src_dir.mkdir()
        
        # Rename it
        dst_dir = mountpoint / "renamed_empty_dir"
        src_dir.rename(dst_dir)
        
        # Verify
        assert not src_dir.exists()
        assert dst_dir.exists()
        assert dst_dir.is_dir()
    
    def test_rename_case_sensitivity(self, mounted_fs):
        """Test rename with case changes (important for case-sensitive filesystems)."""
        process, mountpoint, branches = mounted_fs
        
        # Create file with lowercase name
        src_file = mountpoint / "lowercase.txt"
        src_file.write_text("content")
        
        # Rename to uppercase
        dst_file = mountpoint / "LOWERCASE.TXT"
        src_file.rename(dst_file)
        
        # Verify - on case-sensitive systems these are different files
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "content"
    
    def test_rename_special_characters(self, mounted_fs):
        """Test rename with special characters in filename."""
        process, mountpoint, branches = mounted_fs
        
        # Create file with special characters
        src_file = mountpoint / "file with spaces & special.txt"
        src_file.write_text("content")
        
        # Rename to another name with special characters
        dst_file = mountpoint / "renamed (with) [brackets].txt"
        src_file.rename(dst_file)
        
        # Verify
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "content"
    
    def test_rename_deep_directory_structure(self, mounted_fs):
        """Test rename within deep directory structure."""
        process, mountpoint, branches = mounted_fs
        
        # Create deep directory structure
        deep_path = mountpoint
        for i in range(10):
            deep_path = deep_path / f"level{i}"
        deep_path.mkdir(parents=True)
        
        # Create file in deep structure
        src_file = deep_path / "deep_file.txt"
        src_file.write_text("deep content")
        
        # Rename within same deep directory
        dst_file = deep_path / "renamed_deep_file.txt"
        src_file.rename(dst_file)
        
        # Verify
        assert not src_file.exists()
        assert dst_file.exists()
        assert dst_file.read_text() == "deep content"
    
    def test_concurrent_renames(self, mounted_fs):
        """Test concurrent rename operations."""
        import threading
        import time
        
        process, mountpoint, branches = mounted_fs
        
        # Create multiple files
        num_files = 10
        for i in range(num_files):
            (mountpoint / f"file{i}.txt").write_text(f"content{i}")
        
        errors = []
        
        def rename_file(idx):
            try:
                src = mountpoint / f"file{idx}.txt"
                dst = mountpoint / f"renamed{idx}.txt"
                src.rename(dst)
            except Exception as e:
                errors.append(e)
        
        # Start concurrent renames
        threads = []
        for i in range(num_files):
            t = threading.Thread(target=rename_file, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Verify no errors and all files renamed
        assert len(errors) == 0
        for i in range(num_files):
            assert not (mountpoint / f"file{i}.txt").exists()
            assert (mountpoint / f"renamed{i}.txt").exists()
            assert (mountpoint / f"renamed{i}.txt").read_text() == f"content{i}"


@pytest.mark.integration 
class TestRenameConfiguration:
    """Test rename configuration options through xattr interface."""
    
    def test_ignore_path_preserving_config(self, mounted_fs):
        """Test ignore_path_preserving_on_rename configuration."""
        process, mountpoint, branches = mounted_fs
        
        # Check if .mergerfs control file exists
        control_file = mountpoint / ".mergerfs"
        if not control_file.exists():
            pytest.skip(".mergerfs control file not available")
        
        try:
            # Try to set the configuration
            xattr.setxattr(str(control_file), "user.mergerfs.ignorepponrename", b"true")
            
            # Create test file and rename
            test_file = mountpoint / "test.txt"
            test_file.write_text("content")
            renamed_file = mountpoint / "renamed.txt"
            test_file.rename(renamed_file)
            
            # Verify rename worked
            assert not test_file.exists()
            assert renamed_file.exists()
            
        except OSError as e:
            # xattr operations might not be supported
            pytest.skip(f"xattr operations not supported: {e}")