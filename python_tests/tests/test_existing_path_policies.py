#!/usr/bin/env python3
"""Test existing path create policies (epff, epmfs, eplfs)."""

import os
import time
import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.mark.integration
@pytest.mark.skip(reason="Existing path policies not yet configurable - waiting for runtime config support")
class TestExistingPathPolicies:
    """Test existing path create policies that preserve directory structure."""
    
    def test_epff_basic(self, mounted_fs_with_policy):
        """Test epff (existing path first found) policy."""
        process, mountpoint, branches = mounted_fs_with_policy("epff")
        
        # Create directory structure in different branches
        # Branch 0: has /data/docs
        (branches[0] / "data" / "docs").mkdir(parents=True)
        # Branch 1: has /data/images  
        (branches[1] / "data" / "images").mkdir(parents=True)
        # Branch 2: has /data
        (branches[2] / "data").mkdir(parents=True)
        
        time.sleep(0.1)
        
        # Create file in /data/docs - should go to branch 0 (first with parent)
        docs_file = mountpoint / "data" / "docs" / "test.txt"
        docs_file.write_text("EPFF test")
        
        time.sleep(0.1)
        
        assert (branches[0] / "data" / "docs" / "test.txt").exists()
        assert not (branches[1] / "data" / "docs" / "test.txt").exists()
        assert not (branches[2] / "data" / "docs" / "test.txt").exists()
        
        # Create file in /data/images - should go to branch 1
        img_file = mountpoint / "data" / "images" / "pic.jpg"
        img_file.write_text("Image data")
        
        time.sleep(0.1)
        
        assert not (branches[0] / "data" / "images" / "pic.jpg").exists()
        assert (branches[1] / "data" / "images" / "pic.jpg").exists()
        assert not (branches[2] / "data" / "images" / "pic.jpg").exists()
    
    def test_epff_creates_path_if_needed(self, mounted_fs_with_policy):
        """Test that epff creates parent directories when no existing path found."""
        process, mountpoint, branches = mounted_fs_with_policy("epff")
        
        # Create a new deeply nested file - no existing parent
        nested_file = mountpoint / "new" / "deep" / "path" / "file.txt"
        nested_file.parent.mkdir(parents=True, exist_ok=True)
        nested_file.write_text("Nested content")
        
        time.sleep(0.1)
        
        # Should go to first writable branch
        assert (branches[0] / "new" / "deep" / "path" / "file.txt").exists()
    
    def test_epmfs_selects_most_free_space(self, mounted_fs_with_policy):
        """Test epmfs (existing path most free space) policy."""
        process, mountpoint, branches = mounted_fs_with_policy("epmfs")
        
        # Create same directory structure in all branches
        for branch in branches:
            (branch / "shared" / "data").mkdir(parents=True)
        
        # Add different amounts of data to establish free space differences
        # Branch 0: 40MB used
        with open(branches[0] / "bulk0.bin", 'wb') as f:
            f.write(b'0' * (40 * 1024 * 1024))
        
        # Branch 1: 10MB used (most free)
        with open(branches[1] / "bulk1.bin", 'wb') as f:
            f.write(b'1' * (10 * 1024 * 1024))
            
        # Branch 2: 25MB used
        with open(branches[2] / "bulk2.bin", 'wb') as f:
            f.write(b'2' * (25 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create file in shared directory - should go to branch 1 (most free)
        test_file = mountpoint / "shared" / "data" / "test.txt"
        test_file.write_text("EPMFS test")
        
        time.sleep(0.1)
        
        assert not (branches[0] / "shared" / "data" / "test.txt").exists()
        assert (branches[1] / "shared" / "data" / "test.txt").exists()
        assert not (branches[2] / "shared" / "data" / "test.txt").exists()
    
    def test_epmfs_fallback_behavior(self, mounted_fs_with_policy):
        """Test epmfs fallback when parent doesn't exist anywhere."""
        process, mountpoint, branches = mounted_fs_with_policy("epmfs")
        
        # No existing parents - should fall back to mfs behavior
        # Set up different free space
        with open(branches[0] / "space0.bin", 'wb') as f:
            f.write(b'A' * (30 * 1024 * 1024))
        with open(branches[2] / "space2.bin", 'wb') as f:
            f.write(b'C' * (20 * 1024 * 1024))
        # Branch 1 has most free space
        
        time.sleep(0.2)
        
        # Create file with non-existing parent
        new_file = mountpoint / "nonexistent" / "test.txt"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text("Fallback test")
        
        time.sleep(0.1)
        
        # Should go to branch 1 (most free space)
        assert (branches[1] / "nonexistent" / "test.txt").exists()
    
    def test_eplfs_selects_least_free_space(self, mounted_fs_with_policy):
        """Test eplfs (existing path least free space) policy."""
        process, mountpoint, branches = mounted_fs_with_policy("eplfs")
        
        # Create same directory structure in all branches
        for branch in branches:
            (branch / "storage").mkdir(parents=True)
        
        # Set up free space (opposite of epmfs test)
        # Branch 0: 10MB used (most free)
        with open(branches[0] / "data0.bin", 'wb') as f:
            f.write(b'0' * (10 * 1024 * 1024))
        
        # Branch 1: 40MB used (least free)
        with open(branches[1] / "data1.bin", 'wb') as f:
            f.write(b'1' * (40 * 1024 * 1024))
            
        # Branch 2: 25MB used
        with open(branches[2] / "data2.bin", 'wb') as f:
            f.write(b'2' * (25 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create file - should go to branch 1 (least free space)
        test_file = mountpoint / "storage" / "test.txt"
        test_file.write_text("EPLFS test")
        
        time.sleep(0.1)
        
        assert not (branches[0] / "storage" / "test.txt").exists()
        assert (branches[1] / "storage" / "test.txt").exists()
        assert not (branches[2] / "storage" / "test.txt").exists()
    
    def test_existing_path_with_multiple_matches(self, mounted_fs_with_policy):
        """Test behavior when parent exists in multiple branches."""
        process, mountpoint, branches = mounted_fs_with_policy("epff")
        
        # Create same structure in all branches
        for i, branch in enumerate(branches):
            (branch / "common" / "path").mkdir(parents=True)
            # Add marker file to identify branch
            (branch / "common" / "path" / f"branch{i}.txt").write_text(f"Branch {i}")
        
        time.sleep(0.1)
        
        # With epff, should use first branch
        test_file = mountpoint / "common" / "path" / "test.txt"
        test_file.write_text("Multi-match test")
        
        time.sleep(0.1)
        
        assert (branches[0] / "common" / "path" / "test.txt").exists()
        assert not (branches[1] / "common" / "path" / "test.txt").exists()
        assert not (branches[2] / "common" / "path" / "test.txt").exists()
    
    def test_existing_path_readonly_branches(self, mounted_fs_with_policy):
        """Test existing path policies with read-only branches."""
        process, mountpoint, branches = mounted_fs_with_policy("epff")
        
        # Create paths in all branches
        for branch in branches:
            (branch / "testdir").mkdir()
        
        # Make branch 0 read-only
        os.chmod(branches[0], 0o555)
        
        try:
            # Should skip read-only branch and use branch 1
            test_file = mountpoint / "testdir" / "file.txt"
            test_file.write_text("RO test")
            
            time.sleep(0.1)
            
            assert not (branches[0] / "testdir" / "file.txt").exists()
            assert (branches[1] / "testdir" / "file.txt").exists()
            
        finally:
            os.chmod(branches[0], 0o755)
    
    def test_path_preservation_complex_hierarchy(self, mounted_fs_with_policy):
        """Test path preservation with complex directory hierarchies."""
        process, mountpoint, branches = mounted_fs_with_policy("epmfs")
        
        # Create complex structures in different branches
        # Branch 0: /projects/web/frontend, /projects/web/backend
        (branches[0] / "projects" / "web" / "frontend").mkdir(parents=True)
        (branches[0] / "projects" / "web" / "backend").mkdir(parents=True)
        
        # Branch 1: /projects/mobile/ios, /projects/mobile/android  
        (branches[1] / "projects" / "mobile" / "ios").mkdir(parents=True)
        (branches[1] / "projects" / "mobile" / "android").mkdir(parents=True)
        
        # Branch 2: /projects/docs
        (branches[2] / "projects" / "docs").mkdir(parents=True)
        
        # Add varying amounts of data for epmfs testing
        with open(branches[0] / "web_data.bin", 'wb') as f:
            f.write(b'W' * (20 * 1024 * 1024))
        with open(branches[1] / "mobile_data.bin", 'wb') as f:
            f.write(b'M' * (15 * 1024 * 1024))
        # Branch 2 has most free space
        
        time.sleep(0.2)
        
        # Files should go to branches with matching parent structure
        web_file = mountpoint / "projects" / "web" / "frontend" / "app.js"
        web_file.write_text("Web app")
        
        mobile_file = mountpoint / "projects" / "mobile" / "ios" / "app.swift"
        mobile_file.write_text("iOS app")
        
        docs_file = mountpoint / "projects" / "docs" / "readme.md"
        docs_file.write_text("Documentation")
        
        time.sleep(0.2)
        
        # Verify files went to correct branches
        assert (branches[0] / "projects" / "web" / "frontend" / "app.js").exists()
        assert (branches[1] / "projects" / "mobile" / "ios" / "app.swift").exists()
        assert (branches[2] / "projects" / "docs" / "readme.md").exists()
    
    def test_existing_path_edge_cases(self, temp_mountpoint, fuse_manager):
        """Test edge cases for existing path policies."""
        # Test with single branch
        branch = Path(tempfile.mkdtemp(prefix="ep_single_"))
        try:
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=[branch],
                policy="epff"
            ) as (process, mp, branches_list):
                # Create structure
                (branch / "existing").mkdir()
                
                # Should work normally
                test_file = mp / "existing" / "file.txt"
                test_file.write_text("Single branch EP test")
                time.sleep(0.1)
                
                assert (branch / "existing" / "file.txt").exists()
                
        finally:
            shutil.rmtree(branch)
    
    def test_all_ep_policies_comparison(self, temp_mountpoint, temp_branches, fuse_manager):
        """Compare behavior of all existing path policies."""
        policies = ["epff", "epmfs", "eplfs"]
        results = {}
        
        # Set up branches with different free space
        # Branch 0: least free (50MB used)
        # Branch 1: medium free (30MB used)  
        # Branch 2: most free (10MB used)
        for i, size in enumerate([50, 30, 10]):
            data_file = temp_branches[i] / f"initial_{i}.bin"
            with open(data_file, 'wb') as f:
                f.write(b'X' * (size * 1024 * 1024))
        
        # Create same directory in all branches
        for branch in temp_branches:
            (branch / "shared").mkdir()
        
        # Test each policy
        for policy in policies:
            with fuse_manager.mounted_fs_with_args(
                mountpoint=temp_mountpoint,
                branches=temp_branches,
                policy=policy
            ) as (process, mp, branches_list):
                
                test_file = mp / "shared" / f"{policy}_test.txt"
                test_file.write_text(f"Testing {policy}")
                time.sleep(0.1)
                
                # Find which branch got the file
                for i, branch in enumerate(branches_list):
                    if (branch / "shared" / f"{policy}_test.txt").exists():
                        results[policy] = i
                        break
        
        # Verify expected behavior
        assert results["epff"] == 0, "epff should use first branch"
        assert results["epmfs"] == 2, "epmfs should use branch with most free space"  
        assert results["eplfs"] == 0, "eplfs should use branch with least free space"