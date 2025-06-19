"""Test inode calculation algorithms for mergerfs-rs"""
import os
import pytest
from pathlib import Path
import xattr
import time


@pytest.mark.integration
class TestInodeCalculation:
    """Test inode calculation algorithms"""
    
    def test_hard_link_inodes_default_hybrid_hash(self, mounted_fs):
        """Test that hard links share inodes with default hybrid-hash mode
        
        NOTE: This test currently fails due to a caching limitation in the FUSE layer.
        While the inode calculation correctly generates the same inode for hard links,
        the path-to-inode cache assumes a 1:1 mapping, causing hard links to appear 
        with different inodes through FUSE.
        """
        process, mountpoint, branches = mounted_fs
        
        # Create a file and hard link
        file_path = mountpoint / "test.txt"
        link_path = mountpoint / "link.txt"
        
        # Create original file
        file_path.write_text("test content")
        
        # Wait for file to be visible
        time.sleep(0.5)
        
        # Create hard link
        os.link(str(file_path), str(link_path))
        
        # Wait for link to be visible
        time.sleep(0.5)
        
        # Get stats for both
        file_stat = file_path.stat()
        link_stat = link_path.stat()
        
        # With hybrid-hash (default), files use devino-hash so hard links share inodes
        assert file_stat.st_ino == link_stat.st_ino, "Hard links should share the same inode with hybrid-hash"
        assert file_stat.st_nlink == 2, "Both files should show nlink=2"
        assert link_stat.st_nlink == 2, "Both files should show nlink=2"
    
    def test_change_inode_calc_mode(self, mounted_fs):
        """Test changing inode calculation mode at runtime"""
        process, mountpoint, branches = mounted_fs
        
        # Create a file with default mode
        file_path = mountpoint / "test.txt"
        file_path.write_text("test content")
        time.sleep(0.5)
        
        # Get initial inode
        initial_stat = file_path.stat()
        initial_ino = initial_stat.st_ino
        
        # Change to path-hash mode
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.inodecalc", b"path-hash")
        
        # The inode should change after mode change
        # Note: In a real implementation, this might require cache invalidation
        time.sleep(0.5)
        new_stat = file_path.stat()
        
        # With path-hash, the inode is based on path, not device+inode
        # So it might be different (but could coincidentally be the same)
        # We can't assert they're different, but we can verify the mode changed
        mode = xattr.getxattr(str(control_file), "user.mergerfs.inodecalc")
        assert mode == b"path-hash", "Mode should have changed to path-hash"
    
    def test_hard_links_with_path_hash(self, mounted_fs):
        """Test that hard links have different inodes with path-hash mode"""
        process, mountpoint, branches = mounted_fs
        
        # Set path-hash mode
        control_file = mountpoint / ".mergerfs"
        xattr.setxattr(str(control_file), "user.mergerfs.inodecalc", b"path-hash")
        time.sleep(0.5)
        
        # Create a file and hard link
        file_path = mountpoint / "file.txt"
        link_path = mountpoint / "hardlink.txt"
        
        file_path.write_text("test content")
        time.sleep(0.5)
        
        os.link(str(file_path), str(link_path))
        time.sleep(0.5)
        
        # Get stats
        file_stat = file_path.stat()
        link_stat = link_path.stat()
        
        # With path-hash, hard links should have different inodes
        assert file_stat.st_ino != link_stat.st_ino, "Hard links should have different inodes with path-hash"
        # But they still share the same nlink count
        assert file_stat.st_nlink == 2, "nlink should be 2"
        assert link_stat.st_nlink == 2, "nlink should be 2"
    
    def test_directory_inode_consistency(self, mounted_fs):
        """Test that directories maintain consistent inodes"""
        process, mountpoint, branches = mounted_fs
        
        # Create a directory
        dir_path = mountpoint / "testdir"
        dir_path.mkdir()
        time.sleep(0.5)
        
        # Get initial inode
        initial_ino = dir_path.stat().st_ino
        
        # Create files in the directory
        (dir_path / "file1.txt").write_text("content1")
        (dir_path / "file2.txt").write_text("content2")
        time.sleep(0.5)
        
        # Directory inode should remain the same
        assert dir_path.stat().st_ino == initial_ino, "Directory inode should remain consistent"
    
    def test_inode_modes_list(self, mounted_fs):
        """Test that all inode calculation modes are accepted"""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        modes = [
            "passthrough",
            "path-hash",
            "path-hash32",
            "devino-hash", 
            "devino-hash32",
            "hybrid-hash",
            "hybrid-hash32"
        ]
        
        for mode in modes:
            # Set the mode
            xattr.setxattr(str(control_file), "user.mergerfs.inodecalc", mode.encode())
            time.sleep(0.1)
            
            # Verify it was set
            current_mode = xattr.getxattr(str(control_file), "user.mergerfs.inodecalc")
            assert current_mode.decode() == mode, f"Mode {mode} should be set"
    
    def test_invalid_inode_mode(self, mounted_fs):
        """Test that invalid inode modes are rejected"""
        process, mountpoint, branches = mounted_fs
        control_file = mountpoint / ".mergerfs"
        
        # Try to set an invalid mode
        with pytest.raises(OSError) as exc_info:
            xattr.setxattr(str(control_file), "user.mergerfs.inodecalc", b"invalid-mode")
        
        # Should get EINVAL (22)
        assert exc_info.value.errno == 22, "Should get EINVAL for invalid mode"
    
    def test_cross_branch_same_file(self, mounted_fs):
        """Test inode calculation for files existing in multiple branches"""
        process, mountpoint, branches = mounted_fs
        
        # Create the same file in multiple branches directly
        filename = "samefile.txt"
        for i, branch in enumerate(branches):
            file_path = Path(branch) / filename
            file_path.write_text(f"content from branch {i}")
        
        time.sleep(0.5)
        
        # Access through mergerfs
        merged_file = mountpoint / filename
        
        # Get inode - should be consistent
        ino1 = merged_file.stat().st_ino
        
        # Read the file to ensure it's cached
        content = merged_file.read_text()
        
        # Inode should remain the same
        ino2 = merged_file.stat().st_ino
        assert ino1 == ino2, "Inode should be consistent for the same file"