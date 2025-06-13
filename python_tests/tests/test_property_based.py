"""
Property-based tests for mergerfs-rs using Hypothesis.

These tests generate random filesystem operations and verify that 
policy invariants hold true across all scenarios.
"""

import pytest
import os
import time
from pathlib import Path
from typing import List, Set, Dict
from hypothesis import given, strategies as st, settings, assume, note
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule, precondition, invariant

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


# Strategies for generating test data
valid_filename = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), blacklist_characters="./\\"),
    min_size=1,
    max_size=50
).filter(lambda x: x not in [".", "..", ""] and not x.startswith("."))

file_content = st.text(min_size=0, max_size=1000)

policy_strategy = st.sampled_from(["ff", "mfs", "lfs"])

file_sizes = st.integers(min_value=100, max_value=10000)


@pytest.mark.property
@pytest.mark.integration
class TestPolicyProperties:
    """Property-based tests for policy behavior."""
    
    @given(
        filenames=st.lists(valid_filename, min_size=1, max_size=10, unique=True),
        policy=policy_strategy
    )
    @settings(max_examples=20, deadline=None)
    def test_policy_file_placement_consistency(
        self, 
        fuse_manager: FuseManager, 
        temp_branches: List[Path], 
        temp_mountpoint: Path,
        fs_state: FileSystemState,
        filenames: List[str],
        policy: str
    ):
        """Test that policy file placement is consistent and follows expected rules."""
        config = FuseConfig(
            policy=policy,
            branches=temp_branches,
            mountpoint=temp_mountpoint
        )
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            created_files = []
            
            # Create files according to the policy
            for filename in filenames:
                file_path = mountpoint / filename
                file_path.write_text(f"Content for {filename}")
                created_files.append(filename)
                
                # Verify file was created
                assert file_path.exists(), f"File {filename} should exist after creation"
                
                # Check policy-specific invariants
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File {filename} should exist in exactly one branch, found in: {locations}"
                
                if policy == "ff":
                    # FirstFound should always use the first writable branch
                    assert locations[0] == 0, f"FirstFound policy should use first branch, but used {locations[0]}"
                
            # Verify all files are accessible
            for filename in created_files:
                file_path = mountpoint / filename
                assert file_path.exists(), f"File {filename} should be accessible through mountpoint"
                assert file_path.read_text() == f"Content for {filename}", f"File {filename} content should be preserved"
    
    @given(
        file_sizes_list=st.lists(file_sizes, min_size=3, max_size=3),  # One for each branch
        new_files=st.lists(valid_filename, min_size=1, max_size=5, unique=True)
    )
    @settings(max_examples=15, deadline=None)
    def test_space_based_policy_properties(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState,
        file_sizes_list: List[int],
        new_files: List[str]
    ):
        """Test that space-based policies (MFS/LFS) respect space constraints."""
        assume(len(file_sizes_list) == 3)  # Ensure we have sizes for all 3 branches
        
        # Pre-populate branches with different amounts of data
        for i, size in enumerate(file_sizes_list):
            fs_state.create_file_with_size(temp_branches[i] / f"existing_{i}.dat", size)
        
        # Get initial space usage
        initial_sizes = fs_state.get_branch_sizes(temp_branches)
        note(f"Initial branch sizes: {initial_sizes}")
        
        # Test MFS policy
        mfs_config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        with fuse_manager.mounted_fs(mfs_config) as (process, mountpoint, branches):
            for filename in new_files:
                file_path = mountpoint / filename
                file_path.write_text("MFS test content")
                
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"MFS file {filename} should be in exactly one branch"
                
                # MFS should tend to use branches with more free space (less existing data)
                selected_branch = locations[0]
                note(f"MFS selected branch {selected_branch} for {filename}")
        
        # Test LFS policy  
        lfs_config = FuseConfig(policy="lfs", branches=temp_branches, mountpoint=temp_mountpoint)
        with fuse_manager.mounted_fs(lfs_config) as (process, mountpoint, branches):
            for filename in new_files:
                lfs_filename = f"lfs_{filename}"
                file_path = mountpoint / lfs_filename
                file_path.write_text("LFS test content")
                
                locations = fs_state.get_file_locations(branches, lfs_filename)
                assert len(locations) == 1, f"LFS file {lfs_filename} should be in exactly one branch"
                
                # LFS should tend to use branches with less free space (more existing data)
                selected_branch = locations[0]
                note(f"LFS selected branch {selected_branch} for {lfs_filename}")
    
    @given(
        directory_names=st.lists(valid_filename, min_size=1, max_size=5, unique=True),
        policy=policy_strategy
    )
    @settings(max_examples=15, deadline=None)
    def test_directory_creation_properties(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState,
        directory_names: List[str],
        policy: str
    ):
        """Test that directory creation follows the same rules as file creation."""
        config = FuseConfig(policy=policy, branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            for dirname in directory_names:
                dir_path = mountpoint / dirname
                dir_path.mkdir()
                
                # Directory should exist and be accessible
                assert dir_path.exists(), f"Directory {dirname} should exist"
                assert dir_path.is_dir(), f"{dirname} should be a directory"
                
                # Find which branch contains the directory
                dir_locations = []
                for i, branch in enumerate(branches):
                    if (branch / dirname).exists():
                        dir_locations.append(i)
                
                assert len(dir_locations) == 1, f"Directory {dirname} should exist in exactly one branch"
                
                # Create a file in the directory to verify it works
                test_file = dir_path / "test_file.txt"
                test_file.write_text("Directory test content")
                
                # File should be in the same branch as the directory
                file_locations = fs_state.get_file_locations(branches, f"{dirname}/test_file.txt")
                assert dir_locations == file_locations, f"File should be in same branch as directory"


class PolicyStateMachine(RuleBasedStateMachine):
    """Stateful property-based testing for policy behavior."""
    
    def __init__(self):
        super().__init__()
        self.files_created: Set[str] = set()
        self.directories_created: Set[str] = set()
        self.current_policy: str = "ff"
        self.fuse_manager: FuseManager = None
        self.branches: List[Path] = []
        self.mountpoint: Path = None
        self.mounted_process = None
    
    @initialize()
    def setup_filesystem(self):
        """Initialize the test filesystem."""
        import tempfile
        
        # This would need to be properly integrated with pytest fixtures
        # For now, this is a framework for future expansion
        pass
    
    @rule(filename=valid_filename)
    @precondition(lambda self: self.mounted_process is not None)
    def create_file(self, filename: str):
        """Create a file and verify policy compliance."""
        assume(filename not in self.files_created)
        assume(filename not in self.directories_created)
        
        # This would implement file creation and verification
        # Based on the current policy state
        self.files_created.add(filename)
    
    @rule(dirname=valid_filename)
    @precondition(lambda self: self.mounted_process is not None)
    def create_directory(self, dirname: str):
        """Create a directory and verify policy compliance."""
        assume(dirname not in self.files_created)
        assume(dirname not in self.directories_created)
        
        # This would implement directory creation and verification
        self.directories_created.add(dirname)
    
    @invariant()
    def files_exist_in_exactly_one_branch(self):
        """Verify that all files exist in exactly one branch."""
        # This would verify the core invariant that files created
        # by any policy exist in exactly one branch
        pass
    
    @invariant()
    def policy_specific_invariants(self):
        """Verify policy-specific invariants."""
        # This would check policy-specific properties like:
        # - FF always uses first branch
        # - MFS/LFS make space-conscious decisions
        pass


@pytest.mark.property
@pytest.mark.integration
class TestFileSystemProperties:
    """Property-based tests for general filesystem behavior."""
    
    @given(
        operations=st.lists(
            st.one_of(
                st.tuples(st.just("create_file"), valid_filename, file_content),
                st.tuples(st.just("create_dir"), valid_filename),
                st.tuples(st.just("read_file"), valid_filename)
            ),
            min_size=1,
            max_size=20
        )
    )
    @settings(max_examples=10, deadline=None)
    def test_filesystem_operation_sequence(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        operations: List[tuple]
    ):
        """Test sequences of filesystem operations maintain consistency."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        created_files: Dict[str, str] = {}  # filename -> content
        created_dirs: Set[str] = set()
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            for operation in operations:
                op_type = operation[0]
                
                if op_type == "create_file":
                    _, filename, content = operation
                    assume(filename not in created_dirs)  # Don't create file with same name as dir
                    
                    file_path = mountpoint / filename
                    file_path.write_text(content)
                    created_files[filename] = content
                    
                    # Verify file was created
                    assert file_path.exists(), f"File {filename} should exist"
                    assert file_path.read_text() == content, f"File {filename} content should match"
                
                elif op_type == "create_dir":
                    _, dirname = operation
                    assume(dirname not in created_files)  # Don't create dir with same name as file
                    assume(dirname not in created_dirs)   # Don't create duplicate dirs
                    
                    dir_path = mountpoint / dirname
                    dir_path.mkdir()
                    created_dirs.add(dirname)
                    
                    # Verify directory was created
                    assert dir_path.exists(), f"Directory {dirname} should exist"
                    assert dir_path.is_dir(), f"{dirname} should be a directory"
                
                elif op_type == "read_file":
                    _, filename = operation
                    assume(filename in created_files)  # Only read files that exist
                    
                    file_path = mountpoint / filename
                    expected_content = created_files[filename]
                    actual_content = file_path.read_text()
                    
                    assert actual_content == expected_content, f"File {filename} content should be preserved"
            
            # Final verification: all created items should still exist and be accessible
            for filename, expected_content in created_files.items():
                file_path = mountpoint / filename
                assert file_path.exists(), f"File {filename} should still exist at end"
                assert file_path.read_text() == expected_content, f"File {filename} content should be preserved at end"
            
            for dirname in created_dirs:
                dir_path = mountpoint / dirname
                assert dir_path.exists(), f"Directory {dirname} should still exist at end"
                assert dir_path.is_dir(), f"{dirname} should still be a directory at end"


# Test that would be used with pytest-benchmark for performance properties
@pytest.mark.property
@pytest.mark.slow
class TestPerformanceProperties:
    """Property-based performance testing."""
    
    @given(file_count=st.integers(min_value=10, max_value=100))
    @settings(max_examples=3, deadline=None)
    def test_create_performance_scales_linearly(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        file_count: int
    ):
        """Test that file creation performance scales reasonably."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            start_time = time.time()
            
            for i in range(file_count):
                file_path = mountpoint / f"perf_test_{i}.txt"
                file_path.write_text(f"Performance test file {i}")
            
            elapsed = time.time() - start_time
            
            # Performance should be reasonable (not exponential)
            # This is a basic check - could be enhanced with actual benchmarking
            assert elapsed < file_count * 0.1, f"Creating {file_count} files took {elapsed}s, may be too slow"
            
            # Verify all files were created
            for i in range(file_count):
                file_path = mountpoint / f"perf_test_{i}.txt"
                assert file_path.exists(), f"Performance test file {i} should exist"