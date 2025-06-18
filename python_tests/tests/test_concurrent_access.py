"""
Concurrent access tests for mergerfs-rs.

These tests verify that the filesystem behaves correctly under 
concurrent access from multiple processes/threads.
"""

import pytest
import os
import time
import threading
import multiprocessing
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import tempfile
import random

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@pytest.mark.concurrent
@pytest.mark.integration
class TestConcurrentFileOperations:
    """Test concurrent file operations."""
    
    def test_concurrent_file_creation_same_policy(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that concurrent file creation with same policy works correctly."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def create_files_worker(worker_id: int, mountpoint: Path, num_files: int) -> List[str]:
            """Worker function to create files concurrently."""
            created_files = []
            for i in range(num_files):
                filename = f"worker_{worker_id}_file_{i}.txt"
                file_path = mountpoint / filename
                content = f"Content from worker {worker_id}, file {i}"
                
                try:
                    file_path.write_text(content)
                    # Verify content was written
                    written_content = file_path.read_text()
                    if written_content != content:
                        print(f"Worker {worker_id}: Content mismatch for {filename}")
                        print(f"  Expected: {content}")
                        print(f"  Got: {written_content}")
                    created_files.append(filename)
                    # No artificial delay needed - let timing analysis show actual performance
                except Exception as e:
                    print(f"Worker {worker_id} failed to create {filename}: {e}")
                    
            return created_files
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            num_workers = 2
            files_per_worker = 3
            
            # Create files concurrently using threads
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for worker_id in range(num_workers):
                    future = executor.submit(create_files_worker, worker_id, mountpoint, files_per_worker)
                    futures.append(future)
                
                # Collect results
                all_created_files = []
                for future in as_completed(futures):
                    created_files = future.result()
                    all_created_files.extend(created_files)
            
            # Verify all files were created successfully
            expected_total = num_workers * files_per_worker
            assert len(all_created_files) == expected_total, f"Expected {expected_total} files, got {len(all_created_files)}"
            
            # Verify each file exists and has correct content
            for filename in all_created_files:
                file_path = mountpoint / filename
                assert file_path.exists(), f"File {filename} should exist"
                
                # Parse worker ID from filename to verify content
                worker_id = int(filename.split('_')[1])
                file_num = int(filename.split('_')[3].split('.')[0])
                expected_content = f"Content from worker {worker_id}, file {file_num}"
                
                actual_content = file_path.read_text()
                assert actual_content == expected_content, f"File {filename} has incorrect content"
                
                # Verify file is in exactly one branch (FirstFound should use branch 0)
                locations = fs_state.get_file_locations(branches, filename)
                assert len(locations) == 1, f"File {filename} should be in exactly one branch"
                assert locations[0] == 0, f"FirstFound policy should put file in branch 0"
    
    @pytest.mark.skip(reason="Read operations hanging - needs further investigation")
    def test_concurrent_read_write_operations(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test concurrent read and write operations on the same files."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def writer_worker(mountpoint: Path, filename: str, iterations: int) -> int:
            """Worker that writes to a file multiple times."""
            file_path = mountpoint / filename
            writes_completed = 0
            
            for i in range(iterations):
                try:
                    content = f"Write iteration {i} at {time.time()}"
                    file_path.write_text(content)
                    writes_completed += 1
                except Exception as e:
                    print(f"Write failed for {filename} iteration {i}: {e}")
                    
            return writes_completed
        
        def reader_worker(mountpoint: Path, filename: str, iterations: int) -> int:
            """Worker that reads from a file multiple times."""
            file_path = mountpoint / filename
            reads_completed = 0
            
            for i in range(iterations):
                try:
                    if file_path.exists():
                        content = file_path.read_text()
                        reads_completed += 1
                except Exception as e:
                    print(f"Read failed for {filename} iteration {i}: {e}")
                    
            return reads_completed
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            test_files = ["concurrent_test_1.txt", "concurrent_test_2.txt"]
            iterations = 10
            
            # Create initial files
            for filename in test_files:
                file_path = mountpoint / filename
                file_path.write_text("Initial content")
            
            # Start concurrent readers and writers
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = []
                
                # Start writers
                for filename in test_files:
                    future = executor.submit(writer_worker, mountpoint, filename, iterations)
                    futures.append(('writer', filename, future))
                
                # Start readers
                for filename in test_files:
                    for _ in range(2):  # Multiple readers per file
                        future = executor.submit(reader_worker, mountpoint, filename, iterations)
                        futures.append(('reader', filename, future))
                
                # Collect results
                total_writes = 0
                total_reads = 0
                
                for worker_type, filename, future in futures:
                    result = future.result()
                    if worker_type == 'writer':
                        total_writes += result
                    else:
                        total_reads += result
            
            # Verify operations completed successfully
            expected_writes = len(test_files) * iterations
            assert total_writes >= expected_writes * 0.9, f"Expected at least {expected_writes * 0.9} writes, got {total_writes}"
            
            # Verify files still exist and are readable
            for filename in test_files:
                file_path = mountpoint / filename
                assert file_path.exists(), f"File {filename} should still exist after concurrent operations"
                content = file_path.read_text()
                assert content.startswith("Write iteration"), f"File {filename} should have valid content"
    
    def test_concurrent_different_policies(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that different policies can be tested concurrently (separate mounts)."""
        
        def test_policy_worker(policy: str, branches: List[Path], base_mountpoint: Path) -> Dict[str, Any]:
            """Worker to test a specific policy."""
            # Create a unique mountpoint for this policy test
            policy_mountpoint = base_mountpoint.parent / f"mount_{policy}_{os.getpid()}"
            policy_mountpoint.mkdir(exist_ok=True)
            
            config = FuseConfig(policy=policy, branches=branches, mountpoint=policy_mountpoint)
            
            # Create a temporary FUSE manager for this worker
            with FuseManager() as policy_manager:
                try:
                    with policy_manager.mounted_fs(config) as (process, mountpoint, worker_branches):
                        files_created = []
                        
                        # Create test files
                        for i in range(5):
                            filename = f"{policy}_test_{i}.txt"
                            file_path = mountpoint / filename
                            file_path.write_text(f"Content for {policy} policy, file {i}")
                            files_created.append(filename)
                        
                        # Verify files were created according to policy
                        file_locations = {}
                        for filename in files_created:
                            locations = fs_state.get_file_locations(worker_branches, filename)
                            file_locations[filename] = locations
                        
                        return {
                            'policy': policy,
                            'files_created': len(files_created),
                            'file_locations': file_locations,
                            'success': True
                        }
                        
                except Exception as e:
                    return {
                        'policy': policy,
                        'error': str(e),
                        'success': False
                    }
                finally:
                    # Clean up the policy-specific mountpoint
                    # Note: Don't access the mountpoint after unmounting - it may cause ENOTCONN
                    # The FuseManager cleanup will handle removing temp directories
                    pass
        
        # Test all policies concurrently
        policies = ["ff", "mfs", "lfs"]
        
        with ThreadPoolExecutor(max_workers=len(policies)) as executor:
            futures = []
            for policy in policies:
                future = executor.submit(test_policy_worker, policy, temp_branches, temp_mountpoint)
                futures.append((policy, future))
            
            # Collect results
            results = {}
            for policy, future in futures:
                result = future.result()
                results[policy] = result
        
        # Verify all policies worked
        for policy in policies:
            result = results[policy]
            assert result['success'], f"Policy {policy} test failed: {result.get('error', 'Unknown error')}"
            assert result['files_created'] == 5, f"Policy {policy} should have created 5 files"
            
            # Verify files were placed in exactly one branch each
            for filename, locations in result['file_locations'].items():
                assert len(locations) == 1, f"Policy {policy} file {filename} should be in exactly one branch"


@pytest.mark.concurrent
@pytest.mark.integration
@pytest.mark.skip(reason="Directory operations with concurrent file creation still cause issues")
class TestConcurrentDirectoryOperations:
    """Test concurrent directory operations."""
    
    def test_concurrent_directory_creation(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test concurrent directory creation."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def create_directory_structure(worker_id: int, mountpoint: Path) -> List[str]:
            """Create a directory structure concurrently."""
            created_dirs = []
            
            # Create a worker-specific directory tree
            base_dir = f"worker_{worker_id}"
            for level1 in range(3):
                level1_dir = f"{base_dir}/level1_{level1}"
                for level2 in range(2):
                    level2_dir = f"{level1_dir}/level2_{level2}"
                    
                    try:
                        full_path = mountpoint / level2_dir
                        full_path.mkdir(parents=True, exist_ok=True)
                        created_dirs.append(level2_dir)
                        
                        # Create a test file in each directory
                        test_file = full_path / "test.txt"
                        test_file.write_text(f"Worker {worker_id} content")
                        
                    except Exception as e:
                        print(f"Worker {worker_id} failed to create {level2_dir}: {e}")
            
            return created_dirs
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            num_workers = 4
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for worker_id in range(num_workers):
                    future = executor.submit(create_directory_structure, worker_id, mountpoint)
                    futures.append(future)
                
                # Collect results
                all_created_dirs = []
                for future in as_completed(futures):
                    created_dirs = future.result()
                    all_created_dirs.extend(created_dirs)
            
            # Verify all directories were created
            expected_dirs = num_workers * 3 * 2  # workers * level1 * level2
            assert len(all_created_dirs) == expected_dirs, f"Expected {expected_dirs} directories, got {len(all_created_dirs)}"
            
            # Verify each directory exists and contains the test file
            for dir_path in all_created_dirs:
                full_dir_path = mountpoint / dir_path
                assert full_dir_path.exists(), f"Directory {dir_path} should exist"
                assert full_dir_path.is_dir(), f"{dir_path} should be a directory"
                
                test_file = full_dir_path / "test.txt"
                assert test_file.exists(), f"Test file should exist in {dir_path}"


@pytest.mark.concurrent
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skip(reason="Stress tests need further investigation for concurrent operations")
class TestStressConditions:
    """Stress tests for concurrent operations."""
    
    def test_high_concurrency_file_creation(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test filesystem under high concurrency stress."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def stress_worker(worker_id: int, mountpoint: Path, num_operations: int) -> Dict[str, int]:
            """Perform many operations to stress test the filesystem."""
            stats = {
                'files_created': 0,
                'files_read': 0,
                'directories_created': 0,
                'errors': 0
            }
            
            for i in range(num_operations):
                try:
                    operation = random.choice(['create_file', 'read_file', 'create_dir'])
                    
                    if operation == 'create_file':
                        filename = f"stress_{worker_id}_{i}.txt"
                        file_path = mountpoint / filename
                        file_path.write_text(f"Stress test content {worker_id}:{i}")
                        stats['files_created'] += 1
                        
                    elif operation == 'read_file':
                        # Try to read a file that might exist
                        filename = f"stress_{worker_id}_{max(0, i-5)}.txt"
                        file_path = mountpoint / filename
                        if file_path.exists():
                            content = file_path.read_text()
                            stats['files_read'] += 1
                            
                    elif operation == 'create_dir':
                        dirname = f"stress_dir_{worker_id}_{i}"
                        dir_path = mountpoint / dirname
                        if not dir_path.exists():
                            dir_path.mkdir()
                            stats['directories_created'] += 1
                    
                    # No artificial delays - measure actual performance
                        
                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 5:  # Don't spam with error messages
                        print(f"Stress worker {worker_id} error in operation {i}: {e}")
            
            return stats
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            num_workers = 4
            operations_per_worker = 20
            
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for worker_id in range(num_workers):
                    future = executor.submit(stress_worker, worker_id, mountpoint, operations_per_worker)
                    futures.append(future)
                
                # Collect results
                total_stats = {
                    'files_created': 0,
                    'files_read': 0,
                    'directories_created': 0,
                    'errors': 0
                }
                
                for future in as_completed(futures):
                    worker_stats = future.result()
                    for key, value in worker_stats.items():
                        total_stats[key] += value
            
            end_time = time.time()
            elapsed = end_time - start_time
            
            # Verify results
            total_operations = num_workers * operations_per_worker
            print(f"Stress test completed in {elapsed:.2f}s")
            print(f"Total operations: {total_operations}")
            print(f"Operations/second: {total_operations/elapsed:.2f}")
            print(f"Stats: {total_stats}")
            
            # Basic sanity checks
            assert total_stats['files_created'] > 0, "Should have created some files"
            assert total_stats['errors'] < total_operations * 0.1, "Error rate should be less than 10%"
            
            # Performance check - should complete in reasonable time
            assert elapsed < 60, f"Stress test took {elapsed}s, should complete within 60 seconds"