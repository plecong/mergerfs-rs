"""
Fuzz testing foundation for mergerfs-rs.

This module provides the foundation for fuzz testing the FUSE filesystem,
including random operation generation, invariant checking, and crash detection.
"""

import pytest
import os
import time
import random
import string
import signal
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import tempfile
import subprocess

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


class FuzzOperation(Enum):
    """Types of operations for fuzz testing."""
    CREATE_FILE = "create_file"
    CREATE_DIR = "create_dir"
    READ_FILE = "read_file"
    LIST_DIR = "list_dir"
    DELETE_FILE = "delete_file"
    DELETE_DIR = "delete_dir"
    RENAME_FILE = "rename_file"
    RENAME_DIR = "rename_dir"
    STAT_FILE = "stat_file"
    CHMOD_FILE = "chmod_file"


@dataclass
class FuzzResult:
    """Result of a fuzz testing operation."""
    operation: FuzzOperation
    target: str
    success: bool
    error: Optional[str] = None
    duration: float = 0.0
    additional_data: Optional[Dict[str, Any]] = None


class FuzzOperationGenerator:
    """Generates random filesystem operations for fuzz testing."""
    
    def __init__(self, seed: Optional[int] = None):
        """Initialize the fuzz operation generator.
        
        Args:
            seed: Random seed for reproducible testing
        """
        if seed is not None:
            random.seed(seed)
        
        self.existing_files: Set[str] = set()
        self.existing_dirs: Set[str] = set()
        self.operation_weights = {
            FuzzOperation.CREATE_FILE: 30,
            FuzzOperation.CREATE_DIR: 20,
            FuzzOperation.READ_FILE: 25,
            FuzzOperation.LIST_DIR: 15,
            FuzzOperation.DELETE_FILE: 5,
            FuzzOperation.DELETE_DIR: 3,
            FuzzOperation.RENAME_FILE: 1,
            FuzzOperation.RENAME_DIR: 1,
        }
    
    def generate_random_filename(self, max_length: int = 50) -> str:
        """Generate a random filename."""
        # Mix of safe and potentially problematic filename characters
        safe_chars = string.ascii_letters + string.digits + "_-"
        tricky_chars = " .()[]{}#&"
        
        # Most of the time use safe characters
        if random.random() < 0.8:
            chars = safe_chars
        else:
            chars = safe_chars + tricky_chars
        
        length = random.randint(1, max_length)
        filename = ''.join(random.choice(chars) for _ in range(length))
        
        # Avoid empty names or names that are just dots
        if not filename or filename in [".", "..", ""] or filename.isspace():
            filename = "fuzz_" + str(random.randint(1000, 9999))
        
        return filename
    
    def generate_random_content(self, max_size: int = 1024) -> str:
        """Generate random file content."""
        size = random.randint(0, max_size)
        
        if size == 0:
            return ""
        
        # Mix of different content types
        content_type = random.choice([
            "ascii_printable",
            "ascii_with_newlines", 
            "binary_like",
            "unicode",
            "repeated_pattern"
        ])
        
        if content_type == "ascii_printable":
            return ''.join(random.choice(string.printable) for _ in range(size))
        elif content_type == "ascii_with_newlines":
            content = []
            remaining = size
            while remaining > 0:
                line_len = min(random.randint(0, 80), remaining)
                line = ''.join(random.choice(string.ascii_letters + string.digits + " ") for _ in range(line_len))
                content.append(line)
                remaining -= line_len + 1  # +1 for newline
                if remaining > 0:
                    content.append("\n")
                    remaining -= 1
            return ''.join(content)
        elif content_type == "binary_like":
            return ''.join(chr(random.randint(0, 255)) for _ in range(size))
        elif content_type == "unicode":
            # Use a mix of ASCII and some Unicode characters
            chars = string.ascii_letters + "αβγδεζηθικλμνξοπρστυφχψω"
            return ''.join(random.choice(chars) for _ in range(size))
        elif content_type == "repeated_pattern":
            pattern = random.choice(["A", "0", "test", "\n", " "])
            return pattern * (size // len(pattern)) + pattern[:size % len(pattern)]
        
        return "default_content"
    
    def generate_operation(self) -> Tuple[FuzzOperation, Dict[str, Any]]:
        """Generate a random filesystem operation."""
        # Weighted random choice of operation
        operations = list(self.operation_weights.keys())
        weights = list(self.operation_weights.values())
        operation = random.choices(operations, weights=weights)[0]
        
        params = {}
        
        if operation == FuzzOperation.CREATE_FILE:
            params['filename'] = self.generate_random_filename()
            params['content'] = self.generate_random_content()
            
        elif operation == FuzzOperation.CREATE_DIR:
            params['dirname'] = self.generate_random_filename()
            
        elif operation == FuzzOperation.READ_FILE:
            if self.existing_files:
                params['filename'] = random.choice(list(self.existing_files))
            else:
                # Try to read a file that might not exist
                params['filename'] = self.generate_random_filename()
                
        elif operation == FuzzOperation.LIST_DIR:
            if self.existing_dirs:
                params['dirname'] = random.choice(list(self.existing_dirs))
            else:
                params['dirname'] = "."  # List root directory
                
        elif operation == FuzzOperation.DELETE_FILE:
            if self.existing_files:
                params['filename'] = random.choice(list(self.existing_files))
            else:
                params['filename'] = self.generate_random_filename()
                
        elif operation == FuzzOperation.DELETE_DIR:
            if self.existing_dirs:
                params['dirname'] = random.choice(list(self.existing_dirs))
            else:
                params['dirname'] = self.generate_random_filename()
                
        elif operation in [FuzzOperation.RENAME_FILE, FuzzOperation.RENAME_DIR]:
            if operation == FuzzOperation.RENAME_FILE and self.existing_files:
                params['old_name'] = random.choice(list(self.existing_files))
            elif operation == FuzzOperation.RENAME_DIR and self.existing_dirs:
                params['old_name'] = random.choice(list(self.existing_dirs))
            else:
                params['old_name'] = self.generate_random_filename()
            params['new_name'] = self.generate_random_filename()
            
        elif operation == FuzzOperation.STAT_FILE:
            if self.existing_files:
                params['filename'] = random.choice(list(self.existing_files))
            else:
                params['filename'] = self.generate_random_filename()
        
        return operation, params
    
    def update_state(self, operation: FuzzOperation, params: Dict[str, Any], success: bool):
        """Update the generator's state based on operation results."""
        if success:
            if operation == FuzzOperation.CREATE_FILE:
                self.existing_files.add(params['filename'])
            elif operation == FuzzOperation.CREATE_DIR:
                self.existing_dirs.add(params['dirname'])
            elif operation == FuzzOperation.DELETE_FILE:
                self.existing_files.discard(params['filename'])
            elif operation == FuzzOperation.DELETE_DIR:
                self.existing_dirs.discard(params['dirname'])
            elif operation == FuzzOperation.RENAME_FILE:
                self.existing_files.discard(params['old_name'])
                self.existing_files.add(params['new_name'])
            elif operation == FuzzOperation.RENAME_DIR:
                self.existing_dirs.discard(params['old_name'])
                self.existing_dirs.add(params['new_name'])


class FuzzTester:
    """Main fuzz testing orchestrator."""
    
    def __init__(self, fuse_manager: FuseManager, config: FuseConfig, seed: Optional[int] = None):
        """Initialize the fuzz tester.
        
        Args:
            fuse_manager: FUSE manager instance
            config: FUSE configuration
            seed: Random seed for reproducible testing
        """
        self.fuse_manager = fuse_manager
        self.config = config
        self.generator = FuzzOperationGenerator(seed)
        self.results: List[FuzzResult] = []
        self.fs_state = FileSystemState()
        
        # Invariants to check
        self.invariants = [
            self._check_files_in_single_branch,
            self._check_filesystem_consistency,
            self._check_no_corruption,
        ]
    
    def execute_operation(self, mountpoint: Path, operation: FuzzOperation, params: Dict[str, Any]) -> FuzzResult:
        """Execute a single fuzz operation."""
        start_time = time.time()
        
        try:
            success = False
            error = None
            additional_data = {}
            
            if operation == FuzzOperation.CREATE_FILE:
                file_path = mountpoint / params['filename']
                file_path.write_text(params['content'])
                success = file_path.exists()
                
            elif operation == FuzzOperation.CREATE_DIR:
                dir_path = mountpoint / params['dirname']
                dir_path.mkdir(exist_ok=True)
                success = dir_path.exists() and dir_path.is_dir()
                
            elif operation == FuzzOperation.READ_FILE:
                file_path = mountpoint / params['filename']
                if file_path.exists():
                    content = file_path.read_text()
                    additional_data['content_length'] = len(content)
                    success = True
                else:
                    success = False
                    error = "File does not exist"
                    
            elif operation == FuzzOperation.LIST_DIR:
                dir_path = mountpoint / params['dirname']
                if dir_path.exists() and dir_path.is_dir():
                    files = list(dir_path.iterdir())
                    additional_data['file_count'] = len(files)
                    success = True
                else:
                    success = False
                    error = "Directory does not exist"
                    
            elif operation == FuzzOperation.DELETE_FILE:
                file_path = mountpoint / params['filename']
                if file_path.exists():
                    file_path.unlink()
                    success = not file_path.exists()
                else:
                    success = False
                    error = "File does not exist"
                    
            elif operation == FuzzOperation.DELETE_DIR:
                dir_path = mountpoint / params['dirname']
                if dir_path.exists() and dir_path.is_dir():
                    dir_path.rmdir()
                    success = not dir_path.exists()
                else:
                    success = False
                    error = "Directory does not exist or not empty"
                    
            elif operation in [FuzzOperation.RENAME_FILE, FuzzOperation.RENAME_DIR]:
                old_path = mountpoint / params['old_name']
                new_path = mountpoint / params['new_name']
                if old_path.exists():
                    old_path.rename(new_path)
                    success = new_path.exists() and not old_path.exists()
                else:
                    success = False
                    error = "Source does not exist"
                    
            elif operation == FuzzOperation.STAT_FILE:
                file_path = mountpoint / params['filename']
                if file_path.exists():
                    stat_result = file_path.stat()
                    additional_data['size'] = stat_result.st_size
                    additional_data['mtime'] = stat_result.st_mtime
                    success = True
                else:
                    success = False
                    error = "File does not exist"
            
            duration = time.time() - start_time
            target = params.get('filename') or params.get('dirname') or params.get('old_name', 'unknown')
            
            return FuzzResult(
                operation=operation,
                target=target,
                success=success,
                error=error,
                duration=duration,
                additional_data=additional_data
            )
            
        except Exception as e:
            duration = time.time() - start_time
            target = params.get('filename') or params.get('dirname') or params.get('old_name', 'unknown')
            
            return FuzzResult(
                operation=operation,
                target=target,
                success=False,
                error=str(e),
                duration=duration
            )
    
    def _check_files_in_single_branch(self, mountpoint: Path, branches: List[Path]) -> bool:
        """Check that each file exists in exactly one branch."""
        try:
            all_files = set()
            
            # Collect all files from mountpoint view
            for file_path in mountpoint.rglob("*"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(mountpoint)
                    all_files.add(str(rel_path))
            
            # Check each file exists in exactly one branch
            for file_rel_path in all_files:
                locations = []
                for i, branch in enumerate(branches):
                    if (branch / file_rel_path).exists():
                        locations.append(i)
                
                if len(locations) != 1:
                    print(f"Invariant violation: File {file_rel_path} exists in {len(locations)} branches: {locations}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"Error checking file branch invariant: {e}")
            return False
    
    def _check_filesystem_consistency(self, mountpoint: Path, branches: List[Path]) -> bool:
        """Check general filesystem consistency."""
        try:
            # Basic checks that the filesystem is still functional
            
            # Can we list the root directory?
            list(mountpoint.iterdir())
            
            # Can we create and read a test file?
            test_file = mountpoint / f"invariant_test_{time.time()}.txt"
            test_content = "Invariant check test content"
            test_file.write_text(test_content)
            
            if not test_file.exists():
                print("Invariant violation: Cannot create test file")
                return False
            
            read_content = test_file.read_text()
            if read_content != test_content:
                print("Invariant violation: Test file content mismatch")
                return False
            
            # Clean up test file
            test_file.unlink()
            
            return True
            
        except Exception as e:
            print(f"Error checking filesystem consistency: {e}")
            return False
    
    def _check_no_corruption(self, mountpoint: Path, branches: List[Path]) -> bool:
        """Check for signs of filesystem corruption."""
        try:
            # Check that we can still access the filesystem
            # This is a basic check - more sophisticated corruption detection could be added
            
            # Try to access each branch directory
            for branch in branches:
                if not branch.exists():
                    print(f"Invariant violation: Branch {branch} no longer exists")
                    return False
                
                # Try to list the branch
                list(branch.iterdir())
            
            return True
            
        except Exception as e:
            print(f"Error checking for corruption: {e}")
            return False
    
    def check_invariants(self, mountpoint: Path, branches: List[Path]) -> List[str]:
        """Check all invariants and return list of violations."""
        violations = []
        
        for invariant_check in self.invariants:
            try:
                if not invariant_check(mountpoint, branches):
                    violations.append(invariant_check.__name__)
            except Exception as e:
                violations.append(f"{invariant_check.__name__}: {e}")
        
        return violations
    
    def run_fuzz_session(self, num_operations: int = 100, check_invariants_every: int = 10) -> Dict[str, Any]:
        """Run a fuzz testing session."""
        with self.fuse_manager.mounted_fs(self.config) as (process, mountpoint, branches):
            session_results = {
                'total_operations': num_operations,
                'successful_operations': 0,
                'failed_operations': 0,
                'invariant_violations': [],
                'operations_by_type': {},
                'errors': [],
                'start_time': time.time(),
                'end_time': None
            }
            
            for i in range(num_operations):
                # Generate and execute operation
                operation, params = self.generator.generate_operation()
                result = self.execute_operation(mountpoint, operation, params)
                
                # Update generator state
                self.generator.update_state(operation, params, result.success)
                
                # Record results
                self.results.append(result)
                
                if result.success:
                    session_results['successful_operations'] += 1
                else:
                    session_results['failed_operations'] += 1
                    if result.error:
                        session_results['errors'].append(f"{operation.value}: {result.error}")
                
                # Track operations by type
                op_name = operation.value
                if op_name not in session_results['operations_by_type']:
                    session_results['operations_by_type'][op_name] = 0
                session_results['operations_by_type'][op_name] += 1
                
                # Check invariants periodically
                if (i + 1) % check_invariants_every == 0:
                    violations = self.check_invariants(mountpoint, branches)
                    if violations:
                        session_results['invariant_violations'].extend(violations)
                        print(f"Invariant violations at operation {i+1}: {violations}")
                        
                        # Stop if we detect serious problems
                        if len(violations) > 3:
                            print("Too many invariant violations, stopping fuzz session")
                            break
            
            session_results['end_time'] = time.time()
            return session_results


@pytest.mark.fuzz
@pytest.mark.integration
@pytest.mark.slow
class TestFuzzFoundation:
    """Foundation tests for fuzz testing."""
    
    def test_basic_fuzz_session(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test basic fuzz testing functionality."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        fuzz_tester = FuzzTester(fuse_manager, config, seed=12345)  # Reproducible seed
        
        # Run a small fuzz session
        results = fuzz_tester.run_fuzz_session(num_operations=20, check_invariants_every=5)
        
        # Verify basic functionality
        assert results['total_operations'] == 20
        assert results['successful_operations'] + results['failed_operations'] == 20
        assert results['end_time'] > results['start_time']
        assert len(results['invariant_violations']) == 0, f"Should have no invariant violations: {results['invariant_violations']}"
        
        # Should have attempted various operations
        assert len(results['operations_by_type']) > 1, "Should have tried different operation types"
        
        print(f"Fuzz session completed successfully:")
        print(f"  Operations: {results['total_operations']}")
        print(f"  Success rate: {results['successful_operations']/results['total_operations']*100:.1f}%")
        print(f"  Operations by type: {results['operations_by_type']}")
    
    def test_fuzz_with_different_policies(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test fuzz testing with different policies."""
        policies = ["ff", "mfs", "lfs"]
        
        for policy in policies:
            print(f"Testing fuzz with policy: {policy}")
            
            config = FuseConfig(policy=policy, branches=temp_branches, mountpoint=temp_mountpoint)
            fuzz_tester = FuzzTester(fuse_manager, config, seed=54321)
            
            results = fuzz_tester.run_fuzz_session(num_operations=15, check_invariants_every=5)
            
            # Verify the session completed without major issues
            assert len(results['invariant_violations']) == 0, f"Policy {policy} had invariant violations: {results['invariant_violations']}"
            assert results['successful_operations'] > 0, f"Policy {policy} should have some successful operations"
            
            print(f"  {policy} policy: {results['successful_operations']}/{results['total_operations']} operations successful")
    
    @pytest.mark.slow
    def test_extended_fuzz_session(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test an extended fuzz session with more operations."""
        config = FuseConfig(policy="mfs", branches=temp_branches, mountpoint=temp_mountpoint)
        
        # Pre-populate branches with different amounts of data to make MFS interesting
        fs_state = FileSystemState()
        fs_state.create_file_with_size(temp_branches[0] / "existing_0.dat", 1000)
        fs_state.create_file_with_size(temp_branches[1] / "existing_1.dat", 5000)
        fs_state.create_file_with_size(temp_branches[2] / "existing_2.dat", 2000)
        
        fuzz_tester = FuzzTester(fuse_manager, config, seed=98765)
        
        # Run a longer fuzz session
        results = fuzz_tester.run_fuzz_session(num_operations=100, check_invariants_every=10)
        
        # Verify extended session completed successfully
        assert len(results['invariant_violations']) == 0, f"Extended session had invariant violations: {results['invariant_violations']}"
        assert results['successful_operations'] > results['total_operations'] * 0.7, "Should have >70% success rate"
        
        # Should have exercised all major operation types
        assert 'create_file' in results['operations_by_type'], "Should have created files"
        assert 'read_file' in results['operations_by_type'], "Should have read files"
        
        print(f"Extended fuzz session results:")
        print(f"  Total operations: {results['total_operations']}")
        print(f"  Success rate: {results['successful_operations']/results['total_operations']*100:.1f}%")
        print(f"  Duration: {results['end_time'] - results['start_time']:.2f}s")
        print(f"  Operations/second: {results['total_operations']/(results['end_time'] - results['start_time']):.1f}")
        print(f"  Error summary: {len(set(results['errors']))} unique error types")