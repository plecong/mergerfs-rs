#!/usr/bin/env python3
"""Test hard link functionality."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.mark.integration
class TestHardLinks:
    """Test hard link creation and behavior."""
    
    def test_hard_link_basic(self, mounted_fs):
        """Test basic hard link creation."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create original file
        original = mountpoint / "original.txt"
        original.write_text("Original content")
        time.sleep(0.1)
        
        # Create hard link
        link = mountpoint / "hardlink.txt"
        os.link(original, link)
        time.sleep(0.1)
        
        # Both should have same content
        assert link.read_text() == "Original content"
        
        # Both should have same inode (within branch)
        # Note: Across mountpoint, inodes might be virtualized
        assert link.exists()
        assert original.exists()
        
        # Verify link count increased
        assert original.stat().st_nlink >= 2
        assert link.stat().st_nlink >= 2
        
        # Modifying one should affect the other
        link.write_text("Modified content")
        time.sleep(0.1)
        assert original.read_text() == "Modified content"
    
    def test_hard_link_same_branch(self, mounted_fs):
        """Test hard links within same branch."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file in specific branch
        test_file = branches[0] / "samebranch.txt"
        test_file.write_text("Same branch content")
        
        time.sleep(0.1)
        
        # Create hard link in same directory
        link = mountpoint / "samebranch_link.txt"
        os.link(mountpoint / "samebranch.txt", link)
        time.sleep(0.1)
        
        # Both should be in same branch
        assert (branches[0] / "samebranch.txt").exists()
        assert (branches[0] / "samebranch_link.txt").exists()
        
        # Verify they're actual hard links (same inode in branch)
        orig_stat = (branches[0] / "samebranch.txt").stat()
        link_stat = (branches[0] / "samebranch_link.txt").stat()
        assert orig_stat.st_ino == link_stat.st_ino
    
    def test_hard_link_cross_branch_error(self, fuse_manager, temp_branches, temp_mountpoint):
        """Test hard link across branches (should fail with EXDEV with path-preserving policy)."""
        from lib.fuse_manager import FuseConfig
        
        # Use a path-preserving policy
        config = FuseConfig(
            policy="epff",  # existing path first found - path preserving
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as mounted:
            if len(mounted) == 4:
                process, mountpoint, branches, _ = mounted
            else:
                process, mountpoint, branches = mounted
            
            # Create a file in branch0
            (branches[0] / "file.txt").write_text("Content")
            
            # Create a directory in branch1 only
            (branches[1] / "subdir").mkdir()
            
            time.sleep(0.1)
            
            # Try to create hard link in subdir (which only exists in branch1)
            # With path-preserving policy, this should fail with EXDEV
            with pytest.raises(OSError) as exc_info:
                os.link(
                    mountpoint / "file.txt",
                    mountpoint / "subdir" / "link.txt"
                )
            
            # Should get EXDEV error because target dir doesn't exist on same branch
            assert exc_info.value.errno == 18  # EXDEV
    
    def test_hard_link_to_directory_error(self, mounted_fs):
        """Test hard link to directory (should fail)."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create directory
        test_dir = mountpoint / "testdir"
        test_dir.mkdir()
        time.sleep(0.1)
        
        # Try to create hard link to directory
        with pytest.raises(OSError) as exc_info:
            os.link(test_dir, mountpoint / "dirlink")
        
        # Should fail with EPERM or EISDIR
        assert exc_info.value.errno in [1, 21]  # EPERM or EISDIR
    
    @pytest.mark.parametrize('mounted_fs_with_policy', ['mfs'], indirect=True)
    def test_hard_link_with_policies(self, mounted_fs_with_policy):
        """Test hard link behavior with different create policies."""
        if len(mounted_fs_with_policy) == 4:
            process, mountpoint, branches, _ = mounted_fs_with_policy
        else:
            process, mountpoint, branches = mounted_fs_with_policy
        
        # Add different amounts of data to branches
        (branches[0] / "data0.bin").write_bytes(b'0' * (30 * 1024 * 1024))
        (branches[1] / "data1.bin").write_bytes(b'1' * (10 * 1024 * 1024))
        (branches[2] / "data2.bin").write_bytes(b'2' * (20 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create file - should go to branch 2 (most free space: 500MB - 20MB = 480MB)
        original = mountpoint / "policy_test.txt"
        original.write_text("Policy test content")
        time.sleep(0.1)
        
        assert (branches[2] / "policy_test.txt").exists()
        
        # Create hard link - must be in same branch
        link = mountpoint / "policy_link.txt"
        os.link(original, link)
        time.sleep(0.1)
        
        # Link should be in same branch as original
        assert (branches[2] / "policy_link.txt").exists()
        assert not (branches[0] / "policy_link.txt").exists()
        assert not (branches[1] / "policy_link.txt").exists()
    
    def test_hard_link_unlink_behavior(self, mounted_fs):
        """Test unlinking hard links."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file with multiple hard links
        original = mountpoint / "unlink_test.txt"
        original.write_text("Unlink test content")
        
        link1 = mountpoint / "link1.txt"
        link2 = mountpoint / "link2.txt"
        
        os.link(original, link1)
        os.link(original, link2)
        time.sleep(0.1)
        
        # All should exist with link count 3
        assert original.stat().st_nlink == 3
        assert link1.stat().st_nlink == 3
        assert link2.stat().st_nlink == 3
        
        # Remove original
        original.unlink()
        time.sleep(0.1)
        
        # Links should still exist with count 2
        assert not original.exists()
        assert link1.exists()
        assert link2.exists()
        assert link1.stat().st_nlink == 2
        assert link2.stat().st_nlink == 2
        
        # Content still accessible
        assert link1.read_text() == "Unlink test content"
        
        # Remove link1
        link1.unlink()
        time.sleep(0.1)
        
        # link2 should still exist with count 1
        assert link2.exists()
        assert link2.stat().st_nlink == 1
        assert link2.read_text() == "Unlink test content"
    
    def test_hard_link_rename(self, mounted_fs):
        """Test renaming hard links."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file and hard link
        original = mountpoint / "rename_orig.txt"
        original.write_text("Rename test")
        
        link = mountpoint / "rename_link.txt"
        os.link(original, link)
        time.sleep(0.1)
        
        # Rename the link
        new_link = mountpoint / "renamed_link.txt"
        link.rename(new_link)
        time.sleep(0.1)
        
        # Both should still exist and be linked
        assert original.exists()
        assert new_link.exists()
        assert not link.exists()
        
        assert original.stat().st_nlink == 2
        assert new_link.stat().st_nlink == 2
        
        # Content preserved
        assert new_link.read_text() == "Rename test"
    
    def test_hard_link_permissions(self, mounted_fs):
        """Test permissions with hard links."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file with specific permissions
        original = mountpoint / "perm_test.txt"
        original.write_text("Permission test")
        os.chmod(original, 0o644)
        
        # Create hard link
        link = mountpoint / "perm_link.txt"
        os.link(original, link)
        time.sleep(0.1)
        
        # Both should have same permissions
        assert oct(original.stat().st_mode)[-3:] == "644"
        assert oct(link.stat().st_mode)[-3:] == "644"
        
        # Change permissions via link
        os.chmod(link, 0o600)
        time.sleep(0.1)
        
        # Both should update
        assert oct(original.stat().st_mode)[-3:] == "600"
        assert oct(link.stat().st_mode)[-3:] == "600"
    
    def test_hard_link_edge_cases(self, mounted_fs):
        """Test edge cases for hard links."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Test 1: Link to non-existent file
        with pytest.raises(OSError) as exc_info:
            os.link(mountpoint / "nonexistent.txt", mountpoint / "badlink.txt")
        assert exc_info.value.errno == 2  # ENOENT
        
        # Test 2: Link with same source and destination
        existing = mountpoint / "existing.txt"
        existing.write_text("Existing")
        time.sleep(0.1)
        
        with pytest.raises(OSError) as exc_info:
            os.link(existing, existing)
        assert exc_info.value.errno in [17, 22]  # EEXIST or EINVAL
        
        # Test 3: Link to existing destination
        other = mountpoint / "other.txt"
        other.write_text("Other")
        time.sleep(0.1)
        
        with pytest.raises(OSError) as exc_info:
            os.link(existing, other)
        assert exc_info.value.errno == 17  # EEXIST
        
        # Test 4: Maximum link count (system dependent)
        # Most systems support at least 1000 links
        base = mountpoint / "maxlinks.txt"
        base.write_text("Max links test")
        
        # Try creating many links (stop at reasonable number)
        max_links = 100  # Conservative limit for testing
        created_links = []
        
        try:
            for i in range(max_links):
                link_path = mountpoint / f"mlink_{i}.txt"
                os.link(base, link_path)
                created_links.append(link_path)
                
            # Verify link count
            assert base.stat().st_nlink == max_links + 1
            
        finally:
            # Clean up
            for link_path in created_links:
                if link_path.exists():
                    link_path.unlink()
    
    def test_hard_link_with_branch_modes(self, mounted_fs):
        """Test hard links with read-only branches."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create file in branch 0
        original = mountpoint / "ro_test.txt"
        original.write_text("RO test")
        time.sleep(0.1)
        
        # Make branch 0 read-only
        os.chmod(branches[0], 0o555)
        
        try:
            # Try to create hard link - should fail
            with pytest.raises(OSError):
                os.link(original, mountpoint / "ro_link.txt")
            
            # Reading should still work
            assert original.read_text() == "RO test"
            
        finally:
            os.chmod(branches[0], 0o755)