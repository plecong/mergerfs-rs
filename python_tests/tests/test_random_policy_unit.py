"""
Unit tests for random create policy in mergerfs-rs.

These tests verify the random policy implementation directly,
without going through the FUSE layer.
"""

import pytest
import os
import tempfile
from pathlib import Path
from typing import List
from collections import Counter
import subprocess

@pytest.mark.unit
class TestRandomPolicyUnit:
    """Direct unit tests for random policy."""
    
    def test_random_distribution_direct(self):
        """Test random policy by calling mergerfs-rs directly and checking branch contents."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create branches
            branches = []
            for i in range(3):
                branch = temp_path / f"branch_{i}"
                branch.mkdir()
                branches.append(branch)
            
            # Create mountpoint
            mountpoint = temp_path / "mount"
            mountpoint.mkdir()
            
            # Start mergerfs-rs with random policy
            cmd = [
                str(Path.cwd().parent / "target" / "release" / "mergerfs-rs"),
                "-o", "func.create=rand",
                str(mountpoint)
            ] + [str(b) for b in branches]
            
            process = subprocess.Popen(cmd)
            
            try:
                # Wait for mount
                import time
                time.sleep(1)
                
                # Create files directly through filesystem operations
                branch_counts = Counter()
                
                for i in range(30):
                    filename = f"test_{i}.txt"
                    filepath = mountpoint / filename
                    
                    # Write file
                    filepath.write_text(f"Content {i}")
                    
                    # Force sync
                    subprocess.run(["sync"], check=True)
                    time.sleep(0.1)
                    
                    # Check which branch got the file
                    for branch_idx, branch in enumerate(branches):
                        if (branch / filename).exists():
                            branch_counts[branch_idx] += 1
                            break
                
                print(f"Distribution: {dict(branch_counts)}")
                
                # Verify random distribution
                assert len(branch_counts) > 1, "Random should use multiple branches"
                
                # Each branch should have at least one file (with high probability)
                if sum(branch_counts.values()) >= 30:
                    assert len(branch_counts) >= 2, "Should use at least 2 branches with 30 files"
                
            finally:
                # Cleanup
                process.terminate()
                process.wait()
                
                # Unmount
                subprocess.run(["fusermount", "-u", str(mountpoint)], capture_output=True)
    
    def test_random_policy_with_echo(self):
        """Test random policy using echo commands instead of Python file writes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create branches
            branches = []
            for i in range(3):
                branch = temp_path / f"branch_{i}"
                branch.mkdir()
                branches.append(branch)
            
            # Create mountpoint
            mountpoint = temp_path / "mount"
            mountpoint.mkdir()
            
            # Start mergerfs-rs with random policy
            cmd = [
                str(Path.cwd().parent / "target" / "release" / "mergerfs-rs"),
                "-o", "func.create=rand",
                str(mountpoint)
            ] + [str(b) for b in branches]
            
            process = subprocess.Popen(cmd)
            
            try:
                # Wait for mount
                import time
                time.sleep(1)
                
                # Create files using echo command
                branch_counts = Counter()
                
                for i in range(20):
                    filename = f"echo_test_{i}.txt"
                    
                    # Use echo to create file
                    subprocess.run(
                        ["sh", "-c", f"echo 'Content {i}' > {mountpoint / filename}"],
                        check=True
                    )
                    
                    # Check which branch got the file
                    for branch_idx, branch in enumerate(branches):
                        if (branch / filename).exists():
                            branch_counts[branch_idx] += 1
                            print(f"File {filename} created in branch {branch_idx}")
                            break
                
                print(f"Final distribution: {dict(branch_counts)}")
                
                # Verify random distribution
                assert sum(branch_counts.values()) == 20, "All files should be created"
                assert len(branch_counts) > 1, "Random should use multiple branches"
                
            finally:
                # Cleanup
                process.terminate()
                process.wait()
                
                # Unmount
                subprocess.run(["fusermount", "-u", str(mountpoint)], capture_output=True)