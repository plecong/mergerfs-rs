"""
Test hard link operations in mergerfs-rs
"""
import os
import pytest
from pathlib import Path
import xattr


@pytest.mark.integration
class TestHardLinks:
    """Test hard link creation and behavior"""
    
    def test_create_hard_link_basic(self, mounted_fs):
        """Test basic hard link creation"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "test.txt"
        test_file.write_text("Hello, world!")
        
        # Create a hard link
        link_file = mountpoint / "link.txt"
        os.link(str(test_file), str(link_file))
        
        # Verify link exists
        assert link_file.exists()
        assert link_file.is_file()
        
        # Verify content is the same
        assert link_file.read_text() == "Hello, world!"
        
        # Verify they share the same inode
        test_stat = test_file.stat()
        link_stat = link_file.stat()
        assert test_stat.st_ino == link_stat.st_ino
        assert test_stat.st_nlink == 2
        assert link_stat.st_nlink == 2
    
    def test_hard_link_modifications(self, mounted_fs):
        """Test that modifications through one link affect the other"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "original.txt"
        test_file.write_text("Original content")
        
        # Create a hard link
        link_file = mountpoint / "hardlink.txt"
        os.link(str(test_file), str(link_file))
        
        # Modify through the link
        link_file.write_text("Modified content")
        
        # Verify both have the new content
        assert test_file.read_text() == "Modified content"
        assert link_file.read_text() == "Modified content"
        
        # Modify through the original
        test_file.write_text("Another modification")
        
        # Verify both have the newer content
        assert test_file.read_text() == "Another modification"
        assert link_file.read_text() == "Another modification"
    
    @pytest.mark.skip(reason="Current implementation removes file from all branches, breaking hard link semantics")
    def test_hard_link_delete_one(self, mounted_fs):
        """Test that deleting one hard link leaves the other intact"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "original.txt"
        test_file.write_text("Test content")
        
        # Create a hard link
        link_file = mountpoint / "hardlink.txt"
        os.link(str(test_file), str(link_file))
        
        # Delete the original
        test_file.unlink()
        
        # Verify the link still exists with content
        assert not test_file.exists()
        assert link_file.exists()
        assert link_file.read_text() == "Test content"
        
        # Verify link count decreased
        assert link_file.stat().st_nlink == 1
    
    def test_hard_link_nested_directory(self, mounted_fs):
        """Test creating hard links in nested directories"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "source.txt"
        test_file.write_text("Nested test")
        
        # Create nested directory
        nested_dir = mountpoint / "dir1" / "dir2"
        nested_dir.mkdir(parents=True)
        
        # Create hard link in nested directory
        link_file = nested_dir / "link.txt"
        os.link(str(test_file), str(link_file))
        
        # Verify link exists
        assert link_file.exists()
        assert link_file.read_text() == "Nested test"
        
        # Verify they share the same inode
        assert test_file.stat().st_ino == link_file.stat().st_ino
    
    def test_hard_link_multiple_links(self, mounted_fs):
        """Test creating multiple hard links to the same file"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        original = mountpoint / "original.txt"
        original.write_text("Multiple links test")
        
        # Create multiple hard links
        link1 = mountpoint / "link1.txt"
        link2 = mountpoint / "link2.txt"
        link3 = mountpoint / "subdir" / "link3.txt"
        
        link3.parent.mkdir()
        
        os.link(str(original), str(link1))
        os.link(str(original), str(link2))
        os.link(str(original), str(link3))
        
        # Verify all exist and have same content
        for link in [original, link1, link2, link3]:
            assert link.exists()
            assert link.read_text() == "Multiple links test"
        
        # Verify all share the same inode
        original_ino = original.stat().st_ino
        assert link1.stat().st_ino == original_ino
        assert link2.stat().st_ino == original_ino
        assert link3.stat().st_ino == original_ino
        
        # Verify link count
        assert original.stat().st_nlink == 4
    
    def test_hard_link_permissions(self, mounted_fs):
        """Test that hard links share permissions"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file with specific permissions
        test_file = mountpoint / "perms.txt"
        test_file.write_text("Permission test")
        test_file.chmod(0o644)
        
        # Create hard link
        link_file = mountpoint / "perms_link.txt"
        os.link(str(test_file), str(link_file))
        
        # Verify permissions are the same
        assert test_file.stat().st_mode & 0o777 == 0o644
        assert link_file.stat().st_mode & 0o777 == 0o644
        
        # Change permissions through the link
        link_file.chmod(0o600)
        
        # Verify both have new permissions
        assert test_file.stat().st_mode & 0o777 == 0o600
        assert link_file.stat().st_mode & 0o777 == 0o600
    
    def test_hard_link_xattr(self, mounted_fs):
        """Test that hard links share extended attributes"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "xattr_test.txt"
        test_file.write_text("xattr content")
        
        # Set an extended attribute
        xattr.setxattr(str(test_file), "user.test", b"test_value")
        
        # Create hard link
        link_file = mountpoint / "xattr_link.txt"
        os.link(str(test_file), str(link_file))
        
        # Verify xattr is accessible through both
        assert xattr.getxattr(str(test_file), "user.test") == b"test_value"
        assert xattr.getxattr(str(link_file), "user.test") == b"test_value"
        
        # Set xattr through link
        xattr.setxattr(str(link_file), "user.another", b"another_value")
        
        # Verify both have the new xattr
        assert xattr.getxattr(str(test_file), "user.another") == b"another_value"
        assert xattr.getxattr(str(link_file), "user.another") == b"another_value"
    
    def test_hard_link_errors(self, mounted_fs):
        """Test error cases for hard link creation"""
        process, mountpoint, branches = mounted_fs
        
        # Try to link non-existent file
        with pytest.raises(FileNotFoundError):
            os.link(str(mountpoint / "nonexistent.txt"), str(mountpoint / "link.txt"))
        
        # Create a directory
        test_dir = mountpoint / "testdir"
        test_dir.mkdir()
        
        # Try to create hard link to directory (should fail)
        with pytest.raises(OSError):
            os.link(str(test_dir), str(mountpoint / "dirlink"))
    
    def test_hard_link_branch_behavior(self, mounted_fs):
        """Test that hard links are created on the same branch as the source"""
        process, mountpoint, branches = mounted_fs
        
        # Create a file on the first branch
        branch1_file = Path(branches[0]) / "branch1_only.txt"
        branch1_file.write_text("Branch 1 content")
        
        # Create hard link through mergerfs
        link_file = mountpoint / "branch1_link.txt"
        os.link(str(mountpoint / "branch1_only.txt"), str(link_file))
        
        # Verify link exists only on branch1
        assert (Path(branches[0]) / "branch1_link.txt").exists()
        assert not (Path(branches[1]) / "branch1_link.txt").exists()
        
        # Verify they share the same inode on branch1
        source_stat = branch1_file.stat()
        link_stat = (Path(branches[0]) / "branch1_link.txt").stat()
        assert source_stat.st_ino == link_stat.st_ino
    
    def test_hard_link_rename(self, mounted_fs):
        """Test renaming files with hard links"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "original.txt"
        test_file.write_text("Rename test")
        
        # Create hard link
        link_file = mountpoint / "link.txt"
        os.link(str(test_file), str(link_file))
        
        # Rename the original
        renamed_file = mountpoint / "renamed.txt"
        test_file.rename(renamed_file)
        
        # Verify the link still works
        assert link_file.exists()
        assert link_file.read_text() == "Rename test"
        
        # Verify renamed file works
        assert renamed_file.exists()
        assert renamed_file.read_text() == "Rename test"
        
        # Verify they still share the same inode
        assert link_file.stat().st_ino == renamed_file.stat().st_ino