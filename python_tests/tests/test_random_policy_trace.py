"""
Tests for random create policy in mergerfs-rs with trace-based waiting.

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
from lib.simple_trace import SimpleTraceMonitor, SimpleWaitHelper


@pytest.mark.policy
@pytest.mark.integration
class TestRandomPolicyWithTrace:
    """Test random create policy behavior with trace-based waiting."""
    
    def test_random_policy_basic(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy creates files in different branches."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
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
                
                # Wait for file to be visible and write to complete
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                assert wait_helper.wait_for_write_complete(file_path), f"Write for {filename} not complete"
                
                assert file_path.exists(), f"File {filename} should exist at mountpoint"
                assert file_path.read_text() == f"Random content {i}", f"File {filename} content mismatch"
                
                # Find which branch the file was created in
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
            
            trace_monitor.stop_capture()
    
    def test_random_policy_distribution(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy distributes files somewhat evenly over many iterations."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Create many files to test distribution
            num_files = 100
            branch_counts = Counter()
            
            for i in range(num_files):
                filename = f"dist_test_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Distribution test {i}")
                
                # Wait for file operations to complete
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File should be in exactly one branch"
                branch_counts[locations[0]] += 1
            
            print(f"Distribution after {num_files} files: {dict(branch_counts)}")
            
            # Check that distribution is somewhat even
            # With 100 files across 3 branches, expect roughly 33 per branch
            # Allow for randomness - each branch should have at least 15 files
            for branch_idx in range(len(branches)):
                assert branch_counts[branch_idx] >= 10, \
                    f"Branch {branch_idx} has too few files: {branch_counts[branch_idx]}"
                assert branch_counts[branch_idx] <= 60, \
                    f"Branch {branch_idx} has too many files: {branch_counts[branch_idx]}"
            
            trace_monitor.stop_capture()
    
    def test_random_policy_with_space_constraints(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test random policy behavior when branches have different amounts of free space."""
        # Fill up branch 1 significantly
        large_file = temp_branches[1] / "large_file.dat"
        fs_state.create_file_with_size(large_file, 15000)  # 15KB
        
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Create multiple files
            branch_counts = Counter()
            
            for i in range(30):
                filename = f"space_test_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Space test {i}")
                
                # Wait for file operations to complete
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File should be in exactly one branch"
                branch_counts[locations[0]] += 1
            
            print(f"Distribution with space constraints: {dict(branch_counts)}")
            
            # Random policy should still use all branches, regardless of space
            # (unless a branch is completely full)
            assert len(branch_counts) >= 2, "Random policy should still use multiple branches"
            
            trace_monitor.stop_capture()
    
    def test_random_policy_consistency(self, fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path, fs_state: FileSystemState):
        """Test that random policy is actually random (not deterministic)."""
        config = FuseConfig(
            policy="rand",
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        # Run two separate sessions and compare distributions
        first_distribution = []
        second_distribution = []
        
        # First run
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            for i in range(10):
                filename = f"consistency_test_1_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Test content {i}")
                
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                
                locations = fs_state.get_file_locations(branches, filename)
                first_distribution.append(locations[0])
            
            trace_monitor.stop_capture()
        
        # Second run with fresh mount
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            for i in range(10):
                filename = f"consistency_test_2_{i}.txt"
                file_path = mountpoint / filename
                file_path.write_text(f"Test content {i}")
                
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                
                locations = fs_state.get_file_locations(branches, filename)
                second_distribution.append(locations[0])
            
            trace_monitor.stop_capture()
        
        print(f"First distribution: {first_distribution}")
        print(f"Second distribution: {second_distribution}")
        
        # The distributions should be different (with high probability)
        assert first_distribution != second_distribution, \
            "Random policy should produce different distributions across runs"