#!/usr/bin/env python3
"""
LUS tests with explicit trace monitoring for debugging.
"""

import os
import pytest
import time
from pathlib import Path


@pytest.mark.integration
class TestLUSWithTrace:
    """Test LUS policy with trace monitoring enabled."""
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
    def test_lus_basic_with_trace(self, mounted_fs_with_policy, smart_wait):
        """Test basic LUS functionality with trace."""
        # Extract components
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, trace_monitor = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
            trace_monitor = None
        
        # Pre-fill branches with different data
        print("\nPrefilling branches:")
        
        # Branch 0: 20MB
        for i in range(20):
            (branches[0] / f"init_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Branch 1: 10MB  
        for i in range(10):
            (branches[1] / f"init_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Branch 2: 5MB (least)
        for i in range(5):
            (branches[2] / f"init_{i}.dat").write_bytes(b"x" * (1024 * 1024))
        
        # Show usage
        print("\nBranch usage:")
        for idx, branch in enumerate(branches):
            stat = os.statvfs(str(branch))
            used = ((stat.f_blocks - stat.f_bavail) * stat.f_frsize) / (1024 * 1024)
            total = (stat.f_blocks * stat.f_frsize) / (1024 * 1024)
            print(f"Branch {idx}: {used:.1f}MB used of {total:.0f}MB")
        
        # Create file through FUSE
        test_file = mountpoint / "test_lus.txt"
        test_file.write_text("test content")
        
        # Use smart wait if available
        if smart_wait:
            assert smart_wait.wait_for_file_visible(test_file)
        else:
            time.sleep(0.1)
        
        # Check placement
        found_on = None
        for idx, branch in enumerate(branches):
            if (branch / "test_lus.txt").exists():
                found_on = idx
                break
        
        print(f"\nFile created on branch {found_on}")
        assert found_on == 2, f"Expected file on branch 2 (least used), but found on branch {found_on}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])