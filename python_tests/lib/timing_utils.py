"""
Timing analysis utilities for FUSE testing.

This module provides tools to analyze FUSE operation timing from logs
and help diagnose performance issues in tests.
"""

import re
import time
from typing import List, Dict, Any, Optional, Tuple, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import subprocess
import threading
import queue
import json
from enum import Enum
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class OperationStatus(Enum):
    """Status of a FUSE operation."""
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    

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
    status: OperationStatus = OperationStatus.STARTED
    error: Optional[str] = None
    span_id: Optional[str] = None


@dataclass
class FuseOperation:
    """Represents a single FUSE operation tracked through logs."""
    operation: str
    thread_id: str
    timestamp: float
    path: Optional[str] = None
    parent: Optional[int] = None
    name: Optional[str] = None
    ino: Optional[int] = None
    fh: Optional[int] = None
    status: OperationStatus = OperationStatus.STARTED
    error_code: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)
    

class FuseTraceMonitor:
    """Enhanced monitor for FUSE trace logs with real-time operation tracking."""
    
    def __init__(self, process: subprocess.Popen):
        """Initialize trace monitor for a FUSE process.
        
        Args:
            process: The FUSE subprocess to monitor
        """
        self.process = process
        self.log_lines = []
        self.operations: Dict[str, FuseOperation] = {}  # Keyed by thread_id:operation
        self.completed_operations: List[FuseOperation] = []
        self.capture_thread = None
        self.stop_capture = threading.Event()
        self.log_queue = queue.Queue()
        self.operation_events = defaultdict(threading.Event)  # For waiting on specific operations
        self.lock = threading.Lock()
        
        # Regex patterns for parsing structured logs
        self.ansi_escape = re.compile(r'\[\d+m')  # Remove ANSI color codes
        self.patterns = {
            'timestamp': re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)'),
            'log_level': re.compile(r'\s+(INFO|WARN|DEBUG|TRACE|ERROR)\s+'),
            'thread_id': re.compile(r'ThreadId\((\d+)\)'),
            'module': re.compile(r'\s+(\w+::\w+)'),
            'span_new': re.compile(r'new\(fuse::(\w+)\)'),
            'span_enter': re.compile(r'enter.*?fuse::(\w+)'),
            'span_exit': re.compile(r'exit.*?fuse::(\w+)'),
            'span_close': re.compile(r'close.*?fuse::(\w+)'),
            'op_params': re.compile(r'(?:parent=(\d+)|path="([^"]+)"|name="([^"]+)"|ino=(\d+)|fh=(\d+))'),
            'error_reply': re.compile(r'reply\.error\((\d+)\)'),
        }
        
    def start_capture(self):
        """Start capturing and parsing logs from the process."""
        self.capture_thread = threading.Thread(target=self._capture_and_parse_logs)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        logger.debug("Started FUSE trace monitoring")
        
    def stop_capture(self):
        """Stop capturing logs."""
        logger.debug("Stopping FUSE trace monitoring")
        self.stop_capture.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
            
    def _parse_timestamp(self, timestamp_str: str) -> float:
        """Convert ISO timestamp to float seconds since epoch."""
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.timestamp()
        except:
            return time.time()
            
    def _capture_and_parse_logs(self):
        """Background thread to capture and parse logs in real-time."""
        try:
            # Try stdout first (where tracing output typically goes)
            for line in iter(self.process.stdout.readline, ''):
                if self.stop_capture.is_set():
                    break
                if line:
                    line = line.strip()
                    self.log_lines.append(line)
                    self._parse_log_line(line)
        except Exception as e:
            logger.error(f"Error capturing logs: {e}")
            
    def _parse_log_line(self, line: str):
        """Parse a single log line and update operation tracking."""
        try:
            # Clean ANSI codes first
            clean_line = self.ansi_escape.sub('', line)
            
            # Extract basic info from any line
            ts_match = self.patterns['timestamp'].search(clean_line)
            level_match = self.patterns['log_level'].search(clean_line)
            thread_match = self.patterns['thread_id'].search(clean_line)
            
            if not thread_match:
                return  # Need thread ID to track operations
                
            thread_id = thread_match.group(1)
            timestamp = self._parse_timestamp(ts_match.group(1)) if ts_match else time.time()
            
            # Check for span new/enter (operation start)
            for pattern_name in ['span_new', 'span_enter']:
                match = self.patterns[pattern_name].search(clean_line)
                if match:
                    operation = match.group(1)
                    key = f"{thread_id}:{operation}"
                    
                    with self.lock:
                        self.operations[key] = FuseOperation(
                            operation=operation,
                            thread_id=thread_id,
                            timestamp=timestamp
                        )
                        
                    logger.debug(f"Operation started: {operation} (thread {thread_id})")
                    return
                
            # Check for span exit/close (operation complete)
            for pattern_name in ['span_exit', 'span_close']:
                match = self.patterns[pattern_name].search(clean_line)
                if match:
                    operation = match.group(1)
                    key = f"{thread_id}:{operation}"
                    
                    with self.lock:
                        if key in self.operations:
                            op = self.operations.pop(key)
                            op.status = OperationStatus.COMPLETED
                            
                            # Check for error in the line
                            error_match = self.patterns['error_reply'].search(clean_line)
                            if error_match:
                                op.error_code = int(error_match.group(1))
                                op.status = OperationStatus.FAILED
                                
                            self.completed_operations.append(op)
                            
                            # Signal any waiters for this operation
                            event_key = f"{operation}:{op.path or ''}" if op.path else operation
                            if event_key in self.operation_events:
                                self.operation_events[event_key].set()
                                
                    logger.debug(f"Operation completed: {operation} (thread {thread_id})")
                    return
                    
            # Look for FUSE operations in any log line
            if 'fuse::' in clean_line:
                # Try to extract operation name
                module_match = self.patterns['module'].search(clean_line)
                if module_match and module_match.group(1).startswith('fuse::'):
                    operation = module_match.group(1).split('::')[1]
                    key = f"{thread_id}:{operation}"
                    
                    # If we haven't seen this operation start, create it now
                    with self.lock:
                        if key not in self.operations and key not in [f"{op.thread_id}:{op.operation}" for op in self.completed_operations[-10:]]:
                            self.operations[key] = FuseOperation(
                                operation=operation,
                                thread_id=thread_id,
                                timestamp=timestamp
                            )
                            logger.debug(f"Operation detected from log: {operation} (thread {thread_id})")
                        
                        # Extract operation parameters
                        if key in self.operations:
                            op = self.operations[key]
                            params_match = self.patterns['op_params'].findall(clean_line)
                            for groups in params_match:
                                if groups[0]:  # parent
                                    op.parent = int(groups[0])
                                if groups[1]:  # path
                                    op.path = groups[1]
                                if groups[2]:  # name  
                                    op.name = groups[2]
                                if groups[3]:  # ino
                                    op.ino = int(groups[3])
                                if groups[4]:  # fh
                                    op.fh = int(groups[4])
                            
        except Exception as e:
            logger.debug(f"Error parsing log line: {e} - Line: {line}")
            
    def wait_for_operation(self, 
                          operation: str, 
                          path: Optional[str] = None,
                          timeout: float = 5.0,
                          check_fn: Optional[Callable[[FuseOperation], bool]] = None) -> Optional[FuseOperation]:
        """Wait for a specific FUSE operation to complete.
        
        Args:
            operation: The FUSE operation name (e.g., 'lookup', 'create', 'write')
            path: Optional path to match for the operation
            timeout: Maximum time to wait in seconds
            check_fn: Optional function to check if the operation matches criteria
            
        Returns:
            The completed operation if found, None if timeout
        """
        event_key = f"{operation}:{path}" if path else operation
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check already completed operations
            with self.lock:
                for op in self.completed_operations:
                    if op.operation == operation:
                        if path and op.path != path:
                            continue
                        if check_fn and not check_fn(op):
                            continue
                        return op
                        
                # Set up event for future operations
                event = self.operation_events[event_key]
                
            # Wait for the operation with a short timeout
            if event.wait(timeout=0.1):
                event.clear()
                # Re-check completed operations
                continue
                
        logger.warning(f"Timeout waiting for operation {operation}" + (f" on {path}" if path else ""))
        return None
        
    def wait_for_operations(self,
                           operations: List[str],
                           timeout: float = 5.0,
                           all_required: bool = True) -> List[FuseOperation]:
        """Wait for multiple operations to complete.
        
        Args:
            operations: List of operation names to wait for
            timeout: Maximum time to wait
            all_required: If True, wait for all operations; if False, return when any completes
            
        Returns:
            List of completed operations
        """
        found_ops = []
        remaining = set(operations)
        start_time = time.time()
        
        while remaining and time.time() - start_time < timeout:
            for op_name in list(remaining):
                op = self.wait_for_operation(op_name, timeout=0.5)
                if op:
                    found_ops.append(op)
                    remaining.remove(op_name)
                    if not all_required:
                        return found_ops
                        
        return found_ops
        
    def get_operation_count(self, operation: str) -> int:
        """Get count of completed operations of a specific type."""
        with self.lock:
            return sum(1 for op in self.completed_operations if op.operation == operation)
            
    def get_failed_operations(self) -> List[FuseOperation]:
        """Get all operations that failed."""
        with self.lock:
            return [op for op in self.completed_operations if op.status == OperationStatus.FAILED]
            
    def clear_completed(self):
        """Clear the list of completed operations."""
        with self.lock:
            self.completed_operations.clear()
            
    def get_logs(self) -> List[str]:
        """Get all captured log lines."""
        return self.log_lines.copy()


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
            for line in iter(self.process.stdout.readline, ''):
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
                logger.info(f"Note: {operation_name} took {elapsed:.2f}s to complete")
            return True, elapsed
        time.sleep(interval)
        
    elapsed = time.time() - start_time
    logger.warning(f"Warning: {operation_name} timed out after {elapsed:.2f}s")
    return False, elapsed


