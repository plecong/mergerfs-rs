"""
Concurrent access tests for mergerfs-rs with trace-based waiting.

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
from lib.simple_trace import SimpleTraceMonitor, SimpleWaitHelper


@pytest.mark.concurrent
@pytest.mark.integration
class TestConcurrentFileOperationsWithTrace:
    """Test concurrent file operations with trace-based waiting."""
    
    def test_concurrent_file_creation_same_policy(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test that concurrent file creation with same policy works correctly."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def create_files_worker(worker_id: int, mountpoint: Path, num_files: int, wait_helper: SimpleWaitHelper) -> List[str]:
            """Worker function to create files concurrently."""
            created_files = []
            for i in range(num_files):
                filename = f"worker_{worker_id}_file_{i}.txt"
                file_path = mountpoint / filename
                content = f"Content from worker {worker_id}, file {i}"
                
                try:
                    file_path.write_text(content)
                    # Wait for file to be visible using trace monitoring
                    if wait_helper:
                        wait_helper.wait_for_file_visible(file_path, timeout=1.0)
                    created_files.append(filename)
                except Exception as e:
                    print(f"Worker {worker_id} failed to create {filename}: {e}")
                    
            return created_files
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            num_workers = 4
            files_per_worker = 10
            
            # Create files concurrently using threads
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for worker_id in range(num_workers):
                    future = executor.submit(create_files_worker, worker_id, mountpoint, files_per_worker, wait_helper)
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
            
            trace_monitor.stop_capture()
    
    def test_concurrent_read_write_operations(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path
    ):
        """Test concurrent read and write operations on the same files."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            # Create initial files
            num_files = 5
            for i in range(num_files):
                file_path = mountpoint / f"concurrent_rw_{i}.txt"
                file_path.write_text(f"Initial content {i}")
                assert wait_helper.wait_for_file_visible(file_path), f"File {i} not visible"
            
            # Define worker functions
            def reader_worker(file_idx: int, mountpoint: Path, num_reads: int) -> List[str]:
                """Read a file multiple times."""
                file_path = mountpoint / f"concurrent_rw_{file_idx}.txt"
                contents = []
                for _ in range(num_reads):
                    try:
                        content = file_path.read_text()
                        contents.append(content)
                    except Exception as e:
                        print(f"Reader failed for file {file_idx}: {e}")
                return contents
            
            def writer_worker(file_idx: int, mountpoint: Path, num_writes: int, wait_helper: SimpleWaitHelper) -> int:
                """Write to a file multiple times."""
                file_path = mountpoint / f"concurrent_rw_{file_idx}.txt"
                successful_writes = 0
                for write_num in range(num_writes):
                    try:
                        new_content = f"Updated content {file_idx} - write {write_num}"
                        file_path.write_text(new_content)
                        if wait_helper:
                            wait_helper.wait_for_write_complete(file_path, timeout=1.0)
                        successful_writes += 1
                    except Exception as e:
                        print(f"Writer failed for file {file_idx}, write {write_num}: {e}")
                return successful_writes
            
            # Run concurrent readers and writers
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = []
                
                # Submit readers
                for i in range(num_files):
                    for _ in range(2):  # 2 readers per file
                        future = executor.submit(reader_worker, i, mountpoint, 20)
                        futures.append(('reader', i, future))
                
                # Submit writers
                for i in range(num_files):
                    future = executor.submit(writer_worker, i, mountpoint, 10, wait_helper)
                    futures.append(('writer', i, future))
                
                # Collect results
                reader_results = {}
                writer_results = {}
                
                for worker_type, file_idx, future in futures:
                    result = future.result()
                    if worker_type == 'reader':
                        if file_idx not in reader_results:
                            reader_results[file_idx] = []
                        reader_results[file_idx].extend(result)
                    else:
                        writer_results[file_idx] = result
            
            # Verify results
            for i in range(num_files):
                # All writes should have succeeded
                assert writer_results[i] == 10, f"File {i}: Expected 10 successful writes, got {writer_results[i]}"
                
                # Readers should have read valid content
                assert len(reader_results[i]) > 0, f"File {i}: No successful reads"
                
                # Final file should have valid content
                final_content = (mountpoint / f"concurrent_rw_{i}.txt").read_text()
                assert "content" in final_content.lower(), f"File {i}: Invalid final content"
            
            trace_monitor.stop_capture()
    
    def test_concurrent_directory_operations(
        self,
        fuse_manager: FuseManager,
        temp_branches: List[Path],
        temp_mountpoint: Path,
        fs_state: FileSystemState
    ):
        """Test concurrent directory creation and file operations within them."""
        config = FuseConfig(policy="ff", branches=temp_branches, mountpoint=temp_mountpoint)
        
        def directory_worker(worker_id: int, mountpoint: Path, wait_helper: SimpleWaitHelper) -> Dict[str, Any]:
            """Create directory and files within it."""
            dir_name = f"worker_dir_{worker_id}"
            dir_path = mountpoint / dir_name
            
            results = {
                'dir_created': False,
                'files_created': 0,
                'errors': []
            }
            
            try:
                # Create directory
                dir_path.mkdir(exist_ok=True)
                if wait_helper:
                    wait_helper.wait_for_dir_visible(dir_path, timeout=1.0)
                results['dir_created'] = True
                
                # Create files in directory
                for i in range(5):
                    file_path = dir_path / f"file_{i}.txt"
                    file_path.write_text(f"Worker {worker_id} file {i}")
                    if wait_helper:
                        wait_helper.wait_for_file_visible(file_path, timeout=1.0)
                    results['files_created'] += 1
                    
            except Exception as e:
                results['errors'].append(str(e))
                
            return results
        
        with fuse_manager.mounted_fs(config) as (process, mountpoint, branches):
            # Setup trace monitoring
            trace_monitor = SimpleTraceMonitor(process)
            trace_monitor.start_capture()
            wait_helper = SimpleWaitHelper(trace_monitor)
            
            # Wait for mount to be ready
            assert trace_monitor.wait_for_mount_ready(timeout=10.0), "Mount did not become ready"
            
            num_workers = 4
            
            # Run workers concurrently
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for worker_id in range(num_workers):
                    future = executor.submit(directory_worker, worker_id, mountpoint, wait_helper)
                    futures.append(future)
                
                # Collect results
                all_results = []
                for future in as_completed(futures):
                    result = future.result()
                    all_results.append(result)
            
            # Verify results
            for i, result in enumerate(all_results):
                assert result['dir_created'], f"Worker {i} failed to create directory"
                assert result['files_created'] == 5, f"Worker {i} created {result['files_created']} files, expected 5"
                assert len(result['errors']) == 0, f"Worker {i} had errors: {result['errors']}"
            
            # Verify all directories and files exist
            for worker_id in range(num_workers):
                dir_path = mountpoint / f"worker_dir_{worker_id}"
                assert dir_path.is_dir(), f"Directory worker_dir_{worker_id} should exist"
                
                # Check files in directory
                for i in range(5):
                    file_path = dir_path / f"file_{i}.txt"
                    assert file_path.exists(), f"File {file_path} should exist"
                    content = file_path.read_text()
                    assert content == f"Worker {worker_id} file {i}", f"File {file_path} has incorrect content"
            
            trace_monitor.stop_capture()