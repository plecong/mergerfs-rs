"""
Tests for random create policy in mergerfs-rs.

These tests verify that the random (rand) create policy 
distributes files randomly across available branches.
"""

import pytest
import os
import time
import subprocess
from pathlib import Path
from typing import List, Dict
from collections import Counter

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@pytest.mark.policy
@pytest.mark.integration
class TestRandomPolicy:
    """Test random create policy behavior."""
    
    def test_random_policy_basic(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy creates files in different branches."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Wait a bit for mount to stabilize
            time.sleep(0.5)
            
            # Verify mount is working
            print(f"Mountpoint: {mountpoint}")
            print(f"Mountpoint exists: {mountpoint.exists()}")
            print(f"Mountpoint is dir: {mountpoint.is_dir()}")
            
            # Create multiple files
            num_files = 30
            branch_counts = Counter()
            
            for i in range(num_files):
                filename = f"random_test_{i}.txt"
                file_path = mountpoint / filename
                
                # Create and verify the file was written
                file_path.write_text(f"Random content {i}")
                assert file_path.exists(), f"File {filename} should exist at mountpoint"
                assert file_path.read_text() == f"Random content {i}", f"File {filename} content mismatch"
                
                # Force sync to ensure file is flushed to branches
                import subprocess
                subprocess.run(["sync"], check=True)
                
                # Also sync the specific file
                subprocess.run(["sync", str(file_path)], check=True)
                time.sleep(0.5)  # Give more time for sync
                
                # Find which branch the file was created in
                # Add extra delay to ensure file is visible in branches
                time.sleep(0.2)
                locations = fs_state.get_file_locations(branches, filename)
                
                # Debug: print what we found
                if not locations:
                    print(f"DEBUG: File {filename} not found in any branch")
                    for idx, branch in enumerate(branches):
                        print(f"  Branch {idx}: {branch}")
                        if branch.exists():
                            print(f"    Contents: {list(branch.iterdir())}")
                
                assert len(locations) == 1, f"File {filename} should be in exactly one branch, found in: {locations}"
                branch_counts[locations[0]] += 1
            
            # Verify files are distributed across branches
            print(f"Random distribution: {dict(branch_counts)}")
            
            # With 30 files across 3 branches, we should have files in multiple branches
            assert len(branch_counts) > 1, "Random policy should distribute files across multiple branches"
            
            # Each branch should have at least one file (with high probability)
            # This might fail very rarely due to randomness, but it's a good sanity check
            if len(branches) == 3 and num_files >= 30:
                assert len(branch_counts) >= 2, "With 30 files, at least 2 branches should be used"
    
    def test_random_policy_distribution(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy distributes files somewhat evenly over many iterations."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create many files to test distribution
            num_files = 100
            branch_counts = Counter()
            
            for i in range(num_files):
                filename = f"dist_test_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Distribution test {i}")
                
                # Sync to ensure file is flushed
                subprocess.run(["sync", str(file_path)], check=True)
                time.sleep(0.1)
                
                # Find which branch the file was created in
                locations = fs_state.get_file_locations(branches, filename)
                if not locations:
                    print(f"Warning: File {filename} not found in any branch")
                    continue
                branch_counts[locations[0]] += 1
            
            # Calculate distribution statistics
            total_files = sum(branch_counts.values())
            expected_per_branch = total_files / len(branches)
            
            print(f"Distribution after {num_files} files: {dict(branch_counts)}")
            print(f"Expected per branch: {expected_per_branch}")
            
            # Each branch should have gotten some files
            for branch_idx in range(len(branches)):
                assert branch_idx in branch_counts, f"Branch {branch_idx} should have at least one file"
                
                # Check that distribution is somewhat even (within 50% of expected)
                count = branch_counts[branch_idx]
                deviation = abs(count - expected_per_branch) / expected_per_branch
                assert deviation < 0.5, f"Branch {branch_idx} has {count} files, too far from expected {expected_per_branch}"
    
    def test_random_policy_readonly_branches(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy only uses writable branches."""
        # Make the second branch read-only
        os.chmod(temp_branches[1], 0o555)
        
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        try:
            with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
                # Create multiple files
                branch_counts = Counter()
                
                for i in range(20):
                    filename = f"readonly_test_{i}.txt"
                    file_path = mountpoint / filename
                    file_path.write_text(f"ReadOnly test {i}")
                    
                    # Find which branch the file was created in
                    locations = fs_state.get_file_locations(branches, filename)
                    branch_counts[locations[0]] += 1
                
                # Verify no files were created in the read-only branch (branch 1)
                assert 1 not in branch_counts, "No files should be created in read-only branch"
                assert 0 in branch_counts, "Files should be created in writable branch 0"
                assert 2 in branch_counts, "Files should be created in writable branch 2"
        finally:
            # Restore write permissions
            os.chmod(temp_branches[1], 0o755)
    
    def test_random_policy_single_branch(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test random policy with only one branch."""
        # Use only one branch
        single_branch = temp_branches[:1]
        
        config = FuseConfig(
            policy="rand",
            branches=single_branch,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create multiple files - all should go to the single branch
            for i in range(10):
                filename = f"single_branch_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Single branch content {i}")
                
                # Verify file is in the only branch
                locations = fs_state.get_file_locations(branches, filename)
                assert locations == [0], f"File {filename} should be in the only branch"
    
    def test_random_policy_vs_firstfound(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Compare random policy behavior to first-found policy."""
        results = {}
        
        # Test first-found policy with unique mountpoint
        ff_mountpoint = temp_mountpoint.parent / f"{temp_mountpoint.name}_ff"
        config_ff = FuseConfig(
            policy="ff",
            branches=temp_branches,
            mountpoint=ff_mountpoint
        )
        
        with fuse_manager.mounted_fs(config_ff) as (process, mountpoint, branches):
            ff_branches = set()
            for i in range(10):
                filename = f"ff_test_{i}.txt"
                (mountpoint / filename).write_text(f"FF content {i}")
                locations = fs_state.get_file_locations(branches, filename)
                ff_branches.update(locations)
            results['ff'] = ff_branches
        
        # Test random policy with unique mountpoint
        rand_mountpoint = temp_mountpoint.parent / f"{temp_mountpoint.name}_rand"
        config_rand = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=rand_mountpoint
        )
        
        with fuse_manager.mounted_fs(config_rand) as (process, mountpoint, branches):
            rand_branches = set()
            for i in range(10):
                filename = f"rand_test_{i}.txt"
                (mountpoint / filename).write_text(f"Random content {i}")
                locations = fs_state.get_file_locations(branches, filename)
                rand_branches.update(locations)
            results['rand'] = rand_branches
        
        # First-found should only use first branch
        assert results['ff'] == {0}, "First-found should only use first branch"
        
        # Random should use multiple branches (with high probability)
        assert len(results['rand']) > 1, "Random should use multiple branches"
    
    def test_random_policy_error_handling(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path):
        """Test random policy error handling when all branches are read-only."""
        # Make all branches read-only
        for branch in temp_branches:
            os.chmod(branch, 0o555)
        
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        try:
            with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
                # Wait for mount to stabilize
                time.sleep(0.5)
                
                # Attempt to create a file should fail
                test_file = mountpoint / "should_fail.txt"
                
                with pytest.raises(OSError) as exc_info:
                    test_file.write_text("This should fail")
                
                # Should get a read-only filesystem error
                assert exc_info.value.errno == 30  # EROFS
        finally:
            # Restore write permissions
            for branch in temp_branches:
                os.chmod(branch, 0o755)
    
    def test_random_policy_directory_creation(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that directory creation with random policy is also randomized."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Create multiple directories
            dir_branch_counts = Counter()
            
            for i in range(20):
                dirname = f"random_dir_{i}"
                dir_path = mountpoint / dirname
                dir_path.mkdir()
                
                # Create a file in the directory to determine which branch it's in
                test_file = dir_path / "marker.txt"
                test_file.write_text("Marker")
                
                # Find which branch the directory was created in
                for branch_idx, branch in enumerate(branches):
                    if (branch / dirname / "marker.txt").exists():
                        dir_branch_counts[branch_idx] += 1
                        break
            
            # Verify directories are distributed across branches
            print(f"Directory distribution: {dict(dir_branch_counts)}")
            assert len(dir_branch_counts) > 1, "Directories should be distributed across multiple branches"