def wait_for_path_operation(trace_monitor: FuseTraceMonitor,
                           operation: str,
                           path: str,
                           timeout: float = 5.0) -> bool:
    """Wait for a specific FUSE operation on a path using trace monitoring.
    
    Args:
        trace_monitor: The FuseTraceMonitor instance
        operation: The FUSE operation to wait for
        path: The path to monitor
        timeout: Maximum time to wait
        
    Returns:
        True if operation completed successfully, False on timeout or error
    """
    op = trace_monitor.wait_for_operation(operation, path, timeout)
    return op is not None and op.status == OperationStatus.COMPLETED


def wait_for_file_creation(trace_monitor: FuseTraceMonitor,
                          filepath: Path,
                          timeout: float = 5.0) -> bool:
    """Wait for a file to be created, monitoring FUSE operations.
    
    Args:
        trace_monitor: The FuseTraceMonitor instance  
        filepath: Path to the file
        timeout: Maximum time to wait
        
    Returns:
        True if file was created successfully
    """
    # Wait for create operation
    filename = filepath.name
    parent_path = str(filepath.parent)
    
    def check_create(op: FuseOperation) -> bool:
        return (op.name == filename or 
                (op.path and op.path.endswith(filename)))
    
    op = trace_monitor.wait_for_operation('create', 
                                         check_fn=check_create,
                                         timeout=timeout)
    
    if op and op.status == OperationStatus.COMPLETED:
        # Also check the file exists
        return filepath.exists()
    return False


