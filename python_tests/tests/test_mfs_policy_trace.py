"""
Comprehensive tests for MFS (Most Free Space) policy in mergerfs-rs with trace-based waiting.

These tests verify that the MFS policy correctly selects branches
with the most available space for file creation.
"""

import pytest
import os
import time
from pathlib import Path
from typing import List, Dict, Tuple

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState
from lib.simple_trace import SimpleTraceMonitor, SimpleWaitHelper


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicyBasicWithTrace:
    """Basic MFS policy functionality tests with trace-based waiting."""
    
    def test_mfs_selects_empty_branch_over_populated(
        self,
        fuse_manager: FuseManager,
        tmpfs_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS prefers empty branches over populated ones."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        config = FuseConfig(policy="mfs", branches=tmpfs_branches, mountpoint=temp_mountpoint)
        
        # Mount with trace monitoring
        process = fuse_manager.mount(config)
        trace_monitor = SimpleTraceMonitor(process)
        trace_monitor.start_capture()
        wait_helper = SimpleWaitHelper(trace_monitor)
        
        try:
            mountpoint = config.mountpoint
            branches = config.branches
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Debug: Check mount is working
            print(f"Mountpoint: {mountpoint}")
            print(f"Mountpoint exists: {mountpoint.exists()}")
            print(f"Branches: {branches}")
            
            # Create test file - should go to empty branch (not branch 0)
            test_file = mountpoint / "mfs_test.txt"
            test_file.write_text("MFS test content")
            
            # Wait for file creation to complete
            assert wait_helper.wait_for_file_visible(test_file), "Test file not visible"
            assert wait_helper.wait_for_write_complete(test_file), "Write not complete"
            
            # Verify file was created
            assert test_file.exists(), "Test file should exist"
            print(f"Test file created at: {test_file}")
            print(f"Test file content: {test_file.read_text()}")
            
            # Check which branch contains the file
            locations = fs_state.get_file_locations(branches, "mfs_test.txt")
            assert len(locations) == 1, f"File should exist in exactly one branch, found in {len(locations)} branches"
            
            # Should be in branch 2 (most free space - 90MB)
            assert locations[0] == 2, f"MFS should select branch 2 (most free space), but used branch {locations[0]}"
            print(f"MFS correctly selected branch {locations[0]} (most free space)")
        finally:
            trace_monitor.stop_capture()
            fuse_manager.unmount(mountpoint)
    
    def test_mfs_with_graduated_space_usage(
        self,
        fuse_manager: FuseManager,
        tmpfs_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test MFS with branches having different amounts of used space."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        config = FuseConfig(policy="mfs", branches=tmpfs_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Create multiple test files
            test_files = ["mfs_file_1.txt", "mfs_file_2.txt", "mfs_file_3.txt"]
            
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text(f"Content for {filename}")
                
                # Wait for file operations to complete
                assert wait_helper.wait_for_file_visible(file_path), f"File {filename} not visible"
                
                # Verify file creation
                assert file_path.exists(), f"File {filename} should exist"
                
                # Check location - should prefer branch with most free space (branch 2)
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File {filename} should be in exactly one branch"
                
                print(f"File {filename} created in branch {locations[0]}")
                
                # With current space distribution, should prefer branch 2 (least used)
                assert locations[0] == 2, f"MFS should prefer branch 2 (most free), but used {locations[0]}"
            
            trace_monitor.stop_capture()
    
    def test_mfs_updates_as_space_changes(
        self,
        fuse_manager: FuseManager,
        tmpfs_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS adapts as space usage changes during operation."""
        # tmpfs_branches start with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        # Adjust the space to make branch 1 have the most initially
        fs_state.create_file_with_size(tmpfs_branches[2] / "large_file.dat", 60 * 1024 * 1024)  # 60MB file
        # Now: branch 0: 8MB, branch 1: 40MB, branch 2: ~30MB
        
        config = FuseConfig(policy="mfs", branches=tmpfs_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # First file should go to branch 1 (most free space)
            first_file = mountpoint / "first_file.txt"
            first_file.write_text("First file content")
            
            assert wait_helper.wait_for_file_visible(first_file), "First file not visible"
            
            first_locations = fs_state.get_file_locations(branches, "first_file.txt")
            assert len(first_locations) == 1
            assert first_locations[0] == 1, f"First file should go to branch 1, went to {first_locations[0]}"
            
            # Now add a large file to branch 1 externally to change space dynamics
            fs_state.create_file_with_size(tmpfs_branches[1] / "space_changer.dat", 35 * 1024 * 1024)  # 35MB file
            
            # Wait for filesystem to recognize changes (trace can't see external changes)
            time.sleep(0.2)
            
            # Next file should now go to a different branch with more free space
            second_file = mountpoint / "second_file.txt"
            second_file.write_text("Second file content")
            
            assert wait_helper.wait_for_file_visible(second_file), "Second file not visible"
            
            second_locations = fs_state.get_file_locations(branches, "second_file.txt")
            assert len(second_locations) == 1
            
            print(f"After space change: first file in branch {first_locations[0]}, second file in branch {second_locations[0]}")
            
            # The second file should go to branch 2 (now has most free space)
            print(f"Second file went to branch {second_locations[0]} (expected to avoid heavily used branch 1)")
            
            trace_monitor.stop_capture()


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicySequentialWithTrace:
    """Sequential operation tests for MFS policy with trace-based waiting."""
    
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
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Create initial file - should avoid branch 1 (heavily used)
            initial_file = mountpoint / "initial.txt"
            initial_file.write_text("Initial file")
            
            assert wait_helper.wait_for_file_visible(initial_file), "Initial file not visible"
            
            initial_locations = fs_state.get_file_locations(branches, "initial.txt")
            assert len(initial_locations) == 1
            initial_branch = initial_locations[0]
            
            print(f"Initial file placed in branch {initial_branch}")
            assert initial_branch != 1, f"Should avoid heavily used branch 1, but used {initial_branch}"
            
            # Remove the heavy file from branch 1 to free up space
            heavy_file.unlink()
            
            # Wait for filesystem to recognize the change
            time.sleep(0.2)  # Still need small delay for external changes
            
            # Create another file - now branch 1 should be a candidate again
            post_deletion_file = mountpoint / "post_deletion.txt"
            post_deletion_file.write_text("Post deletion file")
            
            assert wait_helper.wait_for_file_visible(post_deletion_file), "Post-deletion file not visible"
            
            post_deletion_locations = fs_state.get_file_locations(branches, "post_deletion.txt")
            assert len(post_deletion_locations) == 1
            post_deletion_branch = post_deletion_locations[0]
            
            print(f"Post-deletion file placed in branch {post_deletion_branch}")
            
            # Verify both files exist
            assert initial_file.exists(), "Initial file should still exist"
            assert post_deletion_file.exists(), "Post-deletion file should exist"
            
            trace_monitor.stop_capture()


@pytest.mark.policy
@pytest.mark.integration
class TestMFSPolicyComparisonWithTrace:
    """Tests comparing MFS with other policies using trace-based waiting."""
    
    def test_mfs_vs_ff_different_behavior(
        self,
        fuse_manager: FuseManager,
        tmpfs_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that MFS behaves differently from FirstFound policy."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)
        # branch 2: 90MB free (most)
        
        results = {}
        
        # Test FF policy - create a new mountpoint for FF test
        ff_mountpoint = fuse_manager.create_temp_mountpoint()
        ff_config = FuseConfig(policy="ff", branches=tmpfs_branches, mountpoint=ff_mountpoint)
        with fuse_manager.mounted_fs(ff_config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "FF mount did not become ready"
            
            ff_file = mountpoint / "ff_test.txt"
            ff_file.write_text("FF policy test")
            
            assert wait_helper.wait_for_file_visible(ff_file), "FF file not visible"
            
            ff_locations = fs_state.get_file_locations(branches, "ff_test.txt")
            results['ff'] = ff_locations[0] if ff_locations else -1
            
            trace_monitor.stop_capture()
        
        # Test MFS policy - create a new mountpoint for MFS test
        mfs_mountpoint = fuse_manager.create_temp_mountpoint()
        mfs_config = FuseConfig(policy="mfs", branches=tmpfs_branches, mountpoint=mfs_mountpoint)
        with fuse_manager.mounted_fs(mfs_config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "MFS mount did not become ready"
            
            mfs_file = mountpoint / "mfs_test.txt"
            mfs_file.write_text("MFS policy test")
            
            assert wait_helper.wait_for_file_visible(mfs_file), "MFS file not visible"
            
            mfs_locations = fs_state.get_file_locations(branches, "mfs_test.txt")
            results['mfs'] = mfs_locations[0] if mfs_locations else -1
            
            trace_monitor.stop_capture()
        
        print(f"Policy comparison: FF used branch {results['ff']}, MFS used branch {results['mfs']}")
        
        # FF should use branch 0 (first), MFS should use branch 2 (most free space)
        assert results['ff'] == 0, "FF should use first branch (0)"
        assert results['mfs'] == 2, f"MFS should use branch with most free space (2), but used {results['mfs']}"
        assert results['ff'] != results['mfs'], "FF and MFS should make different choices"