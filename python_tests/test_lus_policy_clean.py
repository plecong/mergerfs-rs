#!/usr/bin/env python3
"""
Clean integration tests for the 'lus' (least used space) create policy.
Uses the new mounted_fs_with_policy fixture for cleaner setup.
"""

import os
import pytest
import time
from pathlib import Path
from typing import List, Tuple


@pytest.mark.integration
class TestLeastUsedSpacePolicy:
    """Test the 'lus' create policy behavior."""
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_empty_branches(self, mounted_fs_with_policy):
        """Test LUS behavior when all branches are empty."""
        # Extract components based on whether trace is enabled
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # All branches have 0 used space, should pick first one
        test_file = mountpoint / "first_file.txt"
        test_file.write_text("first")
        time.sleep(0.1)  # Brief wait for filesystem
        
        # Should go to first branch when all have equal (zero) used space
        assert (branches[0] / "first_file.txt").exists()
        assert not (branches[1] / "first_file.txt").exists()
        assert not (branches[2] / "first_file.txt").exists()
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_selects_least_used(self, mounted_fs_with_policy):
        """Test that LUS selects the branch with least used space."""
        # Extract components
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # Pre-fill branches with different amounts of data directly (not through FUSE)
        # This ensures we're testing based on actual filesystem usage
        
        # Branch 0 (100MB tmpfs): Create 80MB of data (most used)
        print("\nCreating 80MB on branch 0...")
        for i in range(80):
            (branches[0] / f"prefill_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Branch 1 (200MB tmpfs): Create 50MB of data
        print("Creating 50MB on branch 1...")
        for i in range(50):
            (branches[1] / f"prefill_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Branch 2 (500MB tmpfs): Create 10MB of data (least used)
        print("Creating 10MB on branch 2...")
        for i in range(10):
            (branches[2] / f"prefill_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Show actual usage
        print("\nActual tmpfs usage:")
        for idx, branch in enumerate(branches):
            stat = os.statvfs(str(branch))
            used_bytes = (stat.f_blocks - stat.f_bavail) * stat.f_frsize
            total_bytes = stat.f_blocks * stat.f_frsize
            print(f"Branch {idx}: {used_bytes/(1024*1024):.1f}MB used of {total_bytes/(1024*1024):.0f}MB")
        
        # Create new file through FUSE - should go to branch 2 (least used)
        test_file = mountpoint / "test_lus.txt"
        test_file.write_text("test content")
        time.sleep(0.1)  # Brief wait
        
        # Check it went to branch 2 (500MB tmpfs with only 10MB used)
        assert (branches[2] / "test_lus.txt").exists(), \
            "File should be on branch 2 (least used space)"
        assert not (branches[0] / "test_lus.txt").exists()
        assert not (branches[1] / "test_lus.txt").exists()
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_distribution(self, mounted_fs_with_policy):
        """Test that LUS distributes files to balance usage."""
        # Extract components
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # Start with empty branches, create multiple files
        file_counts = {0: 0, 1: 0, 2: 0}
        
        # Create 9 files (3 per branch ideally)
        for i in range(9):
            test_file = mountpoint / f"file_{i}.txt"
            test_file.write_text(f"content {i}" * 100)  # Make files ~1KB each
            time.sleep(0.05)  # Small delay between files
            
            # Check which branch got it
            for idx, branch in enumerate(branches):
                if (branch / f"file_{i}.txt").exists():
                    file_counts[idx] += 1
                    break
        
        print(f"\nFile distribution: {file_counts}")
        
        # With LUS, files should distribute evenly when starting empty
        # Each branch should get some files
        assert all(count > 0 for count in file_counts.values()), \
            f"All branches should have files: {file_counts}"
        
        # Should be relatively balanced (within 2 files)
        assert max(file_counts.values()) - min(file_counts.values()) <= 2, \
            f"Distribution should be balanced: {file_counts}"
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_fills_smallest_first(self, mounted_fs_with_policy):
        """Test that LUS continues to select least used branch as it fills."""
        # Extract components
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # Create initial imbalance - branch 2 should have least used space
        print("\nCreating initial data...")
        for i in range(5):
            (branches[0] / f"init_{i}.dat").write_bytes(b"x" * (10 * 1024 * 1024))  # 50MB on branch 0
        for i in range(3):
            (branches[1] / f"init_{i}.dat").write_bytes(b"x" * (10 * 1024 * 1024))  # 30MB on branch 1
        # Branch 2 starts empty (0MB)
        
        # Create 10 files through FUSE, track placement
        branch2_count = 0
        for i in range(10):
            test_file = mountpoint / f"test_{i}.txt"
            test_file.write_bytes(b"x" * (1024 * 1024))  # 1MB each
            time.sleep(0.05)  # Small delay
            
            if (branches[2] / f"test_{i}.txt").exists():
                branch2_count += 1
        
        # Most files should go to branch 2 (started with least used)
        print(f"\nFiles on branch 2: {branch2_count}/10")
        assert branch2_count >= 7, \
            f"Expected most files on branch 2, got {branch2_count}/10"
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_with_tmpfs_different_sizes(self, mounted_fs_with_policy):
        """Test LUS behavior with tmpfs mounts of different sizes."""
        # Extract components
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # Show the tmpfs mount sizes
        print("\nTmpfs mount information:")
        for idx, branch in enumerate(branches):
            stat = os.statvfs(str(branch))
            total_mb = (stat.f_blocks * stat.f_frsize) / (1024 * 1024)
            avail_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
            used_mb = ((stat.f_blocks - stat.f_bavail) * stat.f_frsize) / (1024 * 1024)
            print(f"Branch {idx} ({branch.name}): {total_mb:.0f}MB total, "
                  f"{used_mb:.1f}MB used, {avail_mb:.1f}MB available")
        
        # Create a test file - with all empty, should go to first branch
        test_file = mountpoint / "tmpfs_test.txt"
        test_file.write_text("test on tmpfs")
        time.sleep(0.1)  # Brief wait
        
        # Verify file was created on one of the branches
        found = False
        for idx, branch in enumerate(branches):
            if (branch / "tmpfs_test.txt").exists():
                print(f"\nFile created on branch {idx} ({branch.name})")
                found = True
                break
        
        assert found, "File should be created on one of the tmpfs branches"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])