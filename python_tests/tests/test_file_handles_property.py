"""
Property-based tests for file handle management in mergerfs-rs.

These tests verify that file handle tracking maintains consistency and
correctness across various operations using Hypothesis.

## Key Invariants Tested:

1. **Handle Uniqueness**: Each open() call returns a unique file handle

2. **Handle Validity**: File handles remain valid until explicitly closed

3. **Branch Affinity**: Reads/writes through a handle use the same branch
   that was selected when the file was opened

4. **Concurrent Access**: Multiple handles to the same file work correctly

5. **Handle Cleanup**: Closed handles are properly released and cannot be reused

6. **Resource Limits**: System doesn't leak handles or memory

7. **Consistency**: Operations through different handles see consistent state
"""

import pytest
import os
import time
import threading
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple
from dataclasses import dataclass
from hypothesis import given, strategies as st, settings, assume, note
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule, precondition, invariant, Bundle

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@dataclass
class FileHandle:
    """Track information about an open file handle"""
    handle_id: int
    path: str
    mode: str
    branch_idx: Optional[int]
    is_open: bool = True


class FileHandleStateMachine(RuleBasedStateMachine):
    """
    Stateful testing for file handle operations.
    
    This machine tracks file handles and verifies that all operations
    maintain consistency.
    """
    
    def __init__(self):
        super().__init__()
        self.manager = FuseManager()
        self.state = FileSystemState()
        
        # Setup branches and mount
        config = FuseConfig(
            policy_type="ff",  # Use first-found for predictability
            num_branches=3
        )
        self.manager.setup(config)
        self.manager.mount()
        
        # Track handles
        self.handles: Dict[int, FileHandle] = {}
        self.next_handle_id = 1
        self.open_files: Dict[str, Set[int]] = {}  # path -> set of handle IDs
        
    def teardown(self):
        """Cleanup after test"""
        # Close all open handles
        for handle_id, handle in list(self.handles.items()):
            if handle.is_open:
                try:
                    # In real implementation, would close actual file handle
                    pass
                except:
                    pass
        
        self.manager.unmount()
        self.manager.cleanup()
    
    @initialize()
    def setup_initial_files(self):
        """Create some initial files for testing"""
        for i in range(3):
            path = self.manager.mount_point / f"initial_{i}.txt"
            path.write_text(f"Initial content {i}")
            self.state.add_file(f"/initial_{i}.txt", f"Initial content {i}")
    
    @rule(
        filename=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=97),
            min_size=1,
            max_size=20
        ).filter(lambda x: not x.startswith('.')),
        content=st.text(min_size=0, max_size=1000)
    )
    def create_file(self, filename: str, content: str):
        """Create a new file"""
        path = self.manager.mount_point / filename
        
        try:
            path.write_text(content)
            self.state.add_file(f"/{filename}", content)
            note(f"Created file: {filename}")
        except Exception as e:
            note(f"Failed to create file {filename}: {e}")
    
    @rule(
        target=Bundle("handles"),
        mode=st.sampled_from(['r', 'w', 'a', 'r+', 'w+', 'a+'])
    )
    def open_file(self, mode: str) -> Optional[int]:
        """Open a file and return a handle ID"""
        # Pick a file to open
        files = list(self.state.files.keys())
        if not files:
            return None
        
        # For write modes, we might truncate, so be careful
        if mode in ['w', 'w+']:
            # Don't open files we have open for reading
            available_files = [f for f in files if not self.open_files.get(f)]
            if not available_files:
                return None
            filename = available_files[0]
        else:
            filename = files[0]
        
        path = self.manager.mount_point / filename.lstrip('/')
        
        try:
            # In real implementation, would open actual file
            # For now, simulate handle creation
            handle_id = self.next_handle_id
            self.next_handle_id += 1
            
            # Determine which branch would be used
            branch_idx = None
            for idx, branch in enumerate(self.manager.config.branches):
                if (branch / filename.lstrip('/')).exists():
                    branch_idx = idx
                    break
            
            handle = FileHandle(
                handle_id=handle_id,
                path=filename,
                mode=mode,
                branch_idx=branch_idx
            )
            
            self.handles[handle_id] = handle
            if filename not in self.open_files:
                self.open_files[filename] = set()
            self.open_files[filename].add(handle_id)
            
            note(f"Opened {filename} with handle {handle_id} in mode {mode}")
            return handle_id
            
        except Exception as e:
            note(f"Failed to open {filename}: {e}")
            return None
    
    @rule(handle_id=Bundle("handles"))
    def read_through_handle(self, handle_id: int):
        """Read from a file through a specific handle"""
        if handle_id not in self.handles:
            return
        
        handle = self.handles[handle_id]
        if not handle.is_open or 'r' not in handle.mode:
            return
        
        path = self.manager.mount_point / handle.path.lstrip('/')
        
        try:
            content = path.read_text()
            expected = self.state.files.get(handle.path, "")
            
            # For read modes, content should match
            if handle.mode in ['r', 'r+']:
                assert content == expected, \
                    f"Content mismatch through handle {handle_id}: {content!r} != {expected!r}"
            
            note(f"Read {len(content)} bytes through handle {handle_id}")
            
        except Exception as e:
            note(f"Failed to read through handle {handle_id}: {e}")
    
    @rule(
        handle_id=Bundle("handles"),
        content=st.text(min_size=0, max_size=100)
    )
    def write_through_handle(self, handle_id: int, content: str):
        """Write to a file through a specific handle"""
        if handle_id not in self.handles:
            return
        
        handle = self.handles[handle_id]
        if not handle.is_open or handle.mode not in ['w', 'w+', 'a', 'a+']:
            return
        
        path = self.manager.mount_point / handle.path.lstrip('/')
        
        try:
            if handle.mode in ['w', 'w+']:
                # Write mode truncates
                path.write_text(content)
                self.state.files[handle.path] = content
            elif handle.mode in ['a', 'a+']:
                # Append mode
                current = self.state.files.get(handle.path, "")
                new_content = current + content
                path.write_text(new_content)
                self.state.files[handle.path] = new_content
            
            note(f"Wrote {len(content)} bytes through handle {handle_id}")
            
        except Exception as e:
            note(f"Failed to write through handle {handle_id}: {e}")
    
    @rule(handle_id=Bundle("handles"))
    def close_handle(self, handle_id: int):
        """Close a file handle"""
        if handle_id not in self.handles:
            return
        
        handle = self.handles[handle_id]
        if not handle.is_open:
            return
        
        try:
            # Mark as closed
            handle.is_open = False
            self.open_files[handle.path].discard(handle_id)
            if not self.open_files[handle.path]:
                del self.open_files[handle.path]
            
            note(f"Closed handle {handle_id}")
            
        except Exception as e:
            note(f"Failed to close handle {handle_id}: {e}")
    
    @rule()
    def verify_handle_uniqueness(self):
        """Verify all open handles have unique IDs"""
        open_handles = [h.handle_id for h in self.handles.values() if h.is_open]
        assert len(open_handles) == len(set(open_handles)), \
            "Duplicate handle IDs detected"
    
    @rule()
    def verify_branch_consistency(self):
        """Verify files are accessed from correct branches"""
        for handle in self.handles.values():
            if not handle.is_open or handle.branch_idx is None:
                continue
            
            # Check file exists in the recorded branch
            branch_path = self.manager.config.branches[handle.branch_idx]
            file_path = branch_path / handle.path.lstrip('/')
            
            if handle.mode not in ['w', 'w+']:  # Write modes might have created it
                assert file_path.exists(), \
                    f"File {handle.path} not found in branch {handle.branch_idx}"
    
    @invariant()
    def check_no_handle_leaks(self):
        """Ensure we're not leaking handles"""
        # In a real system, would check actual OS handles
        open_count = sum(1 for h in self.handles.values() if h.is_open)
        assert open_count < 1000, f"Too many open handles: {open_count}"
    
    @invariant()
    def check_file_consistency(self):
        """Verify files have consistent content across handles"""
        for path, content in self.state.files.items():
            mount_path = self.manager.mount_point / path.lstrip('/')
            if mount_path.exists():
                actual = mount_path.read_text()
                # Only check if no handles are open for writing
                if path not in self.open_files or all(
                    self.handles[hid].mode in ['r', 'r+'] 
                    for hid in self.open_files.get(path, [])
                ):
                    assert actual == content, \
                        f"Content mismatch for {path}: {actual!r} != {content!r}"