def wait_for_sync_operations(trace_monitor: FuseTraceMonitor,
                            operations: List[str],
                            timeout: float = 5.0) -> bool:
    """Wait for multiple FUSE operations to complete.
    
    Args:
        trace_monitor: The FuseTraceMonitor instance
        operations: List of operations to wait for
        timeout: Maximum time to wait
        
    Returns:
        True if all operations completed
    """
    ops = trace_monitor.wait_for_operations(operations, timeout, all_required=True)
    return len(ops) == len(operations)


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


class SmartWaitHelper:
    """Helper class to intelligently wait for filesystem operations."""
    
    def __init__(self, trace_monitor: Optional[FuseTraceMonitor] = None):
        """Initialize the wait helper.
        
        Args:
            trace_monitor: Optional trace monitor for operation tracking
        """
        self.trace_monitor = trace_monitor
        
    def wait_for_file_visible(self, filepath: Path, timeout: float = 2.0) -> bool:
        """Wait for a file to become visible in the filesystem.
        
        Uses trace monitoring if available, otherwise falls back to polling.
        """
        if self.trace_monitor:
            # Use trace-based waiting
            return wait_for_file_creation(self.trace_monitor, filepath, timeout)
        else:
            # Fall back to polling
            return wait_for_operation(
                lambda: filepath.exists(),
                timeout=timeout,
                operation_name=f"file {filepath} to exist"
            )[0]
            
    def wait_for_dir_visible(self, dirpath: Path, timeout: float = 2.0) -> bool:
        """Wait for a directory to become visible."""
        if self.trace_monitor:
            op = self.trace_monitor.wait_for_operation('mkdir', str(dirpath), timeout)
            return op is not None and op.status == OperationStatus.COMPLETED
        else:
            return wait_for_operation(
                lambda: dirpath.is_dir(),
                timeout=timeout,
                operation_name=f"directory {dirpath} to exist"
            )[0]
            
    def wait_for_deletion(self, path: Path, timeout: float = 2.0) -> bool:
        """Wait for a file or directory to be deleted."""
        if self.trace_monitor:
            # Wait for unlink or rmdir operation
            ops = self.trace_monitor.wait_for_operations(['unlink', 'rmdir'], timeout, all_required=False)
            for op in ops:
                if op.path == str(path) or (op.name and str(path).endswith(op.name)):
                    return True
            return False
        else:
            return wait_for_operation(
                lambda: not path.exists(),
                timeout=timeout,
                operation_name=f"deletion of {path}"
            )[0]
            
    def wait_for_write_complete(self, filepath: Path, timeout: float = 2.0) -> bool:
        """Wait for a write operation to complete on a file."""
        if self.trace_monitor:
            # Wait for write and release operations
            op = self.trace_monitor.wait_for_operation('write', str(filepath), timeout)
            if op and op.status == OperationStatus.COMPLETED:
                # Also wait for file handle release
                self.trace_monitor.wait_for_operation('release', timeout=1.0)
                return True
            return False
        else:
            # Without trace monitoring, just check file exists
            return filepath.exists()
            
    def wait_for_xattr_operation(self, path: Path, operation: str = 'setxattr', timeout: float = 2.0) -> bool:
        """Wait for an xattr operation to complete."""
        if self.trace_monitor:
            op = self.trace_monitor.wait_for_operation(operation, str(path), timeout)
            return op is not None and op.status == OperationStatus.COMPLETED
        else:
            # Can't reliably detect xattr operations without trace
            time.sleep(0.1)  # Small delay
            return True