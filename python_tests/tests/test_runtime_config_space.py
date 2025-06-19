"""Test runtime configuration with tmpfs branches for proper space-based testing."""

import pytest
import xattr
import time
from pathlib import Path
from typing import List

from lib.fuse_manager import FuseManager, FuseConfig


@pytest.mark.integration
class TestRuntimeConfigWithTmpfs:
    """Test runtime configuration changes with tmpfs branches."""
    
    def test_runtime_policy_changes_with_tmpfs(
        self,
        fuse_manager: FuseManager,
        tmpfs_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test that runtime policy changes affect file placement with different branch sizes."""
        # tmpfs_branches are pre-configured with:
        # branch 0: 8MB free (least)
        # branch 1: 40MB free (medium)  
        # branch 2: 90MB free (most)
        
        config = FuseConfig(policy="ff", branches=tmpfs_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as result:
            if len(result) == 4:
                process, mountpoint, branches, _ = result
            else:
                process, mountpoint, branches = result
                
            control_file = mountpoint / ".mergerfs"
            
            # Test 1: FF policy - should use first branch
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            assert policy == "ff"
            
            test_file = mountpoint / "ff_test.txt"
            test_file.write_text("FF policy test")
            time.sleep(0.2)
            assert (branches[0] / "ff_test.txt").exists(), "FF policy should create in first branch"
            
            # Test 2: Change to MFS - should use branch with most free space (branch 2)
            xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"mfs")
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            assert policy == "mfs"
            
            test_file = mountpoint / "mfs_test.txt"
            test_file.write_text("MFS policy test")
            time.sleep(0.2)
            assert (branches[2] / "mfs_test.txt").exists(), "MFS policy should create in branch with most free space"
            
            # Test 3: Change to LFS - should use branch with least free space (branch 0)
            xattr.setxattr(str(control_file), "user.mergerfs.func.create", b"lfs")
            policy = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
            assert policy == "lfs"
            
            test_file = mountpoint / "lfs_test.txt"
            test_file.write_text("LFS policy test")
            time.sleep(0.2)
            assert (branches[0] / "lfs_test.txt").exists(), "LFS policy should create in branch with least free space"
            
            # Test 4: Verify more policies work
            for policy in ["lus", "epmfs", "eplfs"]:
                xattr.setxattr(str(control_file), "user.mergerfs.func.create", policy.encode())
                current = xattr.getxattr(str(control_file), "user.mergerfs.func.create").decode()
                assert current == policy
                
                # Create a test file
                test_file = mountpoint / f"{policy}_test.txt"
                test_file.write_text(f"{policy} policy test")
                time.sleep(0.1)
                
                # Verify it was created somewhere
                created = False
                for branch in branches:
                    if (branch / f"{policy}_test.txt").exists():
                        created = True
                        break
                assert created, f"File not created with {policy} policy"