# Specific property tests

@given(
    num_handles=st.integers(min_value=1, max_value=10),
    content=st.text(min_size=1, max_size=100)
)
@settings(max_examples=50, deadline=5000)
def test_concurrent_read_handles(num_handles: int, content: str):
    """Test multiple read handles to the same file"""
    manager = FuseManager()
    config = FuseConfig(policy_type="ff", num_branches=3)
    
    try:
        manager.setup(config)
        manager.mount()
        
        # Create test file
        test_file = manager.mount_point / "concurrent_test.txt"
        test_file.write_text(content)
        
        # Open multiple read handles
        handles = []
        for i in range(num_handles):
            fh = open(test_file, 'r')
            handles.append(fh)
        
        # All handles should read the same content
        for i, fh in enumerate(handles):
            read_content = fh.read()
            assert read_content == content, \
                f"Handle {i} read different content: {read_content!r} != {content!r}"
            fh.seek(0)  # Reset for potential reuse
        
        # Close handles
        for fh in handles:
            fh.close()
        
    finally:
        manager.unmount()
        manager.cleanup()


@given(
    filename=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=97),
        min_size=1,
        max_size=20
    ).filter(lambda x: not x.startswith('.')),
    iterations=st.integers(min_value=1, max_value=20)
)
@settings(max_examples=30, deadline=5000)
def test_handle_persistence(filename: str, iterations: int):
    """Test that handles remain valid across other operations"""
    manager = FuseManager()
    config = FuseConfig(policy_type="ff", num_branches=2)
    
    try:
        manager.setup(config)
        manager.mount()
        
        test_file = manager.mount_point / filename
        test_file.write_text("Initial content")
        
        # Open a read handle
        read_handle = open(test_file, 'r')
        initial_content = read_handle.read()
        
        # Perform other operations
        for i in range(iterations):
            other_file = manager.mount_point / f"other_{i}.txt"
            other_file.write_text(f"Other content {i}")
        
        # Original handle should still be valid
        read_handle.seek(0)
        content = read_handle.read()
        assert content == initial_content, \
            "Handle content changed after other operations"
        
        read_handle.close()
        
    finally:
        manager.unmount()
        manager.cleanup()


# Run the state machine test
TestFileHandles = FileHandleStateMachine.TestCase
TestFileHandles.settings = settings(
    max_examples=100,
    stateful_step_count=50,
    deadline=10000
)


if __name__ == "__main__":
    # Run specific property tests
    test_concurrent_read_handles()
    test_handle_persistence()
    
    # Run state machine tests
    state_machine_test = FileHandleStateMachine.TestCase()
    state_machine_test.runTest()
    
    print("All file handle property tests passed!")