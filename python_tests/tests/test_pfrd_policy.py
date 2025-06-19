#!/usr/bin/env python3
"""Test Proportional Fill Random Distribution (pfrd) create policy."""

import os
import time
import pytest
from pathlib import Path
from collections import Counter
import statistics


@pytest.mark.integration
class TestPFRDPolicy:
    """Test proportional fill random distribution policy behavior."""
    
    def test_pfrd_basic_distribution(self, mounted_fs_with_policy):
        """Test that pfrd distributes files proportionally to free space."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Set up branches with different free space
        # Branch 0: 10MB used (high free space)
        # Branch 1: 30MB used (medium free space)
        # Branch 2: 50MB used (low free space)
        for i, size in enumerate([10, 30, 50]):
            data_file = branches[i] / f"initial_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'X' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create many files to test distribution
        file_count = 100
        branch_counts = Counter()
        
        for i in range(file_count):
            test_file = mountpoint / f"pfrd_test_{i}.txt"
            test_file.write_text(f"PFRD test file {i}")
            time.sleep(0.01)
            
            # Find which branch got the file
            for j, branch in enumerate(branches):
                if (branch / f"pfrd_test_{i}.txt").exists():
                    branch_counts[j] += 1
                    break
        
        # Branch 0 should get the most files (most free space)
        # Branch 2 should get the least files (least free space)
        assert branch_counts[0] > branch_counts[1], "Branch 0 should get more files than branch 1"
        assert branch_counts[1] > branch_counts[2], "Branch 1 should get more files than branch 2"
        
        # Verify reasonable distribution (not exact due to randomness)
        total = sum(branch_counts.values())
        assert total == file_count
        
        # Branch 0 should get roughly 40-60% of files
        assert 0.3 < branch_counts[0] / total < 0.7, f"Branch 0 distribution out of range: {branch_counts[0]/total}"
    
    def test_pfrd_adapts_to_changing_space(self, mounted_fs_with_policy):
        """Test that pfrd adapts as free space changes."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Initially all branches have equal free space
        for i in range(3):
            init_file = branches[i] / f"init_{i}.bin"
            with open(init_file, 'wb') as f:
                f.write(b'I' * (10 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create first batch of files - should be roughly equal distribution
        first_batch_counts = Counter()
        for i in range(30):
            test_file = mountpoint / f"batch1_{i}.txt"
            test_file.write_text(f"Batch 1 file {i}")
            time.sleep(0.01)
            
            for j, branch in enumerate(branches):
                if (branch / f"batch1_{i}.txt").exists():
                    first_batch_counts[j] += 1
                    break
        
        # Should be roughly equal (10 ± 5 each)
        for count in first_batch_counts.values():
            assert 5 <= count <= 15, f"Initial distribution not balanced: {first_batch_counts}"
        
        # Now significantly reduce free space in branch 0
        huge_file = branches[0] / "huge.bin"
        with open(huge_file, 'wb') as f:
            f.write(b'H' * (60 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create second batch - should avoid branch 0
        second_batch_counts = Counter()
        for i in range(30):
            test_file = mountpoint / f"batch2_{i}.txt"
            test_file.write_text(f"Batch 2 file {i}")
            time.sleep(0.01)
            
            for j, branch in enumerate(branches):
                if (branch / f"batch2_{i}.txt").exists():
                    second_batch_counts[j] += 1
                    break
        
        # Branch 0 should get very few files now
        assert second_batch_counts[0] < 5, f"Branch 0 got too many files: {second_batch_counts[0]}"
        assert second_batch_counts[1] + second_batch_counts[2] > 25, "Branches 1&2 should get most files"
    
    def test_pfrd_minimum_threshold(self, mounted_fs_with_policy):
        """Test pfrd behavior when branches approach minimum free space."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Fill branches to different levels
        # Branch 0: Almost full
        # Branch 1: Half full
        # Branch 2: Mostly empty
        sizes = [80, 40, 10]  # MB used
        for i, size in enumerate(sizes):
            fill_file = branches[i] / f"fill_{i}.bin"
            with open(fill_file, 'wb') as f:
                f.write(b'F' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create files - almost all should go to branch 2
        branch_counts = Counter()
        for i in range(20):
            test_file = mountpoint / f"threshold_test_{i}.txt"
            test_file.write_text(f"Threshold test {i}")
            time.sleep(0.01)
            
            for j, branch in enumerate(branches):
                if (branch / f"threshold_test_{i}.txt").exists():
                    branch_counts[j] += 1
                    break
        
        # Branch 2 should get vast majority
        assert branch_counts[2] >= 15, f"Branch 2 didn't get enough files: {branch_counts}"
        assert branch_counts[0] <= 2, f"Branch 0 got too many files: {branch_counts[0]}"
    
    def test_pfrd_with_directories(self, mounted_fs_with_policy):
        """Test pfrd policy for directory creation."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Set up different free space
        for i, size in enumerate([20, 35, 15]):
            data_file = branches[i] / f"dir_data_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'D' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create multiple directories
        dir_locations = Counter()
        for i in range(10):
            test_dir = mountpoint / f"pfrd_dir_{i}"
            test_dir.mkdir()
            (test_dir / "content.txt").write_text(f"Dir {i} content")
            time.sleep(0.05)
            
            # Find which branch got the directory
            for j, branch in enumerate(branches):
                if (branch / f"pfrd_dir_{i}").exists():
                    dir_locations[j] += 1
                    break
        
        # Branch 2 (least used) should get most directories
        # Branch 1 (most used) should get fewest
        assert dir_locations[2] >= dir_locations[0], "Wrong directory distribution"
        assert dir_locations[2] >= dir_locations[1], "Wrong directory distribution"
    
    def test_pfrd_statistical_properties(self, mounted_fs_with_policy):
        """Test statistical properties of pfrd distribution."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Set up known free space ratios
        # Branch 0: 80% free (20MB used of 100MB)
        # Branch 1: 50% free (50MB used of 100MB)  
        # Branch 2: 20% free (80MB used of 100MB)
        for i, size in enumerate([20, 50, 80]):
            space_file = branches[i] / f"space_{i}.bin"
            with open(space_file, 'wb') as f:
                f.write(b'S' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create large sample for statistical analysis
        sample_size = 200
        selections = []
        
        for i in range(sample_size):
            test_file = mountpoint / f"stats_test_{i}.txt"
            test_file.write_text(f"Stats test {i}")
            time.sleep(0.005)
            
            # Record which branch was selected
            for j, branch in enumerate(branches):
                if (branch / f"stats_test_{i}.txt").exists():
                    selections.append(j)
                    break
        
        # Calculate observed vs expected distributions
        observed_counts = Counter(selections)
        
        # With free space of 80:50:20, we expect roughly:
        # Branch 0: ~53% (80/150)
        # Branch 1: ~33% (50/150)
        # Branch 2: ~13% (20/150)
        
        obs_pct_0 = observed_counts[0] / sample_size
        obs_pct_1 = observed_counts[1] / sample_size
        obs_pct_2 = observed_counts[2] / sample_size
        
        # Allow reasonable variance (±15%)
        assert 0.38 < obs_pct_0 < 0.68, f"Branch 0 frequency {obs_pct_0} outside expected range"
        assert 0.18 < obs_pct_1 < 0.48, f"Branch 1 frequency {obs_pct_1} outside expected range"
        assert 0.03 < obs_pct_2 < 0.28, f"Branch 2 frequency {obs_pct_2} outside expected range"
    
    def test_pfrd_readonly_branch_handling(self, mounted_fs_with_policy):
        """Test pfrd with read-only branches."""
        process, mountpoint, branches = mounted_fs_with_policy("pfrd")
        
        # Make branch 1 read-only
        os.chmod(branches[1], 0o555)
        
        try:
            # Create files - should distribute between branches 0 and 2 only
            branch_counts = Counter()
            for i in range(30):
                test_file = mountpoint / f"ro_test_{i}.txt"
                test_file.write_text(f"RO test {i}")
                time.sleep(0.01)
                
                for j, branch in enumerate(branches):
                    if (branch / f"ro_test_{i}.txt").exists():
                        branch_counts[j] += 1
                        break
            
            # No files in read-only branch
            assert branch_counts[1] == 0, "Files created in read-only branch"
            assert branch_counts[0] > 0, "Branch 0 should have files"
            assert branch_counts[2] > 0, "Branch 2 should have files"
            
        finally:
            os.chmod(branches[1], 0o755)
    
    def test_pfrd_single_branch(self, temp_mountpoint, fuse_manager):
        """Test pfrd with single branch (should work like ff)."""
        branch = Path(tempfile.mkdtemp(prefix="pfrd_single_"))
        try:
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=[branch],
                policy="pfrd"
            ) as (process, mp, branches_list):
                # Should work normally with single branch
                for i in range(5):
                    test_file = mp / f"single_{i}.txt"
                    test_file.write_text(f"Single branch test {i}")
                
                time.sleep(0.1)
                
                # All files in the single branch
                assert len(list(branch.glob("single_*.txt"))) == 5
                
        finally:
            shutil.rmtree(branch)
    
    def test_pfrd_vs_rand_comparison(self, temp_mountpoint, temp_branches, fuse_manager):
        """Compare pfrd vs pure random distribution."""
        # Set up very different free space levels
        # Branch 0: 90% free
        # Branch 1: 50% free
        # Branch 2: 10% free
        for i, size in enumerate([10, 50, 90]):
            fill_file = temp_branches[i] / f"compare_{i}.bin"
            with open(fill_file, 'wb') as f:
                f.write(b'C' * (size * 1024 * 1024))
        
        policies = ["pfrd", "rand"]
        results = {}
        
        for policy in policies:
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=temp_branches,
                policy=policy
            ) as (process, mp, branches_list):
                
                counts = Counter()
                for i in range(60):
                    test_file = mp / f"{policy}_{i}.txt"
                    test_file.write_text(f"Testing {policy}")
                    time.sleep(0.01)
                    
                    for j, branch in enumerate(branches_list):
                        if (branch / f"{policy}_{i}.txt").exists():
                            counts[j] += 1
                            break
                
                results[policy] = counts
        
        # PFRD should heavily favor branch 0 (most free)
        # Random should be roughly equal
        pfrd_ratio_0 = results["pfrd"][0] / sum(results["pfrd"].values())
        rand_ratio_0 = results["rand"][0] / sum(results["rand"].values())
        
        # PFRD should give branch 0 significantly more files than random
        assert pfrd_ratio_0 > rand_ratio_0 + 0.2, f"PFRD not favoring free space: {pfrd_ratio_0} vs {rand_ratio_0}"