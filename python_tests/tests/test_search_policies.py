#!/usr/bin/env python3
"""Integration tests for search policies."""

import os
import time
import pytest
from pathlib import Path
from typing import Tuple, List


@pytest.mark.integration
class TestSearchPolicies:
    """Test search policy functionality.
    
    Note: Search policies are used internally by mergerfs for finding files.
    We can't directly test them from the outside, but we can verify that
    file operations work correctly which implies search is working.
    """
    
    def test_file_found_across_branches(self, mounted_fs):
        """Test that files can be found regardless of which branch they're in."""
        process, mountpoint, branches = mounted_fs
        
        # Create same file in different branches with different content
        for i, branch in enumerate(branches):
            test_file = branch / "search_test.txt"
            test_file.write_text(f"branch_{i}")
            print(f"Created {test_file} - exists: {test_file.exists()}")
        
        # Small delay to ensure filesystem sees the files
        time.sleep(0.1)
        
        # Check if file is visible through mount
        mount_file = mountpoint / "search_test.txt"
        print(f"\nChecking {mount_file} - exists: {mount_file.exists()}")
        
        # List mount directory
        print(f"\nMount directory contents:")
        try:
            for item in mountpoint.iterdir():
                print(f"  {item.name}")
        except Exception as e:
            print(f"  Error listing: {e}")
        
        # Reading through mount should find the file (using ff search policy by default)
        content = mount_file.read_text()
        
        # Should get content from first branch (ff policy)
        assert content == "branch_0"
    
    def test_directory_found_across_branches(self, mounted_fs):
        """Test that directories can be found across branches."""
        process, mountpoint, branches = mounted_fs
        
        # Create directory in second branch only
        test_dir = branches[1] / "search_dir"
        test_dir.mkdir()
        
        # Create file in that directory
        (test_dir / "file.txt").write_text("in branch 1")
        
        # Should be able to access through mount
        mount_dir = mountpoint / "search_dir"
        assert mount_dir.exists()
        assert mount_dir.is_dir()
        
        mount_file = mount_dir / "file.txt"
        assert mount_file.exists()
        assert mount_file.read_text() == "in branch 1"
    
    def test_nested_path_search(self, mounted_fs):
        """Test searching for deeply nested paths."""
        process, mountpoint, branches = mounted_fs
        
        # Create nested structure in third branch
        nested_path = branches[2] / "a" / "b" / "c" / "d"
        nested_path.mkdir(parents=True)
        
        nested_file = nested_path / "deep.txt"
        nested_file.write_text("deeply nested")
        
        # Access through mount
        mount_file = mountpoint / "a" / "b" / "c" / "d" / "deep.txt"
        assert mount_file.exists()
        assert mount_file.read_text() == "deeply nested"
    
    def test_file_priority_when_in_multiple_branches(self, mounted_fs):
        """Test that first-found search returns file from first branch."""
        process, mountpoint, branches = mounted_fs
        
        # Create file with different content in each branch
        for i, branch in enumerate(branches):
            test_file = branch / "priority_test.txt"
            test_file.write_text(f"priority_{i}")
            # Small delay to ensure different mtimes
            time.sleep(0.01)
        
        # Reading should get from first branch (ff policy)
        mount_file = mountpoint / "priority_test.txt"
        content = mount_file.read_text()
        assert content == "priority_0"
        
        # Stat should also show attributes from first branch
        stat1 = (branches[0] / "priority_test.txt").stat()
        stat_mount = mount_file.stat()
        
        # Size should match
        assert stat_mount.st_size == stat1.st_size
    
    def test_search_with_symlinks(self, mounted_fs):
        """Test that search works with symbolic links."""
        process, mountpoint, branches = mounted_fs
        
        # Create a file in first branch
        real_file = branches[0] / "real_file.txt"
        real_file.write_text("real content")
        
        # Create symlink in second branch
        link_path = branches[1] / "link_to_file.txt"
        link_path.symlink_to(real_file)
        
        # Both should be accessible through mount
        mount_real = mountpoint / "real_file.txt"
        mount_link = mountpoint / "link_to_file.txt"
        
        assert mount_real.exists()
        assert mount_link.exists()
        # mergerfs-rs now properly detects symlinks
        assert mount_link.is_symlink()
    
    def test_search_performance_many_files(self, mounted_fs):
        """Test that search performs well with many files."""
        process, mountpoint, branches = mounted_fs
        
        # Create many files across branches
        file_count = 100
        for i in range(file_count):
            branch_idx = i % len(branches)
            file_path = branches[branch_idx] / f"perf_test_{i}.txt"
            file_path.write_text(f"content_{i}")
        
        # Time accessing files through mount
        start_time = time.time()
        
        for i in range(file_count):
            mount_file = mountpoint / f"perf_test_{i}.txt"
            assert mount_file.exists()
        
        elapsed = time.time() - start_time
        
        # Should complete reasonably quickly (less than 1 second for 100 files)
        assert elapsed < 1.0, f"Search took too long: {elapsed:.2f}s"
    
    def test_search_with_hidden_files(self, mounted_fs):
        """Test that search works with hidden files."""
        process, mountpoint, branches = mounted_fs
        
        # Create hidden files in different branches
        hidden1 = branches[0] / ".hidden1"
        hidden1.write_text("hidden in branch 0")
        
        hidden2 = branches[1] / ".hidden2"
        hidden2.write_text("hidden in branch 1")
        
        # Both should be accessible
        mount_hidden1 = mountpoint / ".hidden1"
        mount_hidden2 = mountpoint / ".hidden2"
        
        assert mount_hidden1.exists()
        assert mount_hidden1.read_text() == "hidden in branch 0"
        
        assert mount_hidden2.exists()
        assert mount_hidden2.read_text() == "hidden in branch 1"
    
    def test_search_case_sensitivity(self, mounted_fs):
        """Test that search is case-sensitive (on Linux)."""
        process, mountpoint, branches = mounted_fs
        
        # Create files with different cases
        lower_file = branches[0] / "casefile.txt"
        lower_file.write_text("lowercase")
        
        upper_file = branches[1] / "CASEFILE.TXT"
        upper_file.write_text("uppercase")
        
        # Both should be accessible as separate files
        mount_lower = mountpoint / "casefile.txt"
        mount_upper = mountpoint / "CASEFILE.TXT"
        
        assert mount_lower.exists()
        assert mount_lower.read_text() == "lowercase"
        
        assert mount_upper.exists()
        assert mount_upper.read_text() == "uppercase"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])