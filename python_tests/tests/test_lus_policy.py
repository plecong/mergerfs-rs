#!/usr/bin/env python3
"""Test Least Used Space (lus) create policy."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.mark.integration
class TestLUSPolicy:
    """Test least used space create policy behavior."""
    
    def test_lus_basic_selection(self, mounted_fs_with_policy):
        """Test that lus selects branch with least used space."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Create different amounts of data in each branch to establish different used space
        # Branch 0: 30MB used
        test_file0 = branches[0] / "existing_data_0.bin"
        with open(test_file0, 'wb') as f:
            f.write(b'A' * (30 * 1024 * 1024))
        
        # Branch 1: 10MB used (least used)
        test_file1 = branches[1] / "existing_data_1.bin"
        with open(test_file1, 'wb') as f:
            f.write(b'B' * (10 * 1024 * 1024))
        
        # Branch 2: 20MB used
        test_file2 = branches[2] / "existing_data_2.bin"
        with open(test_file2, 'wb') as f:
            f.write(b'C' * (20 * 1024 * 1024))
        
        time.sleep(0.2)  # Let filesystem process
        
        # Create new file - should go to branch 1 (least used space)
        new_file = mountpoint / "test_lus.txt"
        new_file.write_text("LUS test content")
        
        time.sleep(0.1)
        
        # Verify file was created in branch 1
        assert not (branches[0] / "test_lus.txt").exists()
        assert (branches[1] / "test_lus.txt").exists()
        assert not (branches[2] / "test_lus.txt").exists()
    
    def test_lus_handles_full_branches(self, mounted_fs_with_policy):
        """Test lus behavior when branches have different capacities."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Create varying amounts of data
        sizes = [50, 30, 40]  # MB
        for i, size in enumerate(sizes):
            test_file = branches[i] / f"data_{i}.bin"
            with open(test_file, 'wb') as f:
                f.write(b'X' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create multiple files - should prefer branch 1 (30MB used)
        for i in range(5):
            test_file = mountpoint / f"lus_test_{i}.txt"
            test_file.write_text(f"Test file {i}")
            time.sleep(0.05)
        
        # Count files in each branch
        branch1_count = sum(1 for f in branches[1].iterdir() if f.name.startswith("lus_test_"))
        
        # Most files should be in branch 1
        assert branch1_count >= 3, f"Expected at least 3 files in branch 1, got {branch1_count}"
    
    def test_lus_updates_on_space_changes(self, mounted_fs_with_policy):
        """Test that lus adapts as space usage changes."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Initially all branches have same used space
        for i in range(3):
            test_file = branches[i] / f"initial_{i}.bin"
            with open(test_file, 'wb') as f:
                f.write(b'I' * (10 * 1024 * 1024))  # 10MB each
        
        time.sleep(0.2)
        
        # First file should go to any branch (all equal)
        test_file1 = mountpoint / "dynamic1.txt"
        test_file1.write_text("First file")
        time.sleep(0.1)
        
        # Add significant data to branch 0
        extra_data = branches[0] / "extra_data.bin"
        with open(extra_data, 'wb') as f:
            f.write(b'E' * (40 * 1024 * 1024))  # 40MB extra
        
        time.sleep(0.2)
        
        # Next files should avoid branch 0
        for i in range(2, 5):
            test_file = mountpoint / f"dynamic{i}.txt"
            test_file.write_text(f"File {i}")
            time.sleep(0.05)
        
        # Branch 0 should have at most 1 dynamic file
        branch0_dynamic = sum(1 for f in branches[0].iterdir() if f.name.startswith("dynamic"))
        assert branch0_dynamic <= 1, f"Branch 0 has too many files: {branch0_dynamic}"
    
    def test_lus_with_directories(self, mounted_fs_with_policy):
        """Test lus policy for directory creation."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Create different used space scenarios
        sizes = [25, 15, 35]  # MB - branch 1 has least used
        for i, size in enumerate(sizes):
            data_file = branches[i] / f"dir_test_data_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'D' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create directory and files
        test_dir = mountpoint / "lus_directory"
        test_dir.mkdir()
        
        for i in range(3):
            (test_dir / f"file_{i}.txt").write_text(f"Content {i}")
            time.sleep(0.05)
        
        # Directory and files should be in branch 1 (least used)
        assert (branches[1] / "lus_directory").exists()
        assert len(list((branches[1] / "lus_directory").iterdir())) == 3
    
    def test_lus_edge_cases(self, temp_mountpoint, fuse_manager):
        """Test lus edge cases like equal space and single branch."""
        # Test with single branch
        branch = Path(tempfile.mkdtemp(prefix="lus_single_"))
        try:
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=[branch],
                policy="lus"
            ) as (process, mp, branches_list):
                # Should work with single branch
                test_file = mp / "single_branch.txt"
                test_file.write_text("Single branch test")
                time.sleep(0.1)
                
                assert (branch / "single_branch.txt").exists()
        finally:
            shutil.rmtree(branch)
    
    def test_lus_readonly_branches(self, mounted_fs_with_policy):
        """Test lus with read-only branches."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Create some initial data
        for i in range(3):
            (branches[i] / f"initial_{i}.txt").write_text(f"Initial {i}")
        
        # Make branch 1 read-only (simulated by removing write permissions)
        os.chmod(branches[1], 0o555)
        
        try:
            # Create files - should skip read-only branch
            for i in range(4):
                test_file = mountpoint / f"ro_test_{i}.txt"
                test_file.write_text(f"RO test {i}")
                time.sleep(0.05)
            
            # No new files should be in branch 1
            branch1_new = sum(1 for f in branches[1].iterdir() if f.name.startswith("ro_test_"))
            assert branch1_new == 0, "Files created in read-only branch"
            
        finally:
            # Restore permissions
            os.chmod(branches[1], 0o755)
    
    def test_lus_space_calculation_accuracy(self, mounted_fs_with_policy):
        """Test that lus accurately tracks used space."""
        process, mountpoint, branches = mounted_fs_with_policy("lus")
        
        # Create precise amounts of data
        # Branch 0: 10MB
        # Branch 1: 20MB  
        # Branch 2: 15MB
        # So order should be: 0 (least), 2, 1 (most)
        
        data_files = []
        sizes = [10, 20, 15]
        for i, size in enumerate(sizes):
            data_file = branches[i] / f"precise_data_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'P' * (size * 1024 * 1024))
            data_files.append(data_file)
        
        time.sleep(0.2)
        
        # Create files one by one and track where they go
        file_locations = []
        for i in range(6):
            test_file = mountpoint / f"precise_test_{i}.txt"
            test_file.write_text(f"Precise test {i}" * 100)  # Small but non-zero
            time.sleep(0.1)
            
            # Find which branch got the file
            for j, branch in enumerate(branches):
                if (branch / f"precise_test_{i}.txt").exists():
                    file_locations.append(j)
                    break
        
        # First few files should prefer branch 0 (least used)
        assert file_locations[0] == 0, f"First file went to branch {file_locations[0]}, expected 0"
        assert file_locations[1] == 0, f"Second file went to branch {file_locations[1]}, expected 0"
    
    def test_lus_with_trace_monitoring(self, mounted_fs_with_trace, smart_wait):
        """Test lus policy with trace monitoring for accurate timing."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        
        # TODO: Update mounted_fs_with_trace to support policy parameter
        # For now, skip if not using lus policy
        
        # Create different used space
        for i, size in enumerate([20, 10, 30]):
            data_file = branches[i] / f"trace_data_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'T' * (size * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create file and wait for it to be visible
        test_file = mountpoint / "trace_lus_test.txt"
        test_file.write_text("Trace LUS test")
        
        # Use smart wait for accurate timing
        assert smart_wait.wait_for_file_visible(test_file)
        
        # Should be in branch 1 (least used - 10MB)
        assert (branches[1] / "trace_lus_test.txt").exists()