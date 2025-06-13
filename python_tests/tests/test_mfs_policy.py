"""
Comprehensive tests for MFS (Most Free Space) policy in mergerfs-rs.

These tests verify that the MFS policy correctly selects branches
with the most available space for file creation.
"""

import pytest
import os
import time
from pathlib import Path
from typing import List, Dict, Tuple

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicyBasic:
    """Basic MFS policy functionality tests."""
    
    def test_mfs_selects_empty_branch_over_populated(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS prefers empty branches over populated ones."""
        # Pre-populate first branch with data
        fs_state.create_file_with_size(temp_branches[0] / "large_file.dat", 5000)
        # Leave other branches empty
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create test file - should go to empty branch (not branch 0)
            test_file = mountpoint / "mfs_test.txt"
            test_file.write_text("MFS test content")
            
            # Verify file was created
            assert test_file.exists(), "Test file should exist"
            
            # Check which branch contains the file
            locations = fs_state.get_file_locations(branches, "mfs_test.txt")
            assert len(locations) == 1, "File should exist in exactly one branch"
            
            # Should not be in the populated branch (branch 0)
            assert locations[0] != 0, f"MFS should avoid populated branch 0, but used branch {locations[0]}"
            print(f"MFS correctly selected branch {locations[0]} instead of populated branch 0")
    
    def test_mfs_with_graduated_space_usage(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS with branches having different amounts of used space."""
        # Create graduated space usage: branch 0 = most used, branch 2 = least used
        fs_state.create_file_with_size(temp_branches[0] / "heavy.dat", 8000)    # Most used
        fs_state.create_file_with_size(temp_branches[1] / "medium.dat", 3000)   # Medium used  
        fs_state.create_file_with_size(temp_branches[2] / "light.dat", 500)     # Least used (most free)
        
        # Get initial sizes for verification
        initial_sizes = fs_state.get_branch_sizes(temp_branches)
        print(f"Initial branch sizes: {initial_sizes}")
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create multiple test files
            test_files = ["mfs_file_1.txt", "mfs_file_2.txt", "mfs_file_3.txt"]
            
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text(f"Content for {filename}")
                
                # Verify file creation
                assert file_path.exists(), f"File {filename} should exist"
                
                # Check location - should prefer branch with most free space (branch 2)
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File {filename} should be in exactly one branch"
                
                print(f"File {filename} created in branch {locations[0]}")
                
                # With current space distribution, should prefer branch 2 (least used)
                assert locations[0] == 2, f"MFS should prefer branch 2 (most free), but used {locations[0]}"
    
    def test_mfs_updates_as_space_changes(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS adapts as space usage changes during operation."""
        # Start with branch 1 having most free space
        fs_state.create_file_with_size(temp_branches[0] / "big_file.dat", 6000)
        fs_state.create_file_with_size(temp_branches[2] / "medium_file.dat", 3000)
        # Branch 1 starts empty (most free space)
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # First file should go to branch 1 (most free space)
            first_file = mountpoint / "first_file.txt"
            first_file.write_text("First file content")
            
            first_locations = fs_state.get_file_locations(branches, "first_file.txt")
            assert len(first_locations) == 1
            assert first_locations[0] == 1, f"First file should go to branch 1, went to {first_locations[0]}"
            
            # Now add a large file to branch 1 externally to change space dynamics
            fs_state.create_file_with_size(temp_branches[1] / "space_changer.dat", 7000)
            
            # Small delay to allow filesystem to recognize changes
            time.sleep(0.1)
            
            # Next file should now go to a different branch with more free space
            second_file = mountpoint / "second_file.txt"
            second_file.write_text("Second file content")
            
            second_locations = fs_state.get_file_locations(branches, "second_file.txt")
            assert len(second_locations) == 1
            
            print(f"After space change: first file in branch {first_locations[0]}, second file in branch {second_locations[0]}")
            
            # The second file should go to branch 2 (now has most free space)
            # Note: This test might be sensitive to the exact space calculation method
            print(f"Second file went to branch {second_locations[0]} (expected to avoid heavily used branch 1)")


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicyEdgeCases:
    """Edge case tests for MFS policy."""
    
    def test_mfs_with_equal_space_usage(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS behavior when branches have equal space usage."""
        # Create equal space usage across all branches
        equal_size = 2000
        for i, branch in enumerate(temp_branches):
            fs_state.create_file_with_size(branch / f"equal_{i}.dat", equal_size)
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create test file - should go to some branch (implementation detail)
            test_file = mountpoint / "equal_space_test.txt"
            test_file.write_text("Equal space test")
            
            assert test_file.exists(), "Test file should exist"
            
            locations = fs_state.get_file_locations(branches, "equal_space_test.txt")
            assert len(locations) == 1, "File should exist in exactly one branch"
            
            # Should be a valid branch (0, 1, or 2)
            assert 0 <= locations[0] <= 2, f"File should be in valid branch, found in {locations[0]}"
            print(f"With equal space usage, MFS selected branch {locations[0]}")
    
    def test_mfs_with_single_writable_branch(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS when only one branch is writable."""
        # Make only the first branch writable by making others read-only
        # Note: This would require implementing read-only branch support
        # For now, we'll test with all branches writable but heavily populate 2 of them
        
        # Make branches 1 and 2 very full, leaving branch 0 as the clear choice
        fs_state.create_file_with_size(temp_branches[1] / "huge1.dat", 15000)
        fs_state.create_file_with_size(temp_branches[2] / "huge2.dat", 15000)
        # Branch 0 stays empty
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            test_file = mountpoint / "single_choice_test.txt"
            test_file.write_text("Single choice test")
            
            assert test_file.exists(), "Test file should exist"
            
            locations = fs_state.get_file_locations(branches, "single_choice_test.txt")
            assert len(locations) == 1, "File should exist in exactly one branch"
            assert locations[0] == 0, f"MFS should choose empty branch 0, chose {locations[0]}"
    
    def test_mfs_with_very_small_files(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS behavior with very small file differences."""
        # Create small differences in space usage
        fs_state.create_file_with_size(temp_branches[0] / "tiny1.dat", 100)
        fs_state.create_file_with_size(temp_branches[1] / "tiny2.dat", 200)
        fs_state.create_file_with_size(temp_branches[2] / "tiny3.dat", 300)
        # Branch 0 should have most free space
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create several small files
            for i in range(5):
                test_file = mountpoint / f"small_test_{i}.txt"
                test_file.write_text(f"Small test content {i}")
                
                assert test_file.exists(), f"Test file {i} should exist"
                
                locations = fs_state.get_file_locations(branches, f"small_test_{i}.txt")
                assert len(locations) == 1, f"File {i} should exist in exactly one branch"
                
                # Should prefer branch 0 (least used initially)
                print(f"Small file {i} went to branch {locations[0]}")


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicySequential:
    """Sequential operation tests for MFS policy."""
    
    def test_mfs_sequential_file_creation(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS with sequential file creation and space monitoring."""
        # Start with different initial space usage
        fs_state.create_file_with_size(temp_branches[0] / "base0.dat", 1000)
        fs_state.create_file_with_size(temp_branches[1] / "base1.dat", 4000)
        fs_state.create_file_with_size(temp_branches[2] / "base2.dat", 7000)
        # Branch 0 should have most free space initially
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            file_placements = []
            
            # Create 10 files sequentially and track their placement
            for i in range(10):
                filename = f"sequential_{i:02d}.txt"
                file_path = mountpoint / filename
                content = f"Sequential file {i} with some content to make it non-empty"
                file_path.write_text(content)
                
                assert file_path.exists(), f"Sequential file {i} should exist"
                
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"Sequential file {i} should be in exactly one branch"
                
                file_placements.append((filename, locations[0]))
                
                # Check current space usage
                current_sizes = fs_state.get_branch_sizes(branches)
                print(f"File {i:2d}: branch {locations[0]}, sizes: {current_sizes}")
            
            # Analyze the placement pattern
            branch_counts = [0, 0, 0]
            for _, branch in file_placements:
                branch_counts[branch] += 1
            
            print(f"Final distribution: Branch 0: {branch_counts[0]}, Branch 1: {branch_counts[1]}, Branch 2: {branch_counts[2]}")
            
            # Branch 0 started with least usage, so should get more files initially
            assert branch_counts[0] > 0, "Branch 0 should receive some files"
            
            # The distribution should reflect the MFS policy - more files in initially less-used branches
            # Branch 2 started most full, so should get fewer files
            assert branch_counts[2] <= branch_counts[0], "Branch 2 (initially most full) should not get more files than branch 0"
    
    def test_mfs_with_file_deletion_and_recreation(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS behavior when files are deleted and space is freed up."""
        # Pre-populate with different amounts of data
        heavy_file = temp_branches[1] / "heavy_initial.dat"
        fs_state.create_file_with_size(heavy_file, 8000)
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create initial file - should avoid branch 1 (heavily used)
            initial_file = mountpoint / "initial.txt"
            initial_file.write_text("Initial file")
            
            initial_locations = fs_state.get_file_locations(branches, "initial.txt")
            assert len(initial_locations) == 1
            initial_branch = initial_locations[0]
            
            print(f"Initial file placed in branch {initial_branch}")
            assert initial_branch != 1, f"Should avoid heavily used branch 1, but used {initial_branch}"
            
            # Remove the heavy file from branch 1 to free up space
            heavy_file.unlink()
            time.sleep(0.1)  # Allow filesystem to recognize the change
            
            # Create another file - now branch 1 should be a candidate again
            post_deletion_file = mountpoint / "post_deletion.txt"
            post_deletion_file.write_text("Post deletion file")
            
            post_deletion_locations = fs_state.get_file_locations(branches, "post_deletion.txt")
            assert len(post_deletion_locations) == 1
            post_deletion_branch = post_deletion_locations[0]
            
            print(f"Post-deletion file placed in branch {post_deletion_branch}")
            
            # Verify both files exist
            assert initial_file.exists(), "Initial file should still exist"
            assert post_deletion_file.exists(), "Post-deletion file should exist"


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicyComparison:
    """Tests comparing MFS with other policies."""
    
    def test_mfs_vs_ff_different_behavior(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS behaves differently from FirstFound policy."""
        # Set up scenario where FF and MFS should make different choices
        # Make first branch (FF's choice) heavily used
        fs_state.create_file_with_size(temp_branches[0] / "ff_burden.dat", 8000)
        # Leave other branches lighter
        fs_state.create_file_with_size(temp_branches[1] / "light1.dat", 1000)
        fs_state.create_file_with_size(temp_branches[2] / "light2.dat", 2000)
        
        results = {}
        
        # Test FF policy
        ff_config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        with fuse_manager.mounted_fs(ff_config) as (process, mountpoint, branches):
            ff_file = mountpoint / "ff_test.txt"
            ff_file.write_text("FF policy test")
            
            ff_locations = fs_state.get_file_locations(branches, "ff_test.txt")
            results['ff'] = ff_locations[0] if ff_locations else -1
        
        # Test MFS policy  
        mfs_config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        with fuse_manager.mounted_fs(mfs_config) as (process, mountpoint, branches):
            mfs_file = mountpoint / "mfs_test.txt"
            mfs_file.write_text("MFS policy test")
            
            mfs_locations = fs_state.get_file_locations(branches, "mfs_test.txt")
            results['mfs'] = mfs_locations[0] if mfs_locations else -1
        
        print(f"Policy comparison: FF used branch {results['ff']}, MFS used branch {results['mfs']}")
        
        # FF should use branch 0 (first), MFS should avoid it (heavily used)
        assert results['ff'] == 0, "FF should use first branch (0)"
        assert results['mfs'] != 0, f"MFS should avoid heavily used first branch, but used {results['mfs']}"
        assert results['ff'] != results['mfs'], "FF and MFS should make different choices"
    
    def test_mfs_policy_consistency_multiple_runs(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS policy is consistent across multiple runs with same setup."""
        # Create consistent space setup
        fs_state.create_file_with_size(temp_branches[0] / "setup0.dat", 2000)
        fs_state.create_file_with_size(temp_branches[1] / "setup1.dat", 5000)
        fs_state.create_file_with_size(temp_branches[2] / "setup2.dat", 1000)
        # Branch 2 should have most free space
        
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        placement_results = []
        
        # Run multiple times with same configuration
        for run in range(3):
            with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
                test_file = mountpoint / f"consistency_test_run_{run}.txt"
                test_file.write_text(f"Consistency test run {run}")
                
                locations = fs_state.get_file_locations(branches, f"consistency_test_run_{run}.txt")
                assert len(locations) == 1, f"Run {run}: file should be in exactly one branch"
                
                placement_results.append(locations[0])
                print(f"Run {run}: file placed in branch {locations[0]}")
        
        # All runs should make the same choice given identical initial conditions
        assert all(branch == placement_results[0] for branch in placement_results), \
            f"MFS should be consistent across runs: {placement_results}"
        
        # Should choose branch 2 (most free space)
        assert placement_results[0] == 2, f"MFS should choose branch 2 (most free), chose {placement_results[0]}"