#!/usr/bin/env python3
"""Test to understand the log format."""

import re

# Sample log lines from the output
sample_logs = """
[2m2025-06-16T16:06:48.773386Z[0m [32m INFO[0m ThreadId(01) [2mmergerfs_rs[0m[2m:[0m [2msrc/main.rs[0m[2m:[0m[2m161:[0m Starting mergerfs-rs mount [3mmountpoint[0m[2m=[0m/tmp/trace_test_mount__8ivgx2s [3mbranches[0m[2m=[0m["/tmp/trace_test_branch1_cis9pout", "/tmp/trace_test_branch2_4mqefxql"] [3mpolicy[0m[2m=[0mff
[2m2025-06-16T16:06:48.773406Z[0m [32m INFO[0m ThreadId(01) [2mfuser::session[0m[2m:[0m [2m/home/plecong/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/fuser-0.14.0/src/session.rs[0m[2m:[0m[2m73:[0m Mounting /tmp/trace_test_mount__8ivgx2s    
[2m2025-06-16T16:06:48.773410Z[0m [33m WARN[0m ThreadId(01) [2mfuser::session[0m[2m:[0m [2m/home/plecong/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/fuser-0.14.0/src/session.rs[0m[2m:[0m[2m81:[0m Given auto_unmount without allow_root or allow_other; adding allow_other, with userspace permission handling    
[2m2025-06-16T16:06:48.774508Z[0m [34mDEBUG[0m ThreadId(01)
""".strip()

# Clean ANSI escape codes - match the actual format
# [2m, [0m, [32m, etc.
ansi_escape = re.compile(r'\[\d+m')

for line in sample_logs.split('\n'):
    clean_line = ansi_escape.sub('', line)
    print(f"Original: {line[:80]}...")
    print(f"Clean:    {clean_line}")
    
    # Test patterns
    timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)')
    level_pattern = re.compile(r'\s+(INFO|WARN|DEBUG|TRACE|ERROR)\s+')
    thread_pattern = re.compile(r'ThreadId\((\d+)\)')
    module_pattern = re.compile(r'\s+(\w+::\w+)')
    
    ts_match = timestamp_pattern.search(clean_line)
    level_match = level_pattern.search(clean_line)
    thread_match = thread_pattern.search(clean_line)
    module_match = module_pattern.search(clean_line)
    
    print(f"  Timestamp: {ts_match.group(1) if ts_match else 'NOT FOUND'}")
    print(f"  Level:     {level_match.group(1) if level_match else 'NOT FOUND'}")
    print(f"  Thread:    {thread_match.group(1) if thread_match else 'NOT FOUND'}")
    print(f"  Module:    {module_match.group(1) if module_match else 'NOT FOUND'}")
    print()