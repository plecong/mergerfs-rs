"""
Property-based tests for statfs implementation in mergerfs-rs.

These tests verify that filesystem statistics are correctly aggregated
and maintain consistency across various operations.

## Key Invariants Tested:

1. **Aggregation Correctness**: Total space is properly aggregated from branches

2. **Free Space Consistency**: Free space never exceeds total space

3. **Available Space**: Available space never exceeds free space

4. **Space Accounting**: Creating/deleting files correctly updates statistics

5. **Device Deduplication**: Branches on same device aren't double-counted

6. **Block Size Normalization**: Different block sizes are handled correctly

7. **Monotonicity**: Operations maintain expected ordering of values
"""

import pytest
import os
import shutil
from pathlib import Path
from typing import List, Dict, Tuple
from hypothesis import given, strategies as st, settings, assume, note
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule, invariant

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


def get_fs_stats(path: Path) -> Dict[str, int]:
    """Get filesystem statistics for a path"""
    stat = os.statvfs(path)
    return {
        'blocks': stat.f_blocks,
        'bfree': stat.f_bfree,
        'bavail': stat.f_bavail,
        'files': stat.f_files,
        'ffree': stat.f_ffree,
        'bsize': stat.f_bsize,
        'frsize': stat.f_frsize,
        'namemax': stat.f_namemax
    }


@pytest.mark.slow
class StatFSStateMachine(RuleBasedStateMachine):
    """
    Stateful testing for statfs operations.
    
    This machine tracks filesystem operations and verifies that
    statistics remain consistent.
    """
    
    def __init__(self):
        super().__init__()
        self.manager = FuseManager()
        self.state = FileSystemState()
        
        # Setup branches and mount
        self.branches = self.manager.create_temp_dirs(3)
        self.mountpoint = self.manager.create_temp_mountpoint()
        config = FuseConfig(
            policy="ff",
            branches=self.branches,
            mountpoint=self.mountpoint
        )
        self.process = self.manager.mount(config)
        self.config = config
        
        # Track space usage
        self.files_created: Dict[str, int] = {}  # filename -> size
        self.initial_stats = None
        
    def teardown(self):
        """Cleanup after test"""
        self.manager.unmount(self.mountpoint)
        self.manager.cleanup()
    
    @initialize()
    def capture_initial_stats(self):
        """Capture initial filesystem statistics"""
        self.initial_stats = get_fs_stats(self.mountpoint)
        
        # Also capture per-branch stats
        self.branch_stats = []
        for branch in self.branches:
            self.branch_stats.append(get_fs_stats(branch))
    
    @rule(
        filename=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=97),
            min_size=1,
            max_size=20
        ).filter(lambda x: not x.startswith('.')),
        size_kb=st.integers(min_value=1, max_value=1024)  # 1KB to 1MB
    )
    def create_file(self, filename: str, size_kb: int):
        """Create a file of specific size"""
        if filename in self.files_created:
            return  # Skip if already exists
        
        path = self.mountpoint / filename
        size_bytes = size_kb * 1024
        
        try:
            # Create file with specific size
            with open(path, 'wb') as f:
                f.write(b'0' * size_bytes)
            
            self.files_created[filename] = size_bytes
            # Note: FileSystemState doesn't have add_file method
            note(f"Created {filename} with {size_kb}KB")
            
        except Exception as e:
            note(f"Failed to create {filename}: {e}")
    
    @rule()
    def delete_file(self):
        """Delete a random file"""
        if not self.files_created:
            return
        
        filename = list(self.files_created.keys())[0]
        path = self.mountpoint / filename
        
        try:
            os.unlink(path)
            del self.files_created[filename]
            # Note: FileSystemState doesn't have files attribute
            note(f"Deleted {filename}")
            
        except Exception as e:
            note(f"Failed to delete {filename}: {e}")
    
    @rule(
        dirname=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=97),
            min_size=1,
            max_size=10
        ).filter(lambda x: not x.startswith('.'))
    )
    def create_directory(self, dirname: str):
        """Create a directory"""
        path = self.mountpoint / dirname
        
        try:
            path.mkdir(exist_ok=True)
            note(f"Created directory {dirname}")
        except Exception as e:
            note(f"Failed to create directory {dirname}: {e}")
    
    @invariant()
    def check_basic_constraints(self):
        """Verify basic statfs constraints"""
        stats = get_fs_stats(self.mountpoint)
        
        # Basic sanity checks
        assert stats['blocks'] > 0, "Total blocks must be positive"
        assert stats['bfree'] >= 0, "Free blocks must be non-negative"
        assert stats['bavail'] >= 0, "Available blocks must be non-negative"
        assert stats['files'] > 0, "Total inodes must be positive"
        assert stats['ffree'] >= 0, "Free inodes must be non-negative"
        
        # Ordering constraints
        assert stats['bfree'] <= stats['blocks'], \
            f"Free blocks {stats['bfree']} exceeds total {stats['blocks']}"
        assert stats['bavail'] <= stats['bfree'], \
            f"Available blocks {stats['bavail']} exceeds free {stats['bfree']}"
        assert stats['ffree'] <= stats['files'], \
            f"Free inodes {stats['ffree']} exceeds total {stats['files']}"
    
    @invariant()
    def check_space_accounting(self):
        """Verify space usage is properly accounted"""
        if not self.initial_stats:
            return
        
        current_stats = get_fs_stats(self.mountpoint)
        
        # Calculate expected space usage
        total_file_size = sum(self.files_created.values())
        blocks_per_byte = 1.0 / current_stats['frsize']
        expected_blocks_used = int(total_file_size * blocks_per_byte)
        
        # Allow for filesystem overhead (metadata, etc)
        overhead_factor = 1.2
        
        # Free space should have decreased by at least the file sizes
        blocks_used = self.initial_stats['bfree'] - current_stats['bfree']
        
        # Only check if we've created files
        if total_file_size > 0:
            assert blocks_used >= expected_blocks_used / overhead_factor, \
                f"Space usage {blocks_used} blocks less than expected {expected_blocks_used} blocks"
    
    @invariant()
    def check_aggregation_consistency(self):
        """Verify stats are properly aggregated from branches"""
        mount_stats = get_fs_stats(self.mountpoint)
        
        # Get current branch stats
        current_branch_stats = []
        for branch in self.branches:
            current_branch_stats.append(get_fs_stats(branch))
        
        # Check if all branches are on the same device
        devices = set()
        for branch in self.branches:
            stat = os.stat(branch)
            devices.add(stat.st_dev)
        
        if len(devices) == 1:
            # Same device - should not multiply space
            # Mount stats should be similar to any single branch
            branch_stat = current_branch_stats[0]
            
            # Allow 10% tolerance for overhead
            assert mount_stats['blocks'] <= branch_stat['blocks'] * 1.1, \
                "Same-device branches should not multiply total space"
        else:
            # Different devices - should aggregate
            total_blocks = sum(s['blocks'] for s in current_branch_stats)
            
            # Mount should show aggregated space (with some overhead)
            assert mount_stats['blocks'] >= total_blocks * 0.9, \
                "Multi-device aggregation seems incorrect"


