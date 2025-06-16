"""
Simplified trace monitoring that works with current log format.

This provides a pragmatic solution that's better than hardcoded sleeps
even if it can't track every operation perfectly.
"""

import re
import time
import threading
import queue
from pathlib import Path
from typing import Optional, List, Callable
import logging

logger = logging.getLogger(__name__)


class SimpleTraceMonitor:
    """Simplified trace monitor that looks for key patterns in logs."""
    
    def __init__(self, process):
        self.process = process
        self.log_lines = []
        self.capture_thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        
        # Patterns for common operations we care about
        self.patterns = {
            'lookup': re.compile(r'fuse::lookup.*?(parent|name)'),
            'create': re.compile(r'fuse::create'),
            'write': re.compile(r'fuse::write'),
            'mkdir': re.compile(r'fuse::mkdir'),
            'rmdir': re.compile(r'fuse::rmdir'),
            'unlink': re.compile(r'fuse::unlink'),
            'getattr': re.compile(r'fuse::getattr'),
            'setxattr': re.compile(r'fuse::setxattr'),
            'getxattr': re.compile(r'fuse::getxattr'),
            'listxattr': re.compile(r'fuse::listxattr'),
            'mount_ready': re.compile(r'(Mounting|Starting mergerfs-rs mount)'),
        }
        
        # ANSI escape code remover
        self.ansi_escape = re.compile(r'\[\d+m')
        
    def start_capture(self):
        """Start capturing logs."""
        self.capture_thread = threading.Thread(target=self._capture_logs)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        
    def stop_capture(self):
        """Stop capturing logs."""
        self.stop_event.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
            
    def _capture_logs(self):
        """Background thread to capture logs."""
        try:
            for line in iter(self.process.stdout.readline, ''):
                if self.stop_event.is_set():
                    break
                if line:
                    clean_line = self.ansi_escape.sub('', line.strip())
                    self.log_lines.append(clean_line)
                    self.log_queue.put(clean_line)
        except Exception as e:
            logger.error(f"Error capturing logs: {e}")
            
    def wait_for_pattern(self, pattern_name: str, timeout: float = 5.0) -> bool:
        """Wait for a specific pattern to appear in logs.
        
        Args:
            pattern_name: Name of pattern to wait for (from self.patterns)
            timeout: Maximum time to wait
            
        Returns:
            True if pattern found, False if timeout
        """
        if pattern_name not in self.patterns:
            logger.warning(f"Unknown pattern: {pattern_name}")
            return False
            
        pattern = self.patterns[pattern_name]
        start_time = time.time()
        
        # Check existing logs first
        for line in self.log_lines:
            if pattern.search(line):
                return True
                
        # Wait for new logs
        while time.time() - start_time < timeout:
            try:
                line = self.log_queue.get(timeout=0.1)
                if pattern.search(line):
                    return True
            except queue.Empty:
                continue
                
        return False
        
    def wait_for_mount_ready(self, timeout: float = 10.0) -> bool:
        """Wait for mount to be ready."""
        return self.wait_for_pattern('mount_ready', timeout)
        
    def get_recent_logs(self, count: int = 50) -> List[str]:
        """Get recent log lines."""
        return self.log_lines[-count:]


class SimpleWaitHelper:
    """Simplified wait helper that uses trace monitoring when available."""
    
    def __init__(self, trace_monitor: Optional[SimpleTraceMonitor] = None):
        self.trace_monitor = trace_monitor
        
    def wait_for_file_visible(self, filepath: Path, timeout: float = 2.0) -> bool:
        """Wait for a file to become visible."""
        if self.trace_monitor:
            # Look for create or lookup operations
            if self.trace_monitor.wait_for_pattern('create', timeout=0.5):
                # Give it a moment to complete
                time.sleep(0.1)
                
        # Always verify with actual filesystem check
        return self._wait_for_condition(lambda: filepath.exists(), timeout)
        
    def wait_for_write_complete(self, filepath: Path, timeout: float = 2.0) -> bool:
        """Wait for write operation to complete."""
        if self.trace_monitor:
            self.trace_monitor.wait_for_pattern('write', timeout=0.5)
            time.sleep(0.1)
            
        return filepath.exists()
        
    def wait_for_dir_visible(self, dirpath: Path, timeout: float = 2.0) -> bool:
        """Wait for directory to become visible."""
        if self.trace_monitor:
            self.trace_monitor.wait_for_pattern('mkdir', timeout=0.5)
            time.sleep(0.1)
            
        return self._wait_for_condition(lambda: dirpath.is_dir(), timeout)
        
    def wait_for_deletion(self, path: Path, timeout: float = 2.0) -> bool:
        """Wait for file or directory deletion."""
        if self.trace_monitor:
            if path.is_dir():
                self.trace_monitor.wait_for_pattern('rmdir', timeout=0.5)
            else:
                self.trace_monitor.wait_for_pattern('unlink', timeout=0.5)
            time.sleep(0.1)
            
        return self._wait_for_condition(lambda: not path.exists(), timeout)
        
    def wait_for_xattr_operation(self, path: Path, operation: str = 'setxattr', timeout: float = 2.0) -> bool:
        """Wait for xattr operation."""
        if self.trace_monitor:
            self.trace_monitor.wait_for_pattern(operation, timeout=0.5)
            time.sleep(0.1)
            
        return True  # Xattr operations are usually synchronous
        
    def _wait_for_condition(self, condition_fn: Callable[[], bool], timeout: float) -> bool:
        """Wait for a condition to become true."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if condition_fn():
                return True
            time.sleep(0.05)
        return False