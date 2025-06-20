"""
Tests for policy behavior in mergerfs-rs.

These tests verify that different create policies (ff, mfs, lfs) 
behave correctly in real FUSE filesystem scenarios.
"""

import pytest
import os
import time
from pathlib import Path
from typing import List

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@pytest.mark.policy
@pytest.mark.integration
class TestCreatePolicies:
    """Test create policy behavior."""
    
    def test_firstfound_policy_basic(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test FirstFound policy creates files in first writable branch."""
        config = FuseConfig(
            policy="ff",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create test files
            test_files = ["test1.txt", "test2.txt", "test3.txt"]
            
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text(f"Content of {filename}")
                
            # Verify all files went to first branch
            for filename in test_files:
                locations = fs_state.get_file_locations(branches, filename)
                assert locations == [0], f"File {filename} should only be in first branch, found in: {locations}"
                
            # Verify files don't exist in other branches
            for i, branch in enumerate(branches[1:], 1):
                for filename in test_files:
                    assert not (branch / filename).exists(), f"File {filename} should not exist in branch {i}"
    
    def test_mostfreespace_policy_selection(self, fuse_manager: FuseManager, tmpfs_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test MostFreeSpace policy selects branch with most available space."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        config = FuseConfig(
            policy="mfs",
            branches=tmpfs_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create test files - should go to branch with most free space (branch 2)
            test_files = ["mfs_test1.txt", "mfs_test2.txt"]
            
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text(f"MFS content: {filename}")
                
            # Verify files went to branch with most free space (branch 2)
            for filename in test_files:
                locations = fs_state.get_file_locations(branches, filename)
                assert 2 in locations, f"File {filename} should be in branch 2 (most free space - 90MB), found in: {locations}"
                assert len(locations) == 1, f"File {filename} should only be in one branch, found in: {locations}"
    
    def test_leastfreespace_policy_selection(self, fuse_manager: FuseManager, tmpfs_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test LeastFreeSpace policy selects branch with least available space."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        config = FuseConfig(
            policy="lfs",
            branches=tmpfs_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create test files - should go to branch with least free space (branch 0)
            test_files = ["lfs_test1.txt", "lfs_test2.txt"]
            
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text(f"LFS content: {filename}")
                
            # Verify files went to branch with least free space (branch 0)
            for filename in test_files:
                locations = fs_state.get_file_locations(branches, filename)
                assert 0 in locations, f"File {filename} should be in branch 0 (least free space - 8MB), found in: {locations}"
                assert len(locations) == 1, f"File {filename} should only be in one branch, found in: {locations}"
    
    @pytest.mark.parametrize("policy", ["ff", "mfs", "lfs", "rand"])
    def test_policy_file_reading(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, policy: str):
        """Test that files can be read regardless of which policy created them."""
        config = FuseConfig(
            policy=policy,
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create and write test file
            test_content = f"Test content created with {policy} policy"
            test_file = mountpoint / f"{policy}_test.txt"
            test_file.write_text(test_content)
            
            # Read back the content
            read_content = test_file.read_text()
            assert read_content == test_content, f"Content mismatch for {policy} policy"
    
    def test_policy_comparison_same_filesystem(self, fuse_manager: FuseManager, tmpfs_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that different policies behave differently on the same filesystem setup."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        results = {}
        
        # Test each policy with a fresh mountpoint for each
        for i, policy in enumerate(["ff", "mfs", "lfs", "rand"]):
            # Create a unique mountpoint for each test to avoid conflicts
            policy_mountpoint = temp_mountpoint.parent / f"{temp_mountpoint.name}_{policy}"
            
            config = FuseConfig(
                policy=policy,
                branches=tmpfs_branches,
                mountpoint=policy_mountpoint
            )
            
            with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
                test_file = mountpoint / f"{policy}_unique.txt"
                test_file.write_text(f"Created by {policy}")
                
                # Record where the file was created
                locations = fs_state.get_file_locations(branches, f"{policy}_unique.txt")
                results[policy] = locations[0] if locations else -1
        
        # Verify each policy made expected choices
        assert results["ff"] == 0, "FirstFound should use first branch (0)"
        assert results["mfs"] == 2, "MostFreeSpace should use branch with most space (2)"  
        assert results["lfs"] == 0, "LeastFreeSpace should use branch with least space (0)"
        assert results["rand"] in [0, 1, 2], "Random should use one of the available branches"
        
        # Verify MFS and LFS made different choices
        assert results["mfs"] != results["lfs"], "MFS and LFS should select different branches"


@pytest.mark.policy
@pytest.mark.integration
class TestUnionBehavior:
    """Test union filesystem behavior across policies."""
    
    def test_union_directory_listing(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path):
        """Test that union directory listing works correctly."""
        # Pre-populate branches with different files
        (temp_branches[0] / "file_a.txt").write_text("From branch 0")
        (temp_branches[1] / "file_b.txt").write_text("From branch 1") 
        (temp_branches[2] / "file_c.txt").write_text("From branch 2")
        
        # Create shared file in multiple branches (first should take precedence)
        (temp_branches[0] / "shared.txt").write_text("From branch 0")
        (temp_branches[1] / "shared.txt").write_text("From branch 1")
        
        config = FuseConfig(
            policy="ff",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # List directory contents
            files = list(mountpoint.iterdir())
            filenames = {f.name for f in files}
            
            # Should see all unique files (excluding .mergerfs control file)
            expected_files = {"file_a.txt", "file_b.txt", "file_c.txt", "shared.txt"}
            # Remove .mergerfs from the actual filenames set for comparison
            actual_files = filenames - {".mergerfs"}
            assert actual_files == expected_files, f"Expected {expected_files}, got {actual_files}"
            
            # Shared file should show content from first branch
            shared_content = (mountpoint / "shared.txt").read_text()
            assert shared_content == "From branch 0", "Shared file should show content from first branch"
    
    def test_file_precedence(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path):
        """Test that files in earlier branches take precedence."""
        # Create same filename in multiple branches with different content
        (temp_branches[0] / "precedence.txt").write_text("First branch content")
        (temp_branches[1] / "precedence.txt").write_text("Second branch content")
        (temp_branches[2] / "precedence.txt").write_text("Third branch content")
        
        config = FuseConfig(
            policy="ff",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Should read content from first branch
            content = (mountpoint / "precedence.txt").read_text()
            assert content == "First branch content", "Should read from first branch due to precedence"


@pytest.mark.policy 
@pytest.mark.integration
class TestDirectoryOperations:
    """Test directory operations with different policies."""
    
    def test_directory_creation_policies(self, fuse_manager: FuseManager, tmpfs_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that directory creation follows the same policy as file creation."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        # Test MFS policy with directories
        config = FuseConfig(
            policy="mfs",
            branches=tmpfs_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create directory structure
            test_dir = mountpoint / "test_directory"
            test_dir.mkdir()
            
            # Create file in the directory to verify it was created in the right branch
            test_file = test_dir / "file_in_dir.txt"
            test_file.write_text("Content in directory")
            
            # Directory should be created in branch with most free space (branch 2)
            assert (branches[2] / "test_directory").exists(), "Directory should exist in branch 2 (most free space - 90MB)"
            assert not (branches[0] / "test_directory").exists(), "Directory should not exist in branch 0"
            assert not (branches[1] / "test_directory").exists(), "Directory should not exist in branch 1"
            
            # File should also be in the same branch
            assert (branches[2] / "test_directory" / "file_in_dir.txt").exists(), "File should exist in same branch as directory"
    
    def test_nested_directory_creation(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path):
        """Test nested directory creation."""
        config = FuseConfig(
            policy="ff",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create nested directory structure
            nested_dir = mountpoint / "level1" / "level2" / "level3"
            nested_dir.mkdir(parents=True)
            
            # Create file in nested directory
            test_file = nested_dir / "nested_file.txt"
            test_file.write_text("Nested content")
            
            # Verify structure was created in first branch
            assert (branches[0] / "level1" / "level2" / "level3" / "nested_file.txt").exists(), \
                "Nested structure should exist in first branch"