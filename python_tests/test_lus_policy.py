#!/usr/bin/env python3
"""
Integration tests for the 'lus' (least used space) create policy.
"""

import os
import pytest
import shutil
from pathlib import Path
from typing import List
from conftest import FuseConfig


@pytest.mark.integration
class TestLeastUsedSpacePolicy:
    """Test the 'lus' create policy behavior."""
    
    @pytest.fixture
    def mounted_lus_fs(self, fuse_manager, temp_branches: List[Path], temp_mountpoint: Path):
        """Mount filesystem with lus policy."""
        config = FuseConfig(
            policy="lus",
            branches=temp_branches,
            mountpoint=temp_mountpoint,
            enable_trace=True
        )
        with fuse_manager.mounted_fs(config) as result:
            yield result
    
    def test_lus_basic_file_creation(self, mounted_lus_fs, smart_wait):
        """Test that files are created on the branch with least used space."""
        process, mountpoint, branches, trace_monitor = mounted_lus_fs
        
        # Create some files on different branches to create different used space
        # Note: The actual filesystem's statvfs will report real disk usage
        # Branch 0: Create larger files (more used space)
        for i in range(10):
            file_path = branches[0] / f"file{i}.txt"
            file_path.write_text("x" * 10 * 1024 * 1024)  # 10MB each = 100MB total
            
        # Branch 1: Create smaller files (less used space)
        for i in range(3):
            file_path = branches[1] / f"file_b{i}.txt"
            file_path.write_text("x" * 10 * 1024 * 1024)  # 10MB each = 30MB total
        
        # Branch 2: No files (least used space)
        
        # The filesystem is already mounted with lus policy
        
        # Create a new file - should go to branch 2 (least used space)
        test_file = mountpoint / "test_lus.txt"
        test_file.write_text("test content")
        assert smart_wait.wait_for_file_visible(test_file)
        
        # Debug: Check which branch got the file
        for i, branch in enumerate(branches):
            if (branch / "test_lus.txt").exists():
                print(f"File created on branch {i}")
        
        # Verify file was created on branch 2
        assert (branches[2] / "test_lus.txt").exists(), f"File not on branch 2. Branch 0: {(branches[0] / 'test_lus.txt').exists()}, Branch 1: {(branches[1] / 'test_lus.txt').exists()}, Branch 2: {(branches[2] / 'test_lus.txt').exists()}"
        assert not (branches[0] / "test_lus.txt").exists()
        assert not (branches[1] / "test_lus.txt").exists()
    
    def test_lus_directory_creation(self, mounted_lus_fs, smart_wait):
        """Test that directories are created on the branch with least used space."""
        process, mountpoint, branches, trace_monitor = mounted_lus_fs
        
        # Create different amounts of data on branches
        # Branch 0: 5MB used
        large_file = branches[0] / "large.dat"
        large_file.write_bytes(b"x" * 5 * 1024 * 1024)
        
        # Branch 1: 2MB used
        medium_file = branches[1] / "medium.dat"
        medium_file.write_bytes(b"x" * 2 * 1024 * 1024)
        
        # Branch 2: 0MB used (least)
        
        # Create a new directory
        test_dir = mountpoint / "test_lus_dir"
        test_dir.mkdir()
        assert smart_wait.wait_for_dir_visible(test_dir)
        
        # Verify directory was created on branch 2
        assert (branches[2] / "test_lus_dir").is_dir()
        assert not (branches[0] / "test_lus_dir").exists()
        assert not (branches[1] / "test_lus_dir").exists()
    
    def test_lus_with_readonly_branch(self, mounted_lus_fs, smart_wait):
        """Test that lus policy skips read-only branches."""
        process, mountpoint, branches, trace_monitor = mounted_lus_fs
        
        # Create some initial files
        (branches[0] / "file0.txt").write_text("data" * 1000)  # Branch 0: some data
        (branches[1] / "file1.txt").write_text("data" * 100)   # Branch 1: less data (least used)
        # Branch 2: no data initially
        
        # Make branch 1 read-only (the one with least used space)
        os.chmod(branches[1], 0o555)
        
        try:
            # Create a new file
            test_file = mountpoint / "test_readonly.txt"
            test_file.write_text("test content")
            assert smart_wait.wait_for_file_visible(test_file)
            
            # Should go to branch 2 (next least used, since branch 1 is readonly)
            assert (branches[2] / "test_readonly.txt").exists()
            assert not (branches[0] / "test_readonly.txt").exists()
            assert not (branches[1] / "test_readonly.txt").exists()
            
        finally:
            # Restore write permissions
            os.chmod(branches[1], 0o755)
    
    def test_lus_space_balancing(self, mounted_lus_fs, smart_wait):
        """Test that lus policy balances space usage over time."""
        process, mountpoint, branches, trace_monitor = mounted_lus_fs
        
        # Track files created on each branch
        branch_files = {0: [], 1: [], 2: []}
        
        # Create multiple files and see distribution
        for i in range(9):
            test_file = mountpoint / f"balanced_{i}.txt"
            test_file.write_text("x" * 1024 * 100)  # 100KB each
            assert smart_wait.wait_for_file_visible(test_file)
            
            # Check which branch got the file
            for idx, branch in enumerate(branches):
                if (branch / f"balanced_{i}.txt").exists():
                    branch_files[idx].append(f"balanced_{i}.txt")
                    break
        
        # Each branch should have gotten some files (roughly balanced)
        # With lus policy, files should distribute fairly evenly
        assert all(len(files) > 0 for files in branch_files.values())
        
        # The difference between max and min files should be small
        file_counts = [len(files) for files in branch_files.values()]
        assert max(file_counts) - min(file_counts) <= 2
    
    def test_lus_empty_branches(self, mounted_lus_fs, smart_wait):
        """Test lus behavior when all branches are empty."""
        process, mountpoint, branches, trace_monitor = mounted_lus_fs
        
        # All branches have 0 used space, should pick first one
        test_file = mountpoint / "first_file.txt"
        test_file.write_text("first")
        assert smart_wait.wait_for_file_visible(test_file)
        
        # Should go to first branch when all have equal (zero) used space
        assert (branches[0] / "first_file.txt").exists()
        assert not (branches[1] / "first_file.txt").exists()
        assert not (branches[2] / "first_file.txt").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])