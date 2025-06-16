"""
FUSE Process Management for mergerfs-rs Testing

This module provides utilities for managing mergerfs-rs FUSE processes
during testing, including mounting, unmounting, and process lifecycle.
"""

import os
import sys
import time
import signal
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager
import psutil
try:
    from .timing_utils import (
        wait_for_operation, FuseLogCapture, FuseTraceMonitor, 
        SmartWaitHelper, wait_for_path_operation
    )
except ImportError:
    # Fallback if timing_utils is not available
    FuseLogCapture = None
    FuseTraceMonitor = None
    SmartWaitHelper = None
    def wait_for_operation(check_fn, timeout=5.0, interval=0.1, operation_name="operation"):
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            if check_fn():
                return True, time.time() - start_time
            time.sleep(interval)
        return False, time.time() - start_time

# Try to import the simpler trace monitor as fallback
try:
    from .simple_trace import SimpleTraceMonitor, SimpleWaitHelper
except ImportError:
    SimpleTraceMonitor = None
    SimpleWaitHelper = None


@dataclass
class FuseConfig:
    """Configuration for a FUSE mount."""
    policy: str = "ff"  # ff, mfs, lfs
    branches: List[Path] = None
    mountpoint: Path = None
    readonly_branches: List[int] = None  # Indices of readonly branches
    timeout: float = 10.0
    enable_trace: bool = False  # Enable trace monitoring
    
    def __post_init__(self):
        if self.branches is None:
            self.branches = []


