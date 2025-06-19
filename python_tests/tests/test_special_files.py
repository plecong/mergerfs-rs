#!/usr/bin/env python3
"""Test special files (FIFOs, device files, sockets)."""

import os
import stat
import time
import pytest
from pathlib import Path
import tempfile
import shutil
import threading
import socket


@pytest.mark.integration
@pytest.mark.skip(reason="Special files FUSE operation not implemented - backend ready but FUSE mknod() missing")
class TestSpecialFiles:
    """Test creation and handling of special files."""
    
    def test_fifo_creation(self, mounted_fs):
        """Test FIFO (named pipe) creation and basic operations."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create FIFO
        fifo_path = mountpoint / "test.fifo"
        os.mkfifo(fifo_path)
        time.sleep(0.1)
        
        # Verify it exists and is a FIFO
        assert fifo_path.exists()
        assert stat.S_ISFIFO(fifo_path.stat().st_mode)
        
        # Should exist in one of the branches
        branch_fifos = []
        for branch in branches:
            branch_fifo = branch / "test.fifo"
            if branch_fifo.exists():
                branch_fifos.append(branch_fifo)
                assert stat.S_ISFIFO(branch_fifo.stat().st_mode)
        
        assert len(branch_fifos) == 1, "FIFO should exist in exactly one branch"
    
    def test_fifo_read_write(self, mounted_fs):
        """Test reading and writing through FIFO."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        fifo_path = mountpoint / "rw.fifo"
        os.mkfifo(fifo_path)
        time.sleep(0.1)
        
        # Test data
        test_data = b"Hello through FIFO!\n"
        received_data = []
        
        # Reader thread
        def reader():
            with open(fifo_path, 'rb') as f:
                data = f.read()
                received_data.append(data)
        
        # Start reader in background
        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        
        # Give reader time to start
        time.sleep(0.1)
        
        # Write to FIFO
        with open(fifo_path, 'wb') as f:
            f.write(test_data)
        
        # Wait for reader to finish
        reader_thread.join(timeout=5)
        
        # Verify data was transferred
        assert len(received_data) == 1
        assert received_data[0] == test_data
    
    def test_fifo_with_policies(self, mounted_fs_with_policy):
        """Test FIFO creation with different create policies."""
        process, mountpoint, branches = mounted_fs_with_policy("mfs")
        
        # Add different amounts of data to branches
        (branches[0] / "data0.bin").write_bytes(b'0' * (30 * 1024 * 1024))
        (branches[1] / "data1.bin").write_bytes(b'1' * (10 * 1024 * 1024))
        (branches[2] / "data2.bin").write_bytes(b'2' * (20 * 1024 * 1024))
        
        time.sleep(0.2)
        
        # Create FIFO - should go to branch 1 (most free space)
        fifo_path = mountpoint / "policy.fifo"
        os.mkfifo(fifo_path)
        time.sleep(0.1)
        
        # Verify it's in the expected branch
        assert (branches[1] / "policy.fifo").exists()
        assert stat.S_ISFIFO((branches[1] / "policy.fifo").stat().st_mode)
        assert not (branches[0] / "policy.fifo").exists()
        assert not (branches[2] / "policy.fifo").exists()
    
    def test_fifo_permissions(self, mounted_fs):
        """Test FIFO permissions."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        fifo_path = mountpoint / "perm.fifo"
        os.mkfifo(fifo_path, mode=0o600)
        time.sleep(0.1)
        
        # Check permissions
        assert oct(fifo_path.stat().st_mode)[-3:] == "600"
        
        # Change permissions
        os.chmod(fifo_path, 0o644)
        time.sleep(0.1)
        
        assert oct(fifo_path.stat().st_mode)[-3:] == "644"
    
    def test_device_files(self, mounted_fs):
        """Test device file creation (requires appropriate permissions)."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Note: Creating device files typically requires root permissions
        # We'll test with mknod but expect permission errors in most cases
        
        try:
            # Try to create a character device (null device as example)
            dev_path = mountpoint / "test_char_dev"
            os.mknod(
                dev_path,
                stat.S_IFCHR | 0o666,
                os.makedev(1, 3)  # Major 1, Minor 3 (null device)
            )
            time.sleep(0.1)
            
            # If successful (running as root), verify
            assert dev_path.exists()
            assert stat.S_ISCHR(dev_path.stat().st_mode)
            
        except PermissionError:
            # Expected in non-root environments
            pytest.skip("Device file creation requires root permissions")
    
    def test_socket_files(self, mounted_fs):
        """Test Unix domain socket creation."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        sock_path = mountpoint / "test.sock"
        
        # Create Unix domain socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            # Remove if exists
            if sock_path.exists():
                sock_path.unlink()
            
            # Bind to create socket file
            sock.bind(str(sock_path))
            time.sleep(0.1)
            
            # Verify socket file exists
            assert sock_path.exists()
            assert stat.S_ISSOCK(sock_path.stat().st_mode)
            
            # Check in branches
            socket_found = False
            for branch in branches:
                branch_sock = branch / "test.sock"
                if branch_sock.exists():
                    assert stat.S_ISSOCK(branch_sock.stat().st_mode)
                    socket_found = True
            
            assert socket_found, "Socket should exist in at least one branch"
            
        finally:
            sock.close()
            if sock_path.exists():
                sock_path.unlink()
    
    def test_special_files_listing(self, mounted_fs):
        """Test that special files appear correctly in directory listings."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create various special files
        special_dir = mountpoint / "special"
        special_dir.mkdir()
        
        # FIFO
        os.mkfifo(special_dir / "pipe.fifo")
        
        # Regular file for comparison
        (special_dir / "regular.txt").write_text("Regular file")
        
        # Socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock_path = special_dir / "unix.sock"
        try:
            sock.bind(str(sock_path))
            
            time.sleep(0.1)
            
            # List directory
            entries = list(special_dir.iterdir())
            assert len(entries) == 3
            
            # Check each entry type
            for entry in entries:
                if entry.name == "pipe.fifo":
                    assert stat.S_ISFIFO(entry.stat().st_mode)
                elif entry.name == "regular.txt":
                    assert entry.is_file()
                elif entry.name == "unix.sock":
                    assert stat.S_ISSOCK(entry.stat().st_mode)
            
        finally:
            sock.close()
    
    def test_special_files_operations(self, mounted_fs):
        """Test operations on special files."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create FIFO
        fifo_path = mountpoint / "ops.fifo"
        os.mkfifo(fifo_path)
        time.sleep(0.1)
        
        # Test stat
        st = fifo_path.stat()
        assert stat.S_ISFIFO(st.st_mode)
        
        # Test chmod
        os.chmod(fifo_path, 0o640)
        time.sleep(0.1)
        assert oct(fifo_path.stat().st_mode)[-3:] == "640"
        
        # Test unlink
        fifo_path.unlink()
        time.sleep(0.1)
        assert not fifo_path.exists()
        
        # Verify removed from branch
        for branch in branches:
            assert not (branch / "ops.fifo").exists()
    
    def test_special_files_edge_cases(self, mounted_fs):
        """Test edge cases with special files."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Test 1: FIFO with long name
        long_name = "f" * 200 + ".fifo"
        long_fifo = mountpoint / long_name
        try:
            os.mkfifo(long_fifo)
            time.sleep(0.1)
            assert long_fifo.exists()
            long_fifo.unlink()
        except OSError as e:
            if e.errno == 36:  # ENAMETOOLONG
                pass  # Expected for very long names
            else:
                raise
        
        # Test 2: Multiple FIFOs in same directory
        fifo_dir = mountpoint / "many_fifos"
        fifo_dir.mkdir()
        
        for i in range(5):
            os.mkfifo(fifo_dir / f"fifo_{i}")
        
        time.sleep(0.1)
        
        # All should exist
        fifos = list(fifo_dir.glob("fifo_*"))
        assert len(fifos) == 5
        for fifo in fifos:
            assert stat.S_ISFIFO(fifo.stat().st_mode)
        
        # Test 3: FIFO in deep directory structure
        deep_path = mountpoint / "a" / "b" / "c" / "d"
        deep_path.mkdir(parents=True)
        
        deep_fifo = deep_path / "deep.fifo"
        os.mkfifo(deep_fifo)
        time.sleep(0.1)
        
        assert deep_fifo.exists()
        assert stat.S_ISFIFO(deep_fifo.stat().st_mode)
    
    def test_special_files_with_branch_failures(self, mounted_fs):
        """Test special file handling when branches become unavailable."""
        if len(mounted_fs) == 4:
            process, mountpoint, branches, _ = mounted_fs
        else:
            process, mountpoint, branches = mounted_fs
        
        # Create FIFO in first branch
        fifo_path = mountpoint / "branch_test.fifo"
        os.mkfifo(fifo_path)
        time.sleep(0.1)
        
        # Find which branch has it
        fifo_branch = None
        for i, branch in enumerate(branches):
            if (branch / "branch_test.fifo").exists():
                fifo_branch = i
                break
        
        assert fifo_branch is not None
        
        # Make that branch read-only
        os.chmod(branches[fifo_branch], 0o555)
        
        try:
            # Should still be able to read/stat
            assert fifo_path.exists()
            assert stat.S_ISFIFO(fifo_path.stat().st_mode)
            
            # But not modify
            with pytest.raises(OSError):
                os.chmod(fifo_path, 0o600)
            
        finally:
            os.chmod(branches[fifo_branch], 0o755)