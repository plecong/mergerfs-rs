"""
Timing analysis utilities for FUSE testing.

This module provides tools to analyze FUSE operation timing from logs
and help diagnose performance issues in tests.
"""

import re
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
import subprocess
import threading
import queue


@dataclass
class OperationTiming:
    """Record of a FUSE operation timing."""
    operation: str
    start_time: float
    end_time: Optional[float]
    duration_ms: Optional[float]
    path: Optional[str]
    thread_id: Optional[str]
    details: Dict[str, Any]


class FuseLogCapture:
    """Captures FUSE debug logs from the mergerfs-rs process."""
    
    def __init__(self, process: subprocess.Popen):
        """Initialize log capture for a FUSE process.
        
        Args:
            process: The FUSE subprocess to capture logs from
        """
        self.process = process
        self.log_lines = []
        self.operation_timings = []
        self.capture_thread = None
        self.stop_capture = threading.Event()
        self.log_queue = queue.Queue()
        
    def start_capture(self):
        """Start capturing logs from the process stderr."""
        self.capture_thread = threading.Thread(target=self._capture_logs)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        
    def stop_capture(self):
        """Stop capturing logs."""
        self.stop_capture.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)
            
    def _capture_logs(self):
        """Background thread to capture logs."""
        try:
            for line in iter(self.process.stderr.readline, ''):
                if self.stop_capture.is_set():
                    break
                if line:
                    self.log_queue.put(line.strip())
        except Exception as e:
            print(f"Error capturing logs: {e}")
            
    def get_logs(self) -> List[str]:
        """Get all captured log lines."""
        # Drain the queue
        while not self.log_queue.empty():
            try:
                self.log_lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return self.log_lines
        
    def analyze_operations(self) -> List[OperationTiming]:
        """Analyze captured logs for operation timings."""
        operations = {}
        span_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(\w+)\s+.*?fuse::(\w+).*?ThreadId\((\d+)\)'
        
        for line in self.get_logs():
            # Look for span enter/exit
            if 'fuse::' in line:
                match = re.search(span_pattern, line)
                if match:
                    timestamp_str, level, operation, thread_id = match.groups()
                    # Parse timestamp (simplified for now)
                    timestamp = time.time()  # Would parse actual timestamp
                    
                    key = f"{thread_id}:{operation}"
                    
                    if 'enter' in line or 'new' in line:
                        # Start of operation
                        operations[key] = OperationTiming(
                            operation=operation,
                            start_time=timestamp,
                            end_time=None,
                            duration_ms=None,
                            path=None,
                            thread_id=thread_id,
                            details={}
                        )
                    elif 'exit' in line or 'close' in line:
                        # End of operation
                        if key in operations:
                            op = operations[key]
                            op.end_time = timestamp
                            op.duration_ms = (op.end_time - op.start_time) * 1000
                            self.operation_timings.append(op)
                            
        return self.operation_timings


class TimingAnalyzer:
    """Analyzes FUSE operation timings to identify performance issues."""
    
    def __init__(self):
        self.slow_threshold_ms = 100  # Operations slower than this are flagged
        
    def analyze_timings(self, timings: List[OperationTiming]) -> Dict[str, Any]:
        """Analyze operation timings for issues.
        
        Returns:
            Dictionary with analysis results
        """
        if not timings:
            return {
                'total_operations': 0,
                'slow_operations': [],
                'operation_stats': {}
            }
            
        # Group by operation type
        by_operation = defaultdict(list)
        for timing in timings:
            if timing.duration_ms is not None:
                by_operation[timing.operation].append(timing.duration_ms)
                
        # Calculate statistics
        operation_stats = {}
        for op, durations in by_operation.items():
            if durations:
                operation_stats[op] = {
                    'count': len(durations),
                    'min_ms': min(durations),
                    'max_ms': max(durations),
                    'avg_ms': sum(durations) / len(durations),
                    'total_ms': sum(durations)
                }
                
        # Find slow operations
        slow_operations = [
            t for t in timings 
            if t.duration_ms and t.duration_ms > self.slow_threshold_ms
        ]
        
        return {
            'total_operations': len(timings),
            'slow_operations': slow_operations,
            'operation_stats': operation_stats,
            'total_time_ms': sum(t.duration_ms or 0 for t in timings)
        }
        
    def generate_report(self, analysis: Dict[str, Any]) -> str:
        """Generate a human-readable timing report."""
        lines = ["FUSE Operation Timing Report", "=" * 40]
        
        lines.append(f"Total operations: {analysis['total_operations']}")
        lines.append(f"Total time: {analysis['total_time_ms']:.2f}ms")
        lines.append("")
        
        if analysis['operation_stats']:
            lines.append("Operation Statistics:")
            lines.append("-" * 40)
            for op, stats in sorted(analysis['operation_stats'].items()):
                lines.append(f"{op}:")
                lines.append(f"  Count: {stats['count']}")
                lines.append(f"  Avg: {stats['avg_ms']:.2f}ms")
                lines.append(f"  Min: {stats['min_ms']:.2f}ms")
                lines.append(f"  Max: {stats['max_ms']:.2f}ms")
                lines.append("")
                
        if analysis['slow_operations']:
            lines.append(f"Slow Operations (>{self.slow_threshold_ms}ms):")
            lines.append("-" * 40)
            for op in analysis['slow_operations'][:10]:  # Show top 10
                lines.append(f"{op.operation}: {op.duration_ms:.2f}ms")
                
        return "\n".join(lines)


def wait_for_operation(
    check_fn,
    timeout: float = 5.0,
    interval: float = 0.1,
    operation_name: str = "operation"
) -> Tuple[bool, float]:
    """Wait for an operation to complete with detailed timing.
    
    Args:
        check_fn: Function that returns True when operation is complete
        timeout: Maximum time to wait in seconds
        interval: Check interval in seconds
        operation_name: Name of operation for logging
        
    Returns:
        Tuple of (success, elapsed_time)
    """
    start_time = time.time()
    deadline = start_time + timeout
    
    while time.time() < deadline:
        if check_fn():
            elapsed = time.time() - start_time
            if elapsed > 1.0:
                print(f"Note: {operation_name} took {elapsed:.2f}s to complete")
            return True, elapsed
        time.sleep(interval)
        
    elapsed = time.time() - start_time
    print(f"Warning: {operation_name} timed out after {elapsed:.2f}s")
    return False, elapsed


def measure_mount_time(mount_fn) -> float:
    """Measure how long it takes for a mount operation to complete.
    
    Args:
        mount_fn: Function that performs the mount
        
    Returns:
        Time in seconds for mount to be ready
    """
    start_time = time.time()
    mount_fn()
    return time.time() - start_time