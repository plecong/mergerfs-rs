"""Debug test for access operation."""

import os
import stat
from pathlib import Path
import pytest


@pytest.mark.integration
def test_access_debug(mounted_fs):
    """Debug access permission checking."""
    process, mountpoint, branches = mounted_fs
    
    # Create a test file
    test_file = mountpoint / "debug_test.txt"
    test_file.write_text("test content")
    
    # Get initial permissions
    initial_stat = test_file.stat()
    print(f"Initial file mode: {oct(initial_stat.st_mode)}")
    print(f"Initial permissions: rwx={oct(initial_stat.st_mode & 0o777)}")
    print(f"User bits: {oct((initial_stat.st_mode >> 6) & 0o7)}")
    print(f"UID: {initial_stat.st_uid}, GID: {initial_stat.st_gid}")
    print(f"Current UID: {os.getuid()}, Current GID: {os.getgid()}")
    
    # Check initial access
    print(f"\nInitial access - R_OK: {os.access(test_file, os.R_OK)}")
    print(f"Initial access - W_OK: {os.access(test_file, os.W_OK)}")
    print(f"Initial access - X_OK: {os.access(test_file, os.X_OK)}")
    
    # Change to write-only (remove all read bits)
    test_file.chmod(0o200)  # Only owner write
    
    # Check new permissions
    new_stat = test_file.stat()
    print(f"\nNew file mode: {oct(new_stat.st_mode)}")
    print(f"New permissions: rwx={oct(new_stat.st_mode & 0o777)}")
    print(f"User bits: {oct((new_stat.st_mode >> 6) & 0o7)}")
    
    # Check access after chmod
    print(f"\nAfter chmod - R_OK: {os.access(test_file, os.R_OK)}")
    print(f"After chmod - W_OK: {os.access(test_file, os.W_OK)}")
    print(f"After chmod - X_OK: {os.access(test_file, os.X_OK)}")
    
    # Check branch files
    print("\nBranch file permissions:")
    for branch in branches:
        branch_file = branch / "debug_test.txt"
        if branch_file.exists():
            branch_stat = branch_file.stat()
            print(f"  {branch}: mode={oct(branch_stat.st_mode)}, " + 
                  f"perms={oct(branch_stat.st_mode & 0o777)}, " +
                  f"uid={branch_stat.st_uid}, gid={branch_stat.st_gid}")