#!/usr/bin/env python3
"""
Utility to run pytest with FUSE trace monitoring enabled.

This script sets up the environment for trace monitoring and provides
helpful options for debugging FUSE operations.
"""

import os
import sys
import argparse
import subprocess


def main():
    parser = argparse.ArgumentParser(
        description="Run pytest with FUSE trace monitoring enabled",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tests with trace monitoring
  ./run_with_trace.py
  
  # Run specific test file
  ./run_with_trace.py test_runtime_config.py
  
  # Run with trace summary on unmount
  ./run_with_trace.py --summary test_xattr.py
  
  # Run with full debug output
  ./run_with_trace.py --debug -v test_file_ops.py
  
  # Compare with/without trace
  ./run_with_trace.py --compare test_demo.py
"""
    )
    
    parser.add_argument(
        'tests',
        nargs='*',
        help='Test files or pytest arguments (default: all tests)'
    )
    
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show operation summary on unmount'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable full debug output (RUST_LOG=debug)'
    )
    
    parser.add_argument(
        '--no-trace',
        action='store_true',
        help='Disable trace monitoring (for comparison)'
    )
    
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Run tests twice: with and without trace monitoring'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose pytest output'
    )
    
    parser.add_argument(
        '-s', '--capture=no',
        action='store_true',
        dest='no_capture',
        help='Disable output capture (show prints)'
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    cmd = ['uv', 'run', 'pytest']
    
    # Add verbosity
    if args.verbose:
        cmd.append('-v')
    
    # Disable capture
    if args.no_capture:
        cmd.append('-s')
    
    # Add test files or use defaults
    if args.tests:
        cmd.extend(args.tests)
    else:
        # Default to integration tests that benefit from tracing
        cmd.extend([
            'test_runtime_config*.py',
            'test_xattr.py',
            'test_file_ops.py',
            '-k', 'not test_traditional'  # Skip traditional examples
        ])
    
    # Setup environment
    env = os.environ.copy()
    
    if args.compare:
        print("="*60)
        print("Running tests WITHOUT trace monitoring...")
        print("="*60)
        
        # Run without trace
        env_no_trace = env.copy()
        env_no_trace['FUSE_TRACE'] = '0'
        env_no_trace['RUST_LOG'] = 'info'
        
        result1 = subprocess.run(cmd, env=env_no_trace)
        
        print("\n" + "="*60)
        print("Running tests WITH trace monitoring...")
        print("="*60)
        
        # Run with trace
        env_trace = env.copy()
        env_trace['FUSE_TRACE'] = '1'
        env_trace['RUST_LOG'] = 'trace'
        if args.summary:
            env_trace['FUSE_TRACE_SUMMARY'] = '1'
            
        result2 = subprocess.run(cmd, env=env_trace)
        
        print("\n" + "="*60)
        print("COMPARISON COMPLETE")
        print(f"Without trace: {'PASSED' if result1.returncode == 0 else 'FAILED'}")
        print(f"With trace:    {'PASSED' if result2.returncode == 0 else 'FAILED'}")
        print("="*60)
        
        sys.exit(max(result1.returncode, result2.returncode))
    
    else:
        # Normal run
        if not args.no_trace:
            env['FUSE_TRACE'] = '1'
            env['RUST_LOG'] = 'debug' if args.debug else 'trace'
            
            if args.summary:
                env['FUSE_TRACE_SUMMARY'] = '1'
                
            print("FUSE trace monitoring ENABLED")
            print(f"RUST_LOG={env['RUST_LOG']}")
            if args.summary:
                print("Operation summary ENABLED")
        else:
            env['FUSE_TRACE'] = '0'
            env['RUST_LOG'] = 'info'
            print("FUSE trace monitoring DISABLED")
            
        print(f"Running: {' '.join(cmd)}")
        print("-"*60)
        
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)


if __name__ == '__main__':
    main()