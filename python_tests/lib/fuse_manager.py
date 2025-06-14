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


@dataclass
class FuseConfig:
    """Configuration for a FUSE mount."""
    policy: str = "ff"  # ff, mfs, lfs
    branches: List[Path] = None
    mountpoint: Path = None
    readonly_branches: List[int] = None  # Indices of readonly branches
    timeout: float = 10.0
    
    def __post_init__(self):
        if self.branches is None:
            self.branches = []


class FuseManager:
    """Manages mergerfs-rs FUSE processes for testing."""
    
    def __init__(self, binary_path: Optional[Path] = None):
        """Initialize FUSE manager.
        
        Args:
            binary_path: Path to mergerfs-rs binary. If None, will search for it.
        """
        self.binary_path = binary_path or self._find_binary()
        self.active_mounts: Dict[Path, subprocess.Popen] = {}
        self.temp_dirs: List[Path] = []
        
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
        
        # Start the process
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Give the process a moment to start
            time.sleep(0.5)
            
            # Check if process is still running
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"FUSE process exited immediately with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}")
            
            # Wait for mount to be ready
            self._wait_for_mount(config.mountpoint, config.timeout)
            
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
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to stat the mountpoint - this will work when FUSE is ready
                os.stat(mountpoint)
                return
            except OSError:
                time.sleep(0.1)
                continue
                
        raise TimeoutError(f"FUSE mount at {mountpoint} did not become ready within {timeout}s")
    
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
            
            # Wait for process to exit
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown fails
                process.kill()
                process.wait(timeout=2.0)
                
            # Remove from active mounts
            del self.active_mounts[mountpoint]
            
            # Wait for the mountpoint to be unmounted
            self._wait_for_unmount(mountpoint, timeout=5.0)
            
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
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if mountpoint is still mounted by trying to list it
                # An unmounted FUSE mountpoint will typically be empty
                if not list(mountpoint.iterdir()):
                    return
            except (OSError, PermissionError):
                # This is expected when unmounting
                return
            time.sleep(0.1)
    
    def cleanup(self):
        """Clean up all active mounts and temporary directories."""
        # Unmount all active FUSE mounts
        for mountpoint in list(self.active_mounts.keys()):
            self.unmount(mountpoint)
        
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
            Tuple of (process, mountpoint, branches)
        """
        process = None
        try:
            process = self.mount(config)
            yield process, config.mountpoint, config.branches
        finally:
            if process and config.mountpoint in self.active_mounts:
                self.unmount(config.mountpoint)
    
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