# Specific property tests

@pytest.mark.slow
@given(
    num_files=st.integers(min_value=0, max_value=10),
    file_sizes=st.lists(
        st.integers(min_value=1, max_value=1024),  # KB
        min_size=0,
        max_size=10
    )
)
@settings(max_examples=30, deadline=10000)
def test_space_calculation(num_files: int, file_sizes: List[int]):
    """Test that space calculations are correct after file operations"""
    assume(len(file_sizes) >= num_files)
    
    manager = FuseManager()
    branches = manager.create_temp_dirs(2)
    mountpoint = manager.create_temp_mountpoint()
    config = FuseConfig(policy="ff", branches=branches, mountpoint=mountpoint)
    
    try:
        process = manager.mount(config)
        
        # Get initial stats
        initial = get_fs_stats(mountpoint)
        
        # Create files
        total_size = 0
        for i in range(num_files):
            size_bytes = file_sizes[i] * 1024
            path = mountpoint / f"test_{i}.dat"
            
            with open(path, 'wb') as f:
                f.write(b'X' * size_bytes)
            
            total_size += size_bytes
        
        # Get stats after creating files
        after = get_fs_stats(mountpoint)
        
        # Free space should have decreased if files were created
        if num_files > 0 and total_size > 0:
            assert after['bfree'] < initial['bfree'], \
                "Free space should decrease after creating files"
        
        # The decrease should be at least the file sizes
        if num_files > 0 and total_size > 0:
            blocks_used = initial['bfree'] - after['bfree']
            bytes_used = blocks_used * after['frsize']
            
            # Allow 20% overhead for filesystem metadata
            assert bytes_used >= total_size * 0.8, \
                f"Space used {bytes_used} less than file sizes {total_size}"
        
    finally:
        manager.unmount(mountpoint)
        manager.cleanup()


@pytest.mark.slow
@given(
    block_sizes=st.lists(
        st.sampled_from([512, 1024, 2048, 4096, 8192]),
        min_size=1,
        max_size=3
    )
)
@settings(max_examples=20, deadline=10000)
def test_block_size_normalization(block_sizes: List[int]):
    """Test that different block sizes are handled correctly"""
    # This test is more conceptual since we can't easily control
    # the block sizes of actual filesystems
    
    manager = FuseManager()
    branches = manager.create_temp_dirs(len(block_sizes))
    mountpoint = manager.create_temp_mountpoint()
    config = FuseConfig(policy="ff", branches=branches, mountpoint=mountpoint)
    
    try:
        process = manager.mount(config)
        
        stats = get_fs_stats(mountpoint)
        
        # Block size should be reasonable
        assert 512 <= stats['bsize'] <= 65536, \
            f"Block size {stats['bsize']} out of reasonable range"
        
        # Fragment size should not exceed block size
        assert stats['frsize'] <= stats['bsize'], \
            "Fragment size should not exceed block size"
        
        # Both should be powers of 2 (common requirement)
        assert (stats['bsize'] & (stats['bsize'] - 1)) == 0, \
            "Block size should be power of 2"
        assert (stats['frsize'] & (stats['frsize'] - 1)) == 0, \
            "Fragment size should be power of 2"
        
    finally:
        manager.unmount(mountpoint)
        manager.cleanup()


# Run the state machine test
@pytest.mark.slow
class TestStatFS(StatFSStateMachine.TestCase):
    settings = settings(
        max_examples=50,
        stateful_step_count=30,
        deadline=15000
    )


if __name__ == "__main__":
    # Run specific property tests
    test_space_calculation()
    test_block_size_normalization()
    
    # Run state machine tests
    state_machine_test = StatFSStateMachine.TestCase()
    state_machine_test.runTest()
    
    print("All statfs property tests passed!")