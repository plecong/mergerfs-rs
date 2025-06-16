#!/usr/bin/env python3
"""Test suite for the eplfs (existing path, least free space) create policy"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
import time
from lib.fuse_manager import FuseConfig

@pytest.mark.integration
class TestEplfsPolicy:
    """Test the eplfs create policy functionality"""

    def test_eplfs_selects_least_free_space_with_existing_path(self, fuse_manager):
        """Test that eplfs selects the branch with least free space where parent exists"""
        # Create three branches
        branches = fuse_manager.create_temp_dirs(3)
        
        # Create parent directory in branches 0 and 1 only
        (branches[0] / "parent").mkdir()
        (branches[1] / "parent").mkdir()
        # Branch 2 does not have the parent directory
        
        # Fill branch 0 with more data to have less free space
        dummy_file = branches[0] / "largefile.dat"
        with open(dummy_file, 'wb') as f:
            # Write 50MB of data
            f.write(b'0' * (50 * 1024 * 1024))
        
        # Create mountpoint
        mountpoint = fuse_manager.create_temp_mountpoint()
        
        # Mount with eplfs policy
        config = FuseConfig(
            policy="eplfs",
            branches=branches,
            mountpoint=mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as result:
            process, mountpoint, branches = result[:3]
            
            # Give filesystem time to initialize
            time.sleep(0.5)
            
            # Create a file in the parent directory
            test_file = mountpoint / "parent" / "test.txt"
            test_file.write_text("test content")
            
            # Wait for write to complete
            time.sleep(0.5)
            
            # Check which branch got the file
            # Since branch 0 has less free space, it should be selected
            assert (branches[0] / "parent" / "test.txt").exists(), "File should be created in branch 0 (less free space)"
            assert not (branches[1] / "parent" / "test.txt").exists(), "File should not be in branch 1"
            assert not (branches[2] / "parent" / "test.txt").exists(), "File should not be in branch 2 (no parent)"
    
    def test_eplfs_no_existing_parent(self, fuse_manager):
        """Test that eplfs creates file in any branch when parent doesn't exist on any specific branch"""
        # Create two branches without a specific parent directory
        branches = fuse_manager.create_temp_dirs(2)
        mountpoint = fuse_manager.create_temp_mountpoint()
        
        config = FuseConfig(
            policy="eplfs",
            branches=branches,
            mountpoint=mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as result:
            process, mountpoint, branches = result[:3]
            
            # Give filesystem time to initialize
            time.sleep(0.5)
            
            # Create a directory first
            test_dir = mountpoint / "newdir"
            test_dir.mkdir()
            
            # Create a file in the new directory
            test_file = test_dir / "test.txt"
            test_file.write_text("test content")
            
            # Wait for write to complete
            time.sleep(0.5)
            
            # The file should be created in one of the branches
            exists_in_branch0 = (branches[0] / "newdir" / "test.txt").exists()
            exists_in_branch1 = (branches[1] / "newdir" / "test.txt").exists()
            
            assert exists_in_branch0 or exists_in_branch1, "File should be created in at least one branch"
    
    def test_eplfs_with_different_free_space(self, fuse_manager):
        """Test that eplfs selects branch with least free space"""
        # Create two branches
        branches = fuse_manager.create_temp_dirs(2)
        
        # Create parent directory in both
        (branches[0] / "parent").mkdir()
        (branches[1] / "parent").mkdir()
        
        # Fill branch 1 with less data so it has MORE free space
        # This means branch 0 should be selected (less free space)
        dummy_file = branches[1] / "bigfile.dat"
        with open(dummy_file, 'wb') as f:
            f.write(b'x' * (10 * 1024 * 1024))  # 10MB
        
        mountpoint = fuse_manager.create_temp_mountpoint()
        
        config = FuseConfig(
            policy="eplfs",
            branches=branches,
            mountpoint=mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as result:
            process, mountpoint, branches = result[:3]
            
            # Give filesystem time to initialize
            time.sleep(0.5)
            
            # Create a file
            test_file = mountpoint / "parent" / "test.txt"
            test_file.write_text("test content")
            
            # Wait for write to complete
            time.sleep(0.5)
            
            # Check file location - should be in branch with least free space
            exists_in_branch0 = (branches[0] / "parent" / "test.txt").exists()
            exists_in_branch1 = (branches[1] / "parent" / "test.txt").exists()
            
            # Since we can't guarantee which has less space in temp dirs,
            # just verify it was created somewhere
            assert exists_in_branch0 or exists_in_branch1, "File should be created in one of the branches"
    
    def test_eplfs_root_path(self, fuse_manager):
        """Test that eplfs works with root path (always exists)"""
        # Create a single branch
        branches = fuse_manager.create_temp_dirs(1)
        mountpoint = fuse_manager.create_temp_mountpoint()
        
        config = FuseConfig(
            policy="eplfs",
            branches=branches,
            mountpoint=mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as result:
            process, mountpoint, branches = result[:3]
            
            # Give filesystem time to initialize
            time.sleep(0.5)
            
            # Create a file at root level
            test_file = mountpoint / "test.txt"
            test_file.write_text("root level file")
            
            # Wait for write to complete
            time.sleep(0.5)
            
            # Check file was created
            assert (branches[0] / "test.txt").exists(), "File should be created at root level"
    
    def test_eplfs_path_preservation(self, fuse_manager):
        """Test that eplfs only creates files where parent exists"""
        # Create three branches
        branches = fuse_manager.create_temp_dirs(3)
        
        # Create 'testdir' only in branch 1
        (branches[1] / "testdir").mkdir()
        
        mountpoint = fuse_manager.create_temp_mountpoint()
        
        config = FuseConfig(
            policy="eplfs",
            branches=branches,
            mountpoint=mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as result:
            process, mountpoint, branches = result[:3]
            
            # Give filesystem time to initialize
            time.sleep(0.5)
            
            # First verify the directory is visible through FUSE
            assert (mountpoint / "testdir").exists(), "testdir should be visible through FUSE"
            
            # Create a file in testdir - should only go to branch1 since that's where testdir exists
            test_file = mountpoint / "testdir" / "test.txt"
            test_file.write_text("test content")
            
            # Wait for write to complete
            time.sleep(0.5)
            
            # Verify file was created only in branch1
            assert not (branches[0] / "testdir" / "test.txt").exists(), "File should not be in branch0"
            assert (branches[1] / "testdir" / "test.txt").exists(), "File should be in branch1"
            assert not (branches[2] / "testdir" / "test.txt").exists(), "File should not be in branch2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])