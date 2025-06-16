#!/usr/bin/env python3
"""Benchmark script to compare test execution times with sleep vs trace-based waiting."""

import time
import subprocess
import sys
from pathlib import Path


def run_test_and_measure(test_file: str, test_name: str) -> float:
    """Run a test and measure execution time."""
    start_time = time.time()
    
    result = subprocess.run(
        ["uv", "run", "pytest", test_file, "-v", "-k", test_name],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    
    elapsed = time.time() - start_time
    
    if result.returncode != 0:
        print(f"Test failed: {test_name}")
        print(result.stdout)
        print(result.stderr)
        return -1
    
    return elapsed


def main():
    """Compare execution times of sleep-based vs trace-based tests."""
    
    # Test pairs to compare
    test_comparisons = [
        {
            "name": "Runtime Config - Control File",
            "sleep": ("test_runtime_config.py", "test_control_file_exists"),
            "trace": ("test_runtime_config_trace.py", "test_control_file_exists")
        },
        {
            "name": "Runtime Config - Set Boolean",
            "sleep": ("test_runtime_config.py", "test_set_boolean_configuration"),
            "trace": ("test_runtime_config_trace.py", "test_set_boolean_configuration")
        },
        {
            "name": "MFS Policy - Select Empty Branch",
            "sleep": ("tests/test_mfs_policy.py", "test_mfs_selects_empty_branch_over_populated"),
            "trace": ("tests/test_mfs_policy_trace.py", "test_mfs_selects_empty_branch_over_populated")
        },
        {
            "name": "MFS Policy - File Deletion",
            "sleep": ("tests/test_mfs_policy.py", "test_mfs_with_file_deletion_and_recreation"),
            "trace": ("tests/test_mfs_policy_trace.py", "test_mfs_with_file_deletion_and_recreation")
        }
    ]
    
    print("Benchmarking sleep-based vs trace-based test execution times\n")
    print("=" * 70)
    
    total_sleep_time = 0
    total_trace_time = 0
    
    for comparison in test_comparisons:
        print(f"\nTest: {comparison['name']}")
        print("-" * 50)
        
        # Run sleep-based test
        sleep_file, sleep_test = comparison["sleep"]
        print(f"Running sleep-based test: {sleep_test}...", end="", flush=True)
        sleep_time = run_test_and_measure(sleep_file, sleep_test)
        
        if sleep_time < 0:
            print(" FAILED")
            continue
        print(f" {sleep_time:.2f}s")
        
        # Run trace-based test
        trace_file, trace_test = comparison["trace"]
        print(f"Running trace-based test: {trace_test}...", end="", flush=True)
        trace_time = run_test_and_measure(trace_file, trace_test)
        
        if trace_time < 0:
            print(" FAILED")
            continue
        print(f" {trace_time:.2f}s")
        
        # Calculate improvement
        improvement = ((sleep_time - trace_time) / sleep_time) * 100
        print(f"Improvement: {improvement:.1f}% faster")
        
        total_sleep_time += sleep_time
        total_trace_time += trace_time
    
    print("\n" + "=" * 70)
    print("\nSummary:")
    print(f"Total sleep-based time: {total_sleep_time:.2f}s")
    print(f"Total trace-based time: {total_trace_time:.2f}s")
    print(f"Overall improvement: {((total_sleep_time - total_trace_time) / total_sleep_time) * 100:.1f}% faster")


if __name__ == "__main__":
    main()