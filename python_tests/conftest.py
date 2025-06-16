"""
Pytest configuration and fixtures for mergerfs-rs testing.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from typing import List, Generator

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState
from lib.tmpfs_manager import TmpfsManager, get_tmpfs_manager
try:
    from lib.timing_utils import SmartWaitHelper
except ImportError:
    SmartWaitHelper = None
try:
    from lib.simple_trace import SimpleWaitHelper
except ImportError:
    SimpleWaitHelper = None
import os


@pytest.fixture(scope="session")
def fuse_manager() -> Generator[FuseManager, None, None]:
    """Session-scoped FUSE manager that handles cleanup."""
    # Enable trace monitoring if requested via environment
    enable_trace = os.getenv('FUSE_TRACE', '').lower() in ('1', 'true', 'yes')
    manager = FuseManager(enable_trace=enable_trace)
    try:
        yield manager
    finally:
        manager.cleanup()


@pytest.fixture
def temp_branches(fuse_manager: FuseManager) -> List[Path]:
    """Create 3 temporary branch directories."""
    return fuse_manager.create_temp_dirs(3)


@pytest.fixture
def tmpfs_branches() -> Generator[List[Path], None, None]:
    """Create 3 tmpfs mounts with different sizes for testing space-based policies."""
    tmpfs_mgr = get_tmpfs_manager()
    
    # Validate that tmpfs mounts are available
    is_valid, errors = tmpfs_mgr.validate_setup()
    if not is_valid:
        pytest.skip(f"Tmpfs mounts not available: {'; '.join(errors)}")
    
    # Prepare 3 mounts with specific free space:
    # small: 8MB free, medium: 40MB free, large: 90MB free
    try:
        small_mount, medium_mount, large_mount = tmpfs_mgr.prepare_space_test(8, 40, 90)
        yield [small_mount.path, medium_mount.path, large_mount.path]
    finally:
        # Clean up after test
        tmpfs_mgr.clear_all()


@pytest.fixture
def mounted_fs_with_policy(fuse_manager: FuseManager, request):
    """Mount filesystem with a specific policy on tmpfs branches.
    
    Usage:
        @pytest.mark.parametrize('mounted_fs_with_policy', ['lus'], indirect=True)
        def test_something(mounted_fs_with_policy):
            process, mountpoint, branches = mounted_fs_with_policy
    """
    # Get policy from parametrize
    policy = request.param if hasattr(request, 'param') else 'ff'
    
    # Get tmpfs manager and validate
    tmpfs_mgr = get_tmpfs_manager()
    is_valid, errors = tmpfs_mgr.validate_setup()
    if not is_valid:
        pytest.skip(f"Tmpfs mounts not available: {'; '.join(errors)}")
    
    # Clear all mounts first
    tmpfs_mgr.clear_all()
    
    # Use standard tmpfs mounts directly
    branches = [
        Path("/tmp/mergerfs_test_100mb"),
        Path("/tmp/mergerfs_test_200mb"),
        Path("/tmp/mergerfs_test_500mb")
    ]
    
    # Create mountpoint
    mountpoint = fuse_manager.create_temp_mountpoint()
    
    # Create config with specified policy
    config = FuseConfig(
        policy=policy,
        branches=branches,
        mountpoint=mountpoint,
        enable_trace=os.getenv('FUSE_TRACE', '').lower() in ('1', 'true', 'yes')
    )
    
    # Mount and yield
    with fuse_manager.mounted_fs(config) as result:
        yield result


@pytest.fixture
def temp_mountpoint(fuse_manager: FuseManager) -> Path:
    """Create a temporary mountpoint."""
    return fuse_manager.create_temp_mountpoint()


@pytest.fixture
def fuse_config(temp_branches: List[Path], temp_mountpoint: Path) -> FuseConfig:
    """Create a basic FUSE configuration."""
    # Enable trace if requested
    enable_trace = os.getenv('FUSE_TRACE', '').lower() in ('1', 'true', 'yes')
    return FuseConfig(
        policy="ff",
        branches=temp_branches,
        mountpoint=temp_mountpoint,
        enable_trace=enable_trace
    )


@pytest.fixture
def fs_state() -> FileSystemState:
    """Create a filesystem state helper."""
    return FileSystemState()


@pytest.fixture(params=["ff", "mfs", "lfs"])
def policy(request) -> str:
    """Parametrized fixture for all policies."""
    return request.param


@pytest.fixture
def mounted_fs(fuse_manager: FuseManager, fuse_config: FuseConfig):
    """Fixture that provides a mounted filesystem."""
    with fuse_manager.mounted_fs(fuse_config) as result:
        # Handle both trace and non-trace cases
        if len(result) == 4:
            # Trace monitoring enabled
            yield result
        else:
            # No trace monitoring
            yield result


@pytest.fixture
def mounted_fs_with_trace(fuse_manager: FuseManager, temp_branches: List[Path], temp_mountpoint: Path):
    """Fixture that provides a mounted filesystem with trace monitoring enabled."""
    config = FuseConfig(
        policy="ff",
        branches=temp_branches,
        mountpoint=temp_mountpoint,
        enable_trace=True
    )
    with fuse_manager.mounted_fs(config) as result:
        if len(result) == 4:
            yield result
        else:
            # Fallback if trace monitoring isn't available
            process, mountpoint, branches = result
            yield process, mountpoint, branches, None


@pytest.fixture
def smart_wait(fuse_manager: FuseManager, mounted_fs):
    """Provide a SmartWaitHelper for the mounted filesystem."""
    # Extract mountpoint from mounted_fs result
    if len(mounted_fs) >= 2:
        mountpoint = mounted_fs[1]
    else:
        raise ValueError("Invalid mounted_fs fixture result")
        
    return fuse_manager.get_smart_wait_helper(mountpoint)


# Markers for different test types
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests") 
    config.addinivalue_line("markers", "policy: Policy behavior tests")
    config.addinivalue_line("markers", "property: Property-based tests")
    config.addinivalue_line("markers", "fuzz: Fuzz tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "concurrent: Concurrent access tests")
    config.addinivalue_line("markers", "stress: Stress tests")


# Custom pytest collection
def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names."""
    for item in items:
        # Add markers based on test file names
        if "property" in item.nodeid:
            item.add_marker(pytest.mark.property)
        if "policy" in item.nodeid:
            item.add_marker(pytest.mark.policy)
        if "concurrent" in item.nodeid:
            item.add_marker(pytest.mark.concurrent)
        if "fuzz" in item.nodeid:
            item.add_marker(pytest.mark.fuzz)
        if "stress" in item.nodeid:
            item.add_marker(pytest.mark.stress)
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)