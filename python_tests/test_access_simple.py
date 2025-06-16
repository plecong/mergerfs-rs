"""Simple test to debug Python's os.access behavior."""

import os
import stat
import subprocess
import tempfile
import time
from pathlib import Path


def test_direct_access():
    """Test os.access directly on filesystem."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        test_file = Path(f.name)
    
    # Write content
    test_file.write_text("test content")
    
    print(f"Initial mode: {oct(test_file.stat().st_mode)}")
    print(f"Initial - R_OK: {os.access(test_file, os.R_OK)}")
    
    # Remove read permission
    test_file.chmod(0o000)
    
    print(f"After chmod 000: {oct(test_file.stat().st_mode)}")
    print(f"After - R_OK: {os.access(test_file, os.R_OK)}")
    print(f"UID: {os.getuid()}, File UID: {test_file.stat().st_uid}")
    
    # Clean up
    test_file.unlink()


def test_fuse_access():
    """Test os.access through FUSE."""
    # Create directories
    branch = Path("/tmp/test_branch_py")
    mount = Path("/tmp/test_mount_py")
    branch.mkdir(exist_ok=True)
    mount.mkdir(exist_ok=True)
    
    # Start FUSE
    fuse_bin = Path(__file__).parent.parent / "target" / "release" / "mergerfs-rs"
    if not fuse_bin.exists():
        fuse_bin = Path(__file__).parent.parent / "target" / "debug" / "mergerfs-rs"
    
    proc = subprocess.Popen([str(fuse_bin), str(mount), str(branch)])
    time.sleep(1)
    
    try:
        # Create test file
        test_file = mount / "test.txt"
        test_file.write_text("test content")
        
        print(f"\nFUSE Initial mode: {oct(test_file.stat().st_mode)}")
        print(f"FUSE Initial - R_OK: {os.access(test_file, os.R_OK)}")
        
        # Remove read permission
        test_file.chmod(0o000)
        
        print(f"FUSE After chmod 000: {oct(test_file.stat().st_mode)}")
        print(f"FUSE After - R_OK: {os.access(test_file, os.R_OK)}")
        
        # Check underlying file
        branch_file = branch / "test.txt"
        print(f"Branch file mode: {oct(branch_file.stat().st_mode)}")
        
    finally:
        # Clean up
        subprocess.run(["fusermount", "-u", str(mount)], capture_output=True)
        proc.wait()
        import shutil
        shutil.rmtree(branch, ignore_errors=True)
        mount.rmdir()


if __name__ == "__main__":
    print("Testing direct filesystem access:")
    test_direct_access()
    
    print("\nTesting FUSE access:")
    test_fuse_access()