class FuseManager:
    """Manages mergerfs-rs FUSE processes for testing."""
    
    def __init__(self, binary_path: Optional[Path] = None, enable_trace: bool = False):
        """Initialize FUSE manager.
        
        Args:
            binary_path: Path to mergerfs-rs binary. If None, will search for it.
            enable_trace: Enable trace monitoring by default for all mounts
        """
        self.binary_path = binary_path or self._find_binary()
        self.active_mounts: Dict[Path, subprocess.Popen] = {}
        self.temp_dirs: List[Path] = []
        self.trace_monitors: Dict[Path, FuseTraceMonitor] = {}
        self.enable_trace = enable_trace
        
    def _find_binary(self) -> Path:
        """Find the mergerfs-rs binary."""
        # First try the target directory relative to python_tests
        base_dir = Path(__file__).parent.parent.parent
        release_path = base_dir / "target" / "release" / "mergerfs-rs"
        debug_path = base_dir / "target" / "debug" / "mergerfs-rs"
        
        if release_path.exists():
            return release_path
        elif debug_path.exists():
            return debug_path
        else:
            raise FileNotFoundError(
                f"Could not find mergerfs-rs binary. Tried:\n"
                f"  {release_path}\n"
                f"  {debug_path}\n"
                f"Please run 'cargo build' first."
            )
    
    def create_temp_dirs(self, count: int) -> List[Path]:
        """Create temporary directories for testing.
        
        Args:
            count: Number of directories to create
            
        Returns:
            List of created temporary directory paths
        """
        dirs = []
        for i in range(count):
            temp_dir = Path(tempfile.mkdtemp(prefix=f"mergerfs_test_branch_{i}_"))
            dirs.append(temp_dir)
            self.temp_dirs.append(temp_dir)
        return dirs
    
    def create_temp_mountpoint(self) -> Path:
        """Create a temporary mountpoint directory.
        
        Returns:
            Path to the created mountpoint
        """
        mountpoint = Path(tempfile.mkdtemp(prefix="mergerfs_test_mount_"))
        self.temp_dirs.append(mountpoint)
        return mountpoint
    
    def mount(self, config: FuseConfig) -> subprocess.Popen:
        """Mount a mergerfs-rs filesystem.
        
        Args:
            config: FUSE configuration
            
        Returns:
            The subprocess.Popen object for the FUSE process
            
        Raises:
            RuntimeError: If mount fails
        """
        if not config.branches:
            raise ValueError("At least one branch is required")
        if not config.mountpoint:
            raise ValueError("Mountpoint is required")
            
        # Ensure all directories exist
        for branch in config.branches:
            branch.mkdir(parents=True, exist_ok=True)
        config.mountpoint.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = [str(self.binary_path)]
        
        # Add policy option
        if config.policy != "ff":
            cmd.extend(["-o", f"func.create={config.policy}"])
            
        # Add mountpoint and branches
        cmd.append(str(config.mountpoint))
        cmd.extend([str(branch) for branch in config.branches])
        
        print(f"Mounting FUSE: {' '.join(cmd)}")
        
        # Set environment for debug logging if requested
        env = os.environ.copy()
        
        # Enable trace logging if requested
        if config.enable_trace or self.enable_trace or os.getenv('FUSE_TRACE'):
            env['RUST_LOG'] = 'trace'
        elif os.getenv('FUSE_DEBUG'):
            env['RUST_LOG'] = 'debug'
        elif os.getenv('RUST_LOG'):
            env['RUST_LOG'] = os.getenv('RUST_LOG')
        else:
            env['RUST_LOG'] = 'info'
            
        # Start the process
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            
            # Start trace monitoring if enabled
            trace_monitor = None
            if (config.enable_trace or self.enable_trace):
                # Use simple trace monitor by default (more reliable)
                if SimpleTraceMonitor:
                    trace_monitor = SimpleTraceMonitor(process)
                elif FuseTraceMonitor:
                    # Fall back to advanced if simple not available
                    trace_monitor = FuseTraceMonitor(process)
                    
                if trace_monitor:
                    trace_monitor.start_capture()
                    self.trace_monitors[config.mountpoint] = trace_monitor
                
            # Start legacy log capture if debug is enabled
            log_capture = None
            if FuseLogCapture and env.get('RUST_LOG') in ['debug', 'trace'] and not trace_monitor:
                log_capture = FuseLogCapture(process)
                log_capture.start_capture()
            
            # Give the process a moment to start
            time.sleep(0.05)  # Further reduced with trace monitoring
            
            # Check if process is still running
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"FUSE process exited immediately with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}")
            
            # Wait for mount to be ready with better diagnostics
            mount_start = time.time()
            if trace_monitor and hasattr(trace_monitor, 'wait_for_operation'):
                # Use advanced trace-based waiting
                self._wait_for_mount_traced(config.mountpoint, trace_monitor, config.timeout)
            else:
                # Use traditional polling (also for SimpleTraceMonitor)
                self._wait_for_mount(config.mountpoint, config.timeout)
            mount_time = time.time() - mount_start
            
            if mount_time > 0.5:
                print(f"Mount took {mount_time:.2f}s to become ready")
                
            # Store monitors with the process
            if trace_monitor:
                process._trace_monitor = trace_monitor
            if log_capture:
                process._log_capture = log_capture
            
            # Store the mount
            self.active_mounts[config.mountpoint] = process
            
            return process
            
        except Exception as e:
            raise RuntimeError(f"Failed to mount FUSE filesystem: {e}")
    
    def _wait_for_mount(self, mountpoint: Path, timeout: float):
        """Wait for the FUSE mount to be ready.
        
        Args:
            mountpoint: Path to the mountpoint
            timeout: Timeout in seconds
            
        Raises:
            TimeoutError: If mount doesn't become ready in time
        """
        def check_mount():
            try:
                # Try to stat the mountpoint - this will work when FUSE is ready
                os.stat(mountpoint)
                # Also try to list directory to ensure it's fully mounted
                list(mountpoint.iterdir())
                return True
            except (OSError, PermissionError):
                return False
                
        success, elapsed = wait_for_operation(
            check_mount,
            timeout=timeout,
            interval=0.05,  # Reduced from 0.1 for faster response
            operation_name=f"mount at {mountpoint}"
        )
        
        if not success:
            raise TimeoutError(f"FUSE mount at {mountpoint} did not become ready within {timeout}s")
    
    def _wait_for_mount_traced(self, mountpoint: Path, trace_monitor: FuseTraceMonitor, timeout: float):
        """Wait for mount using trace monitoring.
        
        Args:
            mountpoint: Path to the mountpoint
            trace_monitor: The trace monitor instance
            timeout: Timeout in seconds
            
        Raises:
            TimeoutError: If mount doesn't become ready in time
        """
        # Wait for initial lookup operations that indicate mount is ready
        start_time = time.time()
        
        # First, ensure basic stat works
        def check_stat():
            try:
                os.stat(mountpoint)
                return True
            except:
                return False
                
        success, _ = wait_for_operation(
            check_stat,
            timeout=timeout / 2,
            interval=0.02,
            operation_name=f"stat on {mountpoint}"
        )
        
        if not success:
            raise TimeoutError(f"FUSE mount at {mountpoint} did not respond to stat within {timeout/2}s")
            
        # Wait for a lookup operation to complete successfully
        op = trace_monitor.wait_for_operation('lookup', timeout=timeout/2)
        if not op:
            # If no lookup yet, try to trigger one
            try:
                list(mountpoint.iterdir())
            except:
                pass
                
        # Verify mount is truly ready
        remaining_time = timeout - (time.time() - start_time)
        success, _ = wait_for_operation(
            lambda: self._is_mount_ready(mountpoint),
            timeout=remaining_time,
            interval=0.02,
            operation_name=f"mount ready check for {mountpoint}"
        )
        
        if not success:
            raise TimeoutError(f"FUSE mount at {mountpoint} did not become fully ready within {timeout}s")
            
    def _is_mount_ready(self, mountpoint: Path) -> bool:
        """Check if a mount point is fully ready."""
        try:
            # Try to stat
            os.stat(mountpoint)
            # Try to list directory
            list(mountpoint.iterdir())
            return True
        except:
            return False
    
    def unmount(self, mountpoint: Path) -> bool:
        """Unmount a FUSE filesystem.
        
        Args:
            mountpoint: Path to the mountpoint
            
        Returns:
            True if unmount was successful
        """
        if mountpoint not in self.active_mounts:
            return False
            
        process = self.active_mounts[mountpoint]
        
        try:
            # First try graceful shutdown
            process.terminate()
            
            # Wait for process to exit with shorter timeout
            try:
                process.wait(timeout=1.0)  # Reduced from 5.0 for faster unmount
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown fails
                process.kill()
                process.wait(timeout=0.5)  # Reduced from 2.0
                
            # Remove from active mounts
            del self.active_mounts[mountpoint]
            
            # Stop trace monitor if present
            trace_monitor = None
            if hasattr(process, '_trace_monitor'):
                trace_monitor = process._trace_monitor
                trace_monitor.stop_capture()
                
                # Print trace summary if requested
                if os.getenv('FUSE_TRACE_SUMMARY'):
                    print("\n=== FUSE Trace Summary ===")
                    print(f"Total operations: {len(trace_monitor.completed_operations)}")
                    failed_ops = trace_monitor.get_failed_operations()
                    if failed_ops:
                        print(f"Failed operations: {len(failed_ops)}")
                        for op in failed_ops[:10]:
                            print(f"  - {op.operation} (error: {op.error_code})")
                    print("=========================\n")
                    
                # Remove from trace monitors
                if mountpoint in self.trace_monitors:
                    del self.trace_monitors[mountpoint]
            
            # Wait for the mountpoint to be unmounted
            unmount_start = time.time()
            if trace_monitor and hasattr(trace_monitor, 'wait_for_operation'):
                # Wait for destroy operation (advanced trace only)
                trace_monitor.wait_for_operation('destroy', timeout=0.5)
            self._wait_for_unmount(mountpoint, timeout=2.0)  # Reduced from 5.0
            unmount_time = time.time() - unmount_start
            
            if unmount_time > 0.5:
                print(f"Unmount took {unmount_time:.2f}s to complete")
                
            # Stop log capture if present
            if hasattr(process, '_log_capture'):
                process._log_capture.stop_capture()
                if os.getenv('FUSE_DEBUG_LOGS'):
                    logs = process._log_capture.get_logs()
                    if logs:
                        print("\n=== FUSE Debug Logs ===")
                        for line in logs[-50:]:  # Last 50 lines
                            print(line)
                        print("======================\n")
            
            return True
            
        except Exception as e:
            print(f"Error unmounting {mountpoint}: {e}")
            return False
    
    def _wait_for_unmount(self, mountpoint: Path, timeout: float):
        """Wait for the mountpoint to be unmounted.
        
        Args:
            mountpoint: Path to the mountpoint
            timeout: Timeout in seconds
        """
        def check_unmounted():
            try:
                # Try to stat the directory - FUSE mount will fail when unmounted
                os.stat(mountpoint / ".mergerfs")
                return False  # Still mounted if we can stat .mergerfs
            except (OSError, FileNotFoundError):
                # Expected when unmounted
                return True
                
        success, elapsed = wait_for_operation(
            check_unmounted,
            timeout=timeout,
            interval=0.05,
            operation_name=f"unmount at {mountpoint}"
        )
    
    def cleanup(self):
        """Clean up all active mounts and temporary directories."""
        # Unmount all active FUSE mounts
        for mountpoint in list(self.active_mounts.keys()):
            self.unmount(mountpoint)
        
        # Ensure all trace monitors are stopped
        for monitor in self.trace_monitors.values():
            try:
                monitor.stop_capture()
            except:
                pass
        self.trace_monitors.clear()
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Warning: Could not remove {temp_dir}: {e}")
        
        self.temp_dirs.clear()
    
    @contextmanager
    def mounted_fs(self, config: FuseConfig):
        """Context manager for mounting/unmounting a filesystem.
        
        Args:
            config: FUSE configuration
            
        Yields:
            Tuple of (process, mountpoint, branches) or 
            Tuple of (process, mountpoint, branches, trace_monitor) if tracing enabled
        """
        process = None
        try:
            process = self.mount(config)
            if config.enable_trace and config.mountpoint in self.trace_monitors:
                yield process, config.mountpoint, config.branches, self.trace_monitors[config.mountpoint]
            else:
                yield process, config.mountpoint, config.branches
        finally:
            if process and config.mountpoint in self.active_mounts:
                self.unmount(config.mountpoint)
    
    def get_trace_monitor(self, mountpoint: Path) -> Optional[FuseTraceMonitor]:
        """Get the trace monitor for a mount point if available."""
        return self.trace_monitors.get(mountpoint)
        
    def get_smart_wait_helper(self, mountpoint: Path) -> SmartWaitHelper:
        """Get a SmartWaitHelper for a mount point.
        
        This will use trace monitoring if available, otherwise fall back to polling.
        """
        trace_monitor = self.get_trace_monitor(mountpoint)
        
        # Try to return appropriate helper
        if trace_monitor:
            if SimpleWaitHelper and hasattr(trace_monitor, 'wait_for_pattern'):
                # Simple trace monitor detected
                return SimpleWaitHelper(trace_monitor)
            elif SmartWaitHelper:
                # Advanced trace monitor
                return SmartWaitHelper(trace_monitor)
        
        # Fall back to polling-based helpers
        if SimpleWaitHelper:
            return SimpleWaitHelper(None)
        elif SmartWaitHelper:
            return SmartWaitHelper(None)
        else:
            raise RuntimeError("No wait helper available")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


