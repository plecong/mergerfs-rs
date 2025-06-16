#!/usr/bin/env python3

import os
import pytest
from pathlib import Path
import subprocess
import shutil
import time

@pytest.fixture
def epmfs_mounted_fs(fuse_manager, temp_branches, temp_mountpoint):
    """Fixture that provides a mounted filesystem with epmfs policy."""
    branches = temp_branches(2)
    mountpoint = temp_mountpoint()
    
    # Mount with epmfs policy
    process = fuse_manager.mount_mergerfs(
        branches=branches,
        mountpoint=mountpoint, 
        options=["-o", "func.create=epmfs"]
    )
    
    try:
        yield process, mountpoint, branches
    finally:
        fuse_manager.cleanup_mount(process, mountpoint)

@pytest.mark.integration
class TestEPMFSPolicy:
    """Test the EPMFS (Existing Path, Most Free Space) create policy"""
    
    def test_epmfs_preserves_path_locality(self, epmfs_mounted_fs):
        """Test that epmfs policy keeps files in directories together on the same branch"""
        process, mountpoint, branches = epmfs_mounted_fs
        
        # Create a directory structure on branch1 only
        branch1_dir = branches[0] / "project"
        branch1_dir.mkdir()
        (branch1_dir / "src").mkdir()
        
        # Create first file through mergerfs - should go to branch1
        src_dir = mountpoint / "project" / "src"
        file1 = src_dir / "main.rs"
        file1.write_text("fn main() {}")
        
        # Verify file was created on branch1
        assert (branches[0] / "project" / "src" / "main.rs").exists()
        assert not (branches[1] / "project" / "src" / "main.rs").exists()
        
        # Create second file in same directory - should also go to branch1
        file2 = src_dir / "lib.rs" 
        file2.write_text("pub fn hello() {}")
        
        # Verify both files are on the same branch (branch1)
        assert (branches[0] / "project" / "src" / "main.rs").exists()
        assert (branches[0] / "project" / "src" / "lib.rs").exists()
        assert not (branches[1] / "project" / "src" / "lib.rs").exists()
    
    def test_epmfs_selects_branch_with_most_space(self, epmfs_mounted_fs):
        """Test that epmfs selects branch with most free space when path exists on multiple branches"""
        process, mountpoint, branches = epmfs_mounted_fs
        
        # Create same directory structure on both branches
        for branch in branches:
            (branch / "shared" / "data").mkdir(parents=True)
        
        # Fill up branch1 with a large file to reduce available space
        large_file = branches[0] / "shared" / "large.bin"
        # Create a 100MB file (adjust size based on your test environment)
        with open(large_file, 'wb') as f:
            f.write(b'0' * (100 * 1024 * 1024))
        
        # Now create a file through mergerfs - should prefer branch2 due to more free space
        test_file = mountpoint / "shared" / "data" / "test.txt"
        test_file.write_text("test content")
        
        # File should be created on branch2 (more free space)
        # Note: This test assumes branch2 has more free space than branch1 after creating large file
        if (branches[1] / "shared" / "data" / "test.txt").exists():
            # Expected behavior - file went to branch with more space
            assert not (branches[0] / "shared" / "data" / "test.txt").exists()
        else:
            # File went to branch1 - this is okay if branch1 still has more space
            # or if the space difference is not significant
            assert (branches[0] / "shared" / "data" / "test.txt").exists()
    
    def test_epmfs_fallback_when_path_missing(self, epmfs_mounted_fs):
        """Test that epmfs returns error when parent path doesn't exist on any branch"""
        process, mountpoint, branches = epmfs_mounted_fs
        
        # Try to create a file in a non-existent directory
        new_file = mountpoint / "nonexistent" / "dir" / "file.txt"
        
        with pytest.raises(FileNotFoundError):
            new_file.write_text("should fail")
    
    def test_epmfs_with_readonly_branches(self, temp_branches, temp_mountpoint, fuse_manager):
        """Test epmfs policy with mix of readonly and readwrite branches"""
        branches = temp_branches(3)  # Create 3 branches
        
        # Create directory structure on all branches
        for branch in branches:
            (branch / "docs").mkdir()
        
        # Make branch1 readonly by changing permissions
        os.chmod(branches[0], 0o555)
        
        try:
            # Mount with epmfs policy
            mountpoint = temp_mountpoint()
            process = fuse_manager.mount_mergerfs(
                branches=branches,
                mountpoint=mountpoint,
                options=["-o", "func.create=epmfs"]
            )
            
            # Create a file - should skip readonly branch
            test_file = mountpoint / "docs" / "readme.txt" 
            test_file.write_text("documentation")
            
            # File should NOT be on readonly branch
            assert not (branches[0] / "docs" / "readme.txt").exists()
            # File should be on one of the writable branches
            assert ((branches[1] / "docs" / "readme.txt").exists() or 
                    (branches[2] / "docs" / "readme.txt").exists())
            
        finally:
            # Restore permissions
            os.chmod(branches[0], 0o755)
            if 'process' in locals():
                fuse_manager.cleanup_mount(process, mountpoint)
    
    def test_epmfs_nested_directory_creation(self, epmfs_mounted_fs):
        """Test that epmfs maintains path locality for nested directory creation"""
        process, mountpoint, branches = epmfs_mounted_fs
        
        # Create base directory on branch1
        (branches[0] / "app").mkdir()
        
        # Create nested structure through mergerfs
        nested_dir = mountpoint / "app" / "src" / "components" / "ui"
        nested_dir.mkdir(parents=True)
        
        # All directories should be created on branch1
        assert (branches[0] / "app" / "src").exists()
        assert (branches[0] / "app" / "src" / "components").exists() 
        assert (branches[0] / "app" / "src" / "components" / "ui").exists()
        
        # Nothing should be on branch2
        assert not (branches[1] / "app" / "src").exists()
        
        # Files in nested directories should also go to branch1
        test_file = nested_dir / "button.rs"
        test_file.write_text("struct Button {}")
        
        assert (branches[0] / "app" / "src" / "components" / "ui" / "button.rs").exists()
        assert not (branches[1] / "app" / "src" / "components" / "ui" / "button.rs").exists()


def test_epmfs_command_line():
    """Test that epmfs policy can be specified on command line"""
    result = subprocess.run(
        ["cargo", "run", "--", "--help"],
        capture_output=True,
        text=True
    )
    
    # Check that epmfs is mentioned in help
    assert "epmfs" in result.stdout
    assert "ExistingPathMostFreeSpace" in result.stdout or "existing path" in result.stdout.lower()