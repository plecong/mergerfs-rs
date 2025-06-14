"""
Tmpfs Manager for mergerfs-rs Python Integration Tests

This module provides utilities for managing tmpfs mounts during testing.
It expects tmpfs mounts to be created by the setup_tmpfs.sh script.
"""

import os
import shutil
from pathlib import Path
from typing import List, Tuple, Optional
import subprocess


class TmpfsMount:
    """Represents a tmpfs mount point for testing."""
    
    def __init__(self, path: Path, size_mb: int):
        self.path = path
        self.size_mb = size_mb
        
    def exists(self) -> bool:
        """Check if the tmpfs mount exists and is mounted."""
        if not self.path.exists():
            return False
            
        # Check if it's actually mounted
        try:
            result = subprocess.run(
                ['mountpoint', '-q', str(self.path)],
                capture_output=True
            )
            return result.returncode == 0
        except:
            return False
    
    def get_available_space_mb(self) -> float:
        """Get available space in MB."""
        if not self.exists():
            raise RuntimeError(f"Tmpfs {self.path} is not mounted")
            
        stat = os.statvfs(self.path)
        # Use f_bavail for available blocks (matches our Rust implementation)
        available_bytes = stat.f_bavail * stat.f_frsize
        return available_bytes / (1024 * 1024)
    
    def get_used_space_mb(self) -> float:
        """Get used space in MB."""
        if not self.exists():
            raise RuntimeError(f"Tmpfs {self.path} is not mounted")
            
        stat = os.statvfs(self.path)
        total_bytes = stat.f_blocks * stat.f_frsize
        available_bytes = stat.f_bavail * stat.f_frsize
        used_bytes = total_bytes - available_bytes
        return used_bytes / (1024 * 1024)
    
    def clear(self):
        """Remove all contents from the tmpfs mount."""
        if not self.exists():
            raise RuntimeError(f"Tmpfs {self.path} is not mounted")
            
        # Remove everything except the marker file
        for item in self.path.iterdir():
            if item.name != '.mergerfs_test_marker':
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
    
    def fill_space(self, filename: str, size_mb: float):
        """Create a file of specific size to fill space."""
        if not self.exists():
            raise RuntimeError(f"Tmpfs {self.path} is not mounted")
            
        file_path = self.path / filename
        size_bytes = int(size_mb * 1024 * 1024)
        
        # Use dd to create file of exact size
        subprocess.run([
            'dd', 'if=/dev/zero', f'of={file_path}',
            'bs=1M', f'count={int(size_mb)}',
            'status=none'
        ], check=True)
        
        # If we need partial MB, write the remainder
        remainder = size_bytes - (int(size_mb) * 1024 * 1024)
        if remainder > 0:
            with open(file_path, 'ab') as f:
                f.write(b'\0' * remainder)


class TmpfsManager:
    """Manager for tmpfs mounts used in integration testing."""
    
    # Standard tmpfs mount configurations
    STANDARD_MOUNTS = [
        (10, '/tmp/mergerfs_test_10mb'),
        (50, '/tmp/mergerfs_test_50mb'),
        (100, '/tmp/mergerfs_test_100mb'),
        (200, '/tmp/mergerfs_test_200mb'),
        (500, '/tmp/mergerfs_test_500mb'),
    ]
    
    def __init__(self):
        self.mounts = []
        self._initialize_mounts()
    
    def _initialize_mounts(self):
        """Initialize the list of available tmpfs mounts."""
        for size_mb, path_str in self.STANDARD_MOUNTS:
            mount = TmpfsMount(Path(path_str), size_mb)
            if mount.exists():
                self.mounts.append(mount)
    
    def validate_setup(self) -> Tuple[bool, List[str]]:
        """
        Validate that tmpfs mounts are properly set up.
        
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        if not self.mounts:
            errors.append("No tmpfs mounts found. Run: sudo python_tests/scripts/setup_tmpfs.sh")
            return False, errors
        
        # Check which standard mounts are missing
        found_sizes = {m.size_mb for m in self.mounts}
        expected_sizes = {size for size, _ in self.STANDARD_MOUNTS}
        missing_sizes = expected_sizes - found_sizes
        
        if missing_sizes:
            errors.append(f"Missing tmpfs mounts for sizes: {sorted(missing_sizes)}MB")
        
        return len(errors) == 0, errors
    
    def get_mounts_by_size(self, min_size_mb: Optional[int] = None, 
                          max_size_mb: Optional[int] = None) -> List[TmpfsMount]:
        """Get tmpfs mounts filtered by size."""
        result = []
        for mount in self.mounts:
            if min_size_mb is not None and mount.size_mb < min_size_mb:
                continue
            if max_size_mb is not None and mount.size_mb > max_size_mb:
                continue
            result.append(mount)
        return result
    
    def prepare_space_test(self, small_free_mb: float, medium_free_mb: float, 
                          large_free_mb: float) -> Tuple[TmpfsMount, TmpfsMount, TmpfsMount]:
        """
        Prepare three tmpfs mounts with specific free space for testing.
        
        Returns:
            (small_mount, medium_mount, large_mount)
        """
        # Select appropriate mounts based on required space
        candidates = []
        
        for mount in self.mounts:
            mount.clear()  # Start fresh
            available = mount.get_available_space_mb()
            
            if available >= large_free_mb:
                candidates.append((mount, available))
        
        if len(candidates) < 3:
            raise RuntimeError(
                f"Need at least 3 tmpfs mounts with {large_free_mb}MB+ space. "
                f"Found {len(candidates)}. Check tmpfs setup."
            )
        
        # Sort by size and pick three different ones
        candidates.sort(key=lambda x: x[0].size_mb)
        small_mount, medium_mount, large_mount = [c[0] for c in candidates[:3]]
        
        # Fill space to achieve desired free space
        # For small mount
        available = small_mount.get_available_space_mb()
        if available > small_free_mb:
            fill_size = available - small_free_mb - 0.5  # Leave 0.5MB buffer
            if fill_size > 0:
                small_mount.fill_space('filler.dat', fill_size)
        
        # For medium mount
        available = medium_mount.get_available_space_mb()
        if available > medium_free_mb:
            fill_size = available - medium_free_mb - 0.5
            if fill_size > 0:
                medium_mount.fill_space('filler.dat', fill_size)
        
        # For large mount
        available = large_mount.get_available_space_mb()
        if available > large_free_mb:
            fill_size = available - large_free_mb - 0.5
            if fill_size > 0:
                large_mount.fill_space('filler.dat', fill_size)
        
        return small_mount, medium_mount, large_mount
    
    def clear_all(self):
        """Clear all tmpfs mounts."""
        for mount in self.mounts:
            try:
                mount.clear()
            except Exception as e:
                print(f"Warning: Failed to clear {mount.path}: {e}")


# Global instance for easy access
_manager = None

def get_tmpfs_manager() -> TmpfsManager:
    """Get the global tmpfs manager instance."""
    global _manager
    if _manager is None:
        _manager = TmpfsManager()
    return _manager