#!/usr/bin/env python3
"""
Run trace-based tests alongside sleep-based tests to demonstrate improvements.
"""

import subprocess
import time
import sys
from pathlib import Path


def run_test(test_file: str, capture_output: bool = False) -> tuple[bool, float, str]:
    """Run a single test file and return success, duration, and output."""
    start_time = time.time()
    
    cmd = ["uv", "run", "pytest", test_file, "-v"]
    
    if capture_output:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        output = result.stdout + result.stderr
    else:
        result = subprocess.run(cmd, cwd=Path(__file__).parent)
        output = ""
    
    duration = time.time() - start_time
    success = result.returncode == 0
    
    return success, duration, output


def main():
    """Run comparison tests."""
    print("=" * 80)
    print("Comparing sleep-based tests with trace-based tests")
    print("=" * 80)
    print()
    
    # Define test pairs
    test_pairs = [
        {
            "name": "Runtime Configuration Tests",
            "sleep": "test_runtime_config.py",
            "trace": "test_runtime_config_trace.py",
        },
        {
            "name": "MFS Policy Tests", 
            "sleep": "tests/test_mfs_policy.py::TestMFSPolicyBasic",
            "trace": "tests/test_mfs_policy_trace.py::TestMFSPolicyBasicWithTrace",
        },
        {
            "name": "Random Policy Tests",
            "sleep": "tests/test_random_policy.py::TestRandomPolicy::test_random_policy_basic",
            "trace": "tests/test_random_policy_trace.py::TestRandomPolicyWithTrace::test_random_policy_basic",
        }
    ]
    
    results = []
    
    for test_pair in test_pairs:
        print(f"\n{test_pair['name']}")
        print("-" * len(test_pair['name']))
        
        # Run sleep-based test
        print(f"\nRunning sleep-based test: {test_pair['sleep']}")
        sleep_success, sleep_duration, _ = run_test(test_pair['sleep'])
        
        if sleep_success:
            print(f"✓ Completed in {sleep_duration:.2f}s")
        else:
            print(f"✗ Failed after {sleep_duration:.2f}s")
        
        # Run trace-based test
        print(f"\nRunning trace-based test: {test_pair['trace']}")
        trace_success, trace_duration, _ = run_test(test_pair['trace'])
        
        if trace_success:
            print(f"✓ Completed in {trace_duration:.2f}s")
        else:
            print(f"✗ Failed after {trace_duration:.2f}s")
        
        # Calculate improvement
        if sleep_success and trace_success:
            improvement = ((sleep_duration - trace_duration) / sleep_duration) * 100
            print(f"\n🚀 Improvement: {improvement:.1f}% faster ({sleep_duration - trace_duration:.2f}s saved)")
            
            results.append({
                "name": test_pair['name'],
                "sleep_time": sleep_duration,
                "trace_time": trace_duration,
                "improvement": improvement
            })
    
    # Summary
    if results:
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print()
        
        total_sleep_time = sum(r["sleep_time"] for r in results)
        total_trace_time = sum(r["trace_time"] for r in results)
        total_improvement = ((total_sleep_time - total_trace_time) / total_sleep_time) * 100
        
        print(f"{'Test':<40} {'Sleep (s)':>10} {'Trace (s)':>10} {'Improvement':>15}")
        print("-" * 80)
        
        for result in results:
            print(f"{result['name']:<40} {result['sleep_time']:>10.2f} {result['trace_time']:>10.2f} {result['improvement']:>14.1f}%")
        
        print("-" * 80)
        print(f"{'TOTAL':<40} {total_sleep_time:>10.2f} {total_trace_time:>10.2f} {total_improvement:>14.1f}%")
        print()
        print(f"⏱️  Total time saved: {total_sleep_time - total_trace_time:.2f} seconds")
        print(f"🚀 Average improvement: {total_improvement:.1f}% faster")


if __name__ == "__main__":
    main()