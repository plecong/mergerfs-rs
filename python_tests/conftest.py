"""
Pytest configuration and fixtures for mergerfs-rs testing.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from typing import List, Generator

from lib.fuse_manager import FuseManager, FuseConfig, FileSystemState


@pytest.fixture(scope="session")
def fuse_manager() -> Generator[FuseManager, None, None]:
    """Session-scoped FUSE manager that handles cleanup."""
    manager = FuseManager()
    try:
        yield manager
    finally:
        manager.cleanup()


@pytest.fixture
def temp_branches(fuse_manager: FuseManager) -> List[Path]:
    """Create 3 temporary branch directories."""
    return fuse_manager.create_temp_dirs(3)


@pytest.fixture
def temp_mountpoint(fuse_manager: FuseManager) -> Path:
    """Create a temporary mountpoint."""
    return fuse_manager.create_temp_mountpoint()


@pytest.fixture
def fuse_config(temp_branches: List[Path], temp_mountpoint: Path) -> FuseConfig:
    """Create a basic FUSE configuration."""
    return FuseConfig(
        policy="ff",
        branches=temp_branches,
        mountpoint=temp_mountpoint
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
    with fuse_manager.mounted_fs(fuse_config) as (process, mountpoint, branches):
        yield process, mountpoint, branches


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