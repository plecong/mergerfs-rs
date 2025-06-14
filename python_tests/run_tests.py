#!/usr/bin/env python3
"""
Test runner for mergerfs-rs Python tests.

This script provides convenient ways to run different types of tests
and manages the FUSE binary compilation if needed.
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path


def find_project_root() -> Path:
    """Find the project root directory."""
    current = Path(__file__).parent
    while current.parent != current:
        if (current / "Cargo.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root (no Cargo.toml found)")


def ensure_binary_exists() -> bool:
    """Ensure the mergerfs-rs binary is built."""
    project_root = find_project_root()
    
    # Check if binary exists
    release_path = project_root / "target" / "release" / "mergerfs-rs"
    debug_path = project_root / "target" / "debug" / "mergerfs-rs"
    
    if release_path.exists() or debug_path.exists():
        return True
    
    print("mergerfs-rs binary not found. Building...")
    
    try:
        # Try to build the binary
        result = subprocess.run(
            ["cargo", "build"],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("Build successful!")
            return True
        else:
            print(f"Build failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("Error: cargo not found. Please install Rust and Cargo.")
        return False


def run_pytest(args: list) -> int:
    """Run pytest with the given arguments."""
    # Try to use uv if available, fall back to python
    try:
        # Check if uv is available
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        pytest_cmd = ["uv", "run", "pytest"] + args
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to regular python
        pytest_cmd = ["python3", "-m", "pytest"] + args
    
    print(f"Running: {' '.join(pytest_cmd)}")
    result = subprocess.run(pytest_cmd)
    return result.returncode


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Run mergerfs-rs Python tests")
    parser.add_argument(
        "--test-type", 
        choices=["all", "unit", "integration", "policy", "property", "concurrent", "fuzz", "stress", "quick", "full"],
        default="all",
        help="Type of tests to run (quick excludes slow tests, full includes everything)"
    )
    parser.add_argument(
        "--policy",
        choices=["ff", "mfs", "lfs", "rand"],
        help="Test specific policy only"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--parallel", "-n",
        type=int,
        help="Number of parallel test processes (requires pytest-xdist)"
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Force rebuild of mergerfs-rs binary"
    )
    parser.add_argument(
        "--no-build-check",
        action="store_true",
        help="Skip checking if binary exists"
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Additional arguments to pass to pytest"
    )
    
    args = parser.parse_args()
    
    # Change to the python_tests directory
    os.chdir(Path(__file__).parent)
    
    # Ensure binary is built unless skipped
    if not args.no_build_check:
        if args.build:
            # Force rebuild
            project_root = find_project_root()
            print("Force rebuilding mergerfs-rs...")
            result = subprocess.run(["cargo", "build"], cwd=project_root)
            if result.returncode != 0:
                print("Build failed!")
                return 1
        elif not ensure_binary_exists():
            print("Failed to ensure binary exists!")
            return 1
    
    # Build pytest arguments
    pytest_args = []
    
    # Add test type marker
    if args.test_type == "quick":
        # Quick tests exclude slow property-based and fuzz tests
        pytest_args.extend(["-m", "not slow and not property and not fuzz"])
    elif args.test_type == "full":
        # Full tests include everything but with extended timeouts
        pytest_args.extend(["-c", "pytest-full.ini"])
    elif args.test_type != "all":
        pytest_args.extend(["-m", args.test_type])
    
    # Add verbose flag
    if args.verbose:
        pytest_args.append("-v")
    
    # Add parallel execution
    if args.parallel:
        pytest_args.extend(["-n", str(args.parallel)])
    
    # Add policy filter if specified
    if args.policy:
        pytest_args.extend(["-k", f"policy or {args.policy}"])
    
    # Add any additional pytest arguments
    pytest_args.extend(args.pytest_args)
    
    # Run the tests
    return run_pytest(pytest_args)


def quick_test():
    """Run a quick test to verify the setup works."""
    print("Running quick verification test...")
    
    if not ensure_binary_exists():
        return 1
    
    # Run just the basic policy tests
    return run_pytest([
        "-v",
        "-m", "policy",
        "-k", "test_firstfound_policy_basic",
        "--tb=short"
    ])


def run_quick_suite():
    """Run quick test suite excluding slow tests."""
    print("Running quick test suite (excluding slow property-based and fuzz tests)...")
    
    if not ensure_binary_exists():
        return 1
    
    return run_pytest([
        "-v",
        "-m", "not slow and not property and not fuzz",
        "--tb=short"
    ])


def run_full_suite():
    """Run full test suite with extended timeouts."""
    print("Running full test suite (including all slow tests)...")
    
    if not ensure_binary_exists():
        return 1
    
    return run_pytest([
        "-v",
        "-c", "pytest-full.ini",
        "--tb=short"
    ])


def run_all_tests():
    """Run all tests in order of increasing complexity."""
    print("Running complete test suite...")
    
    if not ensure_binary_exists():
        return 1
    
    test_suites = [
        ("Basic Policy Tests", ["-m", "policy", "-k", "TestCreatePolicies"]),
        ("Union Behavior Tests", ["-m", "integration", "-k", "TestUnionBehavior"]),
        ("Directory Operations", ["-m", "integration", "-k", "TestDirectoryOperations"]),
        ("Property-based Tests", ["-m", "property", "--tb=line"]),
        ("Concurrent Access Tests", ["-m", "concurrent", "--tb=line"]),
        ("Fuzz Foundation Tests", ["-m", "fuzz", "--tb=line"]),
    ]
    
    for suite_name, suite_args in test_suites:
        print(f"\n{'='*60}")
        print(f"Running {suite_name}")
        print(f"{'='*60}")
        
        result = run_pytest(["-v"] + suite_args)
        if result != 0:
            print(f"\n❌ {suite_name} failed!")
            return result
        else:
            print(f"\n✅ {suite_name} passed!")
    
    print(f"\n{'='*60}")
    print("🎉 All test suites completed successfully!")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        sys.exit(run_quick_suite())
    elif len(sys.argv) > 1 and sys.argv[1] == "full":
        sys.exit(run_full_suite())
    elif len(sys.argv) > 1 and sys.argv[1] == "all":
        sys.exit(run_all_tests())
    else:
        sys.exit(main())