class FileSystemState:
    """Helper for examining filesystem state."""
    
    @staticmethod
    def get_file_locations(branches: List[Path], filename: str) -> List[int]:
        """Get which branches contain a specific file.
        
        Args:
            branches: List of branch directories
            filename: Name of file to check
            
        Returns:
            List of branch indices that contain the file
        """
        locations = []
        for i, branch in enumerate(branches):
            if (branch / filename).exists():
                locations.append(i)
        return locations
    
    @staticmethod
    def get_branch_sizes(branches: List[Path]) -> List[int]:
        """Get the total size of files in each branch.
        
        Args:
            branches: List of branch directories
            
        Returns:
            List of total sizes in bytes for each branch
        """
        sizes = []
        for branch in branches:
            total_size = 0
            for file_path in branch.rglob("*"):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
            sizes.append(total_size)
        return sizes
    
    @staticmethod
    def create_file_with_size(path: Path, size: int, content: bytes = None):
        """Create a file with specific size.
        
        Args:
            path: Path to create file at
            size: Size in bytes
            content: Content to repeat. If None, uses b'x'
        """
        if content is None:
            content = b'x'
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'wb') as f:
            written = 0
            while written < size:
                to_write = min(len(content), size - written)
                f.write(content[:to_write])
                written += to_write