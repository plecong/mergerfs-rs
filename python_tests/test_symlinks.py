"""Test symlink operations in mergerfs-rs"""

import os
import pytest
from pathlib import Path

@pytest.mark.integration
class TestSymlinks:
    """Test symlink creation and behavior"""
    
    def test_create_symlink_basic(self, mounted_fs):
        """Test basic symlink creation"""
        process, mountpoint, branches = mounted_fs
        
        # Create a target file in one branch
        target_file = branches[0] / "target.txt"
        target_file.write_text("Hello from target")
        
        # Create symlink through mergerfs
        link_path = mountpoint / "mylink"
        link_path.symlink_to("target.txt")
        
        # Verify symlink exists
        assert link_path.is_symlink()
        assert link_path.exists()
        
        # Verify we can read through the symlink
        assert link_path.read_text() == "Hello from target"
        
        # Verify symlink was created in first writable branch
        branch_link = branches[0] / "mylink"
        assert branch_link.is_symlink()
        assert os.readlink(branch_link) == "target.txt"
    
    def test_create_symlink_absolute_path(self, mounted_fs):
        """Test symlink with absolute path target"""
        process, mountpoint, branches = mounted_fs
        
        # Create symlink with absolute path
        link_path = mountpoint / "abs_link"
        target = "/etc/passwd"
        link_path.symlink_to(target)
        
        # Verify symlink points to absolute path
        assert link_path.is_symlink()
        assert os.readlink(link_path) == target
    
    def test_create_symlink_relative_path(self, mounted_fs):
        """Test symlink with relative path target"""
        process, mountpoint, branches = mounted_fs
        
        # Create directory structure
        (mountpoint / "dir1" / "dir2").mkdir(parents=True)
        
        # Create target file
        target_file = mountpoint / "dir1" / "target.txt"
        target_file.write_text("Target content")
        
        # Create symlink with relative path
        link_path = mountpoint / "dir1" / "dir2" / "link"
        link_path.symlink_to("../target.txt")
        
        # Verify symlink works
        assert link_path.is_symlink()
        assert link_path.read_text() == "Target content"
        assert os.readlink(link_path) == "../target.txt"
    
    def test_create_symlink_broken(self, mounted_fs):
        """Test creating a broken symlink (target doesn't exist)"""
        process, mountpoint, branches = mounted_fs
        
        # Create symlink to non-existent target
        link_path = mountpoint / "broken_link"
        link_path.symlink_to("non_existent_file")
        
        # Verify symlink exists but is broken
        assert link_path.is_symlink()
        assert not link_path.exists()  # exists() returns False for broken symlinks
        assert os.readlink(link_path) == "non_existent_file"
    
    def test_create_symlink_in_subdirectory(self, mounted_fs):
        """Test creating symlink in a subdirectory"""
        process, mountpoint, branches = mounted_fs
        
        # Create subdirectory
        subdir = mountpoint / "subdir"
        subdir.mkdir()
        
        # Create symlink in subdirectory
        link_path = subdir / "link"
        link_path.symlink_to("/etc/hosts")
        
        # Verify symlink was created
        assert link_path.is_symlink()
        assert os.readlink(link_path) == "/etc/hosts"
    
    def test_symlink_with_multiple_branches(self, mounted_fs):
        """Test symlink behavior with multiple branches"""
        process, mountpoint, branches = mounted_fs
        
        # Create same directory in multiple branches
        for branch in branches[:2]:
            (branch / "shared_dir").mkdir()
        
        # Create symlink through mergerfs
        link_path = mountpoint / "shared_dir" / "link"
        link_path.symlink_to("../target")
        
        # Verify symlink was created in the first writable branch
        assert (branches[0] / "shared_dir" / "link").is_symlink()
        assert not (branches[1] / "shared_dir" / "link").exists()
    
    def test_readlink_operation(self, mounted_fs):
        """Test reading symlink targets"""
        process, mountpoint, branches = mounted_fs
        
        # Create various symlinks
        links = {
            "abs_link": "/absolute/path",
            "rel_link": "relative/path",
            "dots_link": "../../../file",
        }
        
        for name, target in links.items():
            link_path = mountpoint / name
            link_path.symlink_to(target)
            
            # Verify readlink returns correct target
            assert os.readlink(link_path) == target
    
    def test_symlink_permissions(self, mounted_fs):
        """Test that symlinks have correct permissions"""
        process, mountpoint, branches = mounted_fs
        
        # Create a symlink
        link_path = mountpoint / "test_link"
        link_path.symlink_to("/etc/passwd")
        
        # Get symlink stats (not following the link)
        stat = link_path.lstat()
        
        # Symlinks typically have 0o777 permissions
        assert stat.st_mode & 0o777 == 0o777
    
    def test_symlink_to_directory(self, mounted_fs):
        """Test creating symlink to a directory"""
        process, mountpoint, branches = mounted_fs
        
        # Create a directory
        target_dir = mountpoint / "target_dir"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("In directory")
        
        # Create symlink to directory
        link_path = mountpoint / "dir_link"
        link_path.symlink_to("target_dir")
        
        # Verify we can access files through the symlink
        assert link_path.is_symlink()
        assert (link_path / "file.txt").read_text() == "In directory"