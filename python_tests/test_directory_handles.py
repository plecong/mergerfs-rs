"""Test directory handle operations (opendir/releasedir)"""

import os
import pytest
import time
from pathlib import Path
import subprocess


@pytest.mark.integration
class TestDirectoryHandles:
    """Test opendir and releasedir operations"""

    def test_basic_directory_listing(self, mounted_fs_with_trace, smart_wait):
        """Test basic directory listing with opendir/readdir/releasedir"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create test directory structure
        for branch in branches:
            test_dir = branch / "testdir"
            test_dir.mkdir(exist_ok=True)
            (test_dir / "file1.txt").write_text("content1")
            (test_dir / "file2.txt").write_text("content2")
            (test_dir / "subdir").mkdir(exist_ok=True)
        
        # List directory through FUSE
        fuse_dir = mountpoint / "testdir"
        assert smart_wait.wait_for_dir_visible(fuse_dir)
        
        # Use os.listdir which internally calls opendir/readdir/releasedir
        entries = sorted(os.listdir(fuse_dir))
        
        # Should contain merged entries
        assert "file1.txt" in entries
        assert "file2.txt" in entries
        assert "subdir" in entries
        
        # Trace monitor will have captured opendir/releasedir operations
        # The operations are logged but we don't need to verify them here

    def test_multiple_concurrent_directory_handles(self, mounted_fs_with_trace, smart_wait):
        """Test multiple directory handles can be open simultaneously"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create test directories
        for i in range(3):
            for branch in branches:
                dir_path = branch / f"dir{i}"
                dir_path.mkdir(exist_ok=True)
                (dir_path / f"file{i}.txt").write_text(f"content{i}")
        
        # Open multiple directories concurrently
        dirs = []
        for i in range(3):
            fuse_dir = mountpoint / f"dir{i}"
            assert smart_wait.wait_for_dir_visible(fuse_dir)
            # os.scandir returns an iterator that keeps the directory handle open
            dirs.append(os.scandir(fuse_dir))
        
        # Read from all directories
        for i, dir_iter in enumerate(dirs):
            entries = [entry.name for entry in dir_iter]
            assert f"file{i}.txt" in entries
            dir_iter.close()

    def test_directory_handle_after_modification(self, mounted_fs_with_trace, smart_wait):
        """Test directory handle remains valid after directory modification"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create initial directory
        for branch in branches:
            test_dir = branch / "moddir"
            test_dir.mkdir(exist_ok=True)
            (test_dir / "initial.txt").write_text("initial")
        
        fuse_dir = mountpoint / "moddir"
        assert smart_wait.wait_for_dir_visible(fuse_dir)
        
        # Open directory handle
        dir_iter = os.scandir(fuse_dir)
        
        # Read initial entries
        initial_entries = [entry.name for entry in dir_iter]
        assert "initial.txt" in initial_entries
        dir_iter.close()
        
        # Add new file
        new_file = fuse_dir / "added.txt"
        new_file.write_text("new content")
        assert smart_wait.wait_for_file_visible(new_file)
        
        # List again with new handle
        new_entries = sorted(os.listdir(fuse_dir))
        assert "initial.txt" in new_entries
        assert "added.txt" in new_entries

    def test_nested_directory_traversal(self, mounted_fs_with_trace, smart_wait):
        """Test traversing nested directories with multiple handles"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create nested directory structure
        for branch in branches:
            base = branch / "nested"
            base.mkdir(exist_ok=True)
            (base / "level1").mkdir(exist_ok=True)
            (base / "level1" / "level2").mkdir(exist_ok=True)
            (base / "level1" / "level2" / "deep.txt").write_text("deep content")
        
        # Traverse nested structure
        base_path = mountpoint / "nested"
        assert smart_wait.wait_for_dir_visible(base_path)
        
        level1_path = base_path / "level1"
        assert smart_wait.wait_for_dir_visible(level1_path)
        
        level2_path = level1_path / "level2"
        assert smart_wait.wait_for_dir_visible(level2_path)
        
        # Use os.walk which opens multiple directory handles
        walked_paths = []
        for root, dirs, files in os.walk(base_path):
            walked_paths.append(root)
            if "deep.txt" in files:
                deep_file = Path(root) / "deep.txt"
                content = deep_file.read_text()
                assert content == "deep content"
        
        # Should have walked through all levels
        assert len(walked_paths) == 3  # nested, nested/level1, nested/level1/level2

    def test_directory_handle_with_special_files(self, mounted_fs_with_trace, smart_wait):
        """Test directory listing includes special control file"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # List root directory
        entries = os.listdir(mountpoint)
        
        # Should include .mergerfs control file
        assert ".mergerfs" in entries
        
        # Control file should be accessible
        control_file = mountpoint / ".mergerfs"
        assert control_file.exists()

    def test_empty_directory_listing(self, mounted_fs_with_trace, smart_wait):
        """Test listing empty directories"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create empty directory
        for branch in branches:
            empty_dir = branch / "empty"
            empty_dir.mkdir(exist_ok=True)
        
        fuse_dir = mountpoint / "empty"
        assert smart_wait.wait_for_dir_visible(fuse_dir)
        
        # List empty directory
        entries = os.listdir(fuse_dir)
        assert len(entries) == 0

    def test_directory_handle_error_cases(self, mounted_fs_with_trace, smart_wait):
        """Test error cases for directory operations"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Try to list non-existent directory
        non_existent = mountpoint / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            os.listdir(non_existent)
        
        # Create a file and try to list it as directory
        test_file = mountpoint / "not_a_dir.txt"
        test_file.write_text("I am a file")
        assert smart_wait.wait_for_file_visible(test_file)
        
        with pytest.raises(NotADirectoryError):
            os.listdir(test_file)

    def test_directory_handle_persistence(self, mounted_fs_with_trace, smart_wait):
        """Test that directory handles are properly tracked and released"""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # Create test directory
        for branch in branches:
            test_dir = branch / "persist_test"
            test_dir.mkdir(exist_ok=True)
            for i in range(5):
                (test_dir / f"file{i}.txt").write_text(f"content{i}")
        
        fuse_dir = mountpoint / "persist_test"
        assert smart_wait.wait_for_dir_visible(fuse_dir)
        
        # Open and close directory handles multiple times
        for _ in range(3):
            # Using context manager ensures proper cleanup
            with os.scandir(fuse_dir) as entries:
                file_count = sum(1 for entry in entries if entry.is_file())
                assert file_count == 5
        
        # Directory should still be accessible
        final_entries = os.listdir(fuse_dir)
        assert len([e for e in final_entries if e.endswith('.txt')]) == 5