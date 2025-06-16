#!/usr/bin/env python3
"""
Diagnostic test to measure and compare timing approaches.

This test clearly shows the benefit of trace-based waiting over hardcoded sleeps.
"""

import time
import pytest
from pathlib import Path
from lib.simple_trace import SimpleWaitHelper


@pytest.mark.integration
class TestTimingDiagnostics:
    """Diagnostic tests for timing improvements."""
    
    def test_file_operations_timing(self, mounted_fs_with_trace):
        """Measure actual file operation timings."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        wait_helper = SimpleWaitHelper(trace_monitor)
        
        print("\n=== File Operation Timing Analysis ===")
        
        # Test 1: File creation
        test_file = mountpoint / "timing_test.txt"
        start = time.time()
        test_file.write_text("test content")
        write_time = time.time() - start
        
        # Wait for visibility
        start = time.time()
        assert wait_helper.wait_for_file_visible(test_file)
        wait_time = time.time() - start
        
        print(f"File write took: {write_time:.3f}s")
        print(f"Wait for visibility took: {wait_time:.3f}s")
        print(f"Total time: {write_time + wait_time:.3f}s")
        print(f"Traditional approach would use: 0.500s (fixed sleep)")
        print(f"Savings: {0.5 - (write_time + wait_time):.3f}s ({((0.5 - (write_time + wait_time)) / 0.5 * 100):.1f}%)")
        
        # Test 2: Directory creation
        print("\n--- Directory Creation ---")
        test_dir = mountpoint / "timing_dir"
        start = time.time()
        test_dir.mkdir()
        mkdir_time = time.time() - start
        
        start = time.time()
        assert wait_helper.wait_for_dir_visible(test_dir)
        wait_time = time.time() - start
        
        print(f"Directory creation took: {mkdir_time:.3f}s")
        print(f"Wait for visibility took: {wait_time:.3f}s")
        print(f"Total time: {mkdir_time + wait_time:.3f}s")
        print(f"Traditional approach would use: 0.500s (fixed sleep)")
        
        # Test 3: Multiple operations
        print("\n--- Batch Operations ---")
        start = time.time()
        files = []
        for i in range(10):
            f = mountpoint / f"batch_{i}.txt"
            f.write_text(f"content {i}")
            files.append(f)
            
        # Wait for all files
        for f in files:
            assert wait_helper.wait_for_file_visible(f)
            
        batch_time = time.time() - start
        print(f"Created and verified 10 files in: {batch_time:.3f}s")
        print(f"Traditional approach would use: {10 * 0.5:.1f}s (0.5s per file)")
        print(f"Savings: {(10 * 0.5) - batch_time:.3f}s ({((10 * 0.5 - batch_time) / (10 * 0.5) * 100):.1f}%)")
        
    def test_sleep_vs_smart_wait_comparison(self, mounted_fs_with_trace):
        """Direct comparison of sleep vs smart wait."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        wait_helper = SimpleWaitHelper(trace_monitor)
        
        print("\n=== Sleep vs Smart Wait Comparison ===")
        
        # Method 1: Traditional sleep
        print("\nMethod 1: Traditional Sleep")
        file1 = mountpoint / "sleep_test.txt"
        start = time.time()
        file1.write_text("content")
        time.sleep(0.5)  # Traditional approach
        assert file1.exists()
        sleep_time = time.time() - start
        print(f"Time taken: {sleep_time:.3f}s")
        
        # Method 2: Smart wait
        print("\nMethod 2: Smart Wait")
        file2 = mountpoint / "smart_test.txt"
        start = time.time()
        file2.write_text("content")
        assert wait_helper.wait_for_file_visible(file2)
        smart_time = time.time() - start
        print(f"Time taken: {smart_time:.3f}s")
        
        # Summary
        print(f"\nImprovement: {sleep_time - smart_time:.3f}s saved ({((sleep_time - smart_time) / sleep_time * 100):.1f}% faster)")
        print(f"Smart wait is {sleep_time / smart_time:.1f}x faster than sleep")
        
    def test_operation_patterns(self, mounted_fs_with_trace):
        """Analyze common operation patterns."""
        process, mountpoint, branches, trace_monitor = mounted_fs_with_trace
        wait_helper = SimpleWaitHelper(trace_monitor)
        
        print("\n=== Common Operation Patterns ===")
        
        # Pattern 1: Write and read
        print("\nPattern 1: Write and Read")
        file_path = mountpoint / "pattern1.txt"
        start = time.time()
        
        file_path.write_text("test data")
        assert wait_helper.wait_for_file_visible(file_path)
        content = file_path.read_text()
        assert content == "test data"
        
        pattern1_time = time.time() - start
        print(f"Write-wait-read took: {pattern1_time:.3f}s")
        
        # Pattern 2: Create, modify, delete
        print("\nPattern 2: Create, Modify, Delete")
        file_path = mountpoint / "pattern2.txt"
        start = time.time()
        
        file_path.write_text("initial")
        assert wait_helper.wait_for_file_visible(file_path)
        
        file_path.write_text("modified")
        assert wait_helper.wait_for_write_complete(file_path)
        
        file_path.unlink()
        assert wait_helper.wait_for_deletion(file_path)
        
        pattern2_time = time.time() - start
        print(f"Create-modify-delete took: {pattern2_time:.3f}s")
        print(f"Traditional approach would use: 1.5s (3 x 0.5s sleeps)")
        
        # Show trace log patterns if available
        if trace_monitor:
            print("\n--- Recent FUSE Operations ---")
            recent_logs = trace_monitor.get_recent_logs(20)
            for log in recent_logs[-10:]:  # Last 10 operations
                if any(op in log for op in ['create', 'write', 'unlink', 'lookup']):
                    print(f"  {log.strip()}")