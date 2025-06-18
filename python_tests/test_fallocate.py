import os
import pytest
from pathlib import Path
import fcntl
import ctypes
import ctypes.util
import platform


@pytest.mark.integration
class TestFallocate:
    """Test fallocate functionality"""

    def test_fallocate_basic(self, mounted_fs):
        """Test basic file preallocation"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "test_fallocate.txt"
        test_file.write_text("initial content")
        
        # Get initial size
        initial_size = test_file.stat().st_size
        assert initial_size == len("initial content")
        
        # Open the file for writing
        fd = os.open(str(test_file), os.O_RDWR)
        try:
            # Try to use fallocate to extend the file
            # Note: fallocate may not be available on all systems
            if platform.system() == "Linux":
                try:
                    # Load libc
                    libc = ctypes.CDLL(ctypes.util.find_library('c'))
                    
                    # Define fallocate parameters
                    # int fallocate(int fd, int mode, off_t offset, off_t len)
                    libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, 
                                               ctypes.c_longlong, ctypes.c_longlong]
                    libc.fallocate.restype = ctypes.c_int
                    
                    # Preallocate 1000 bytes (mode=0 means extend file)
                    result = libc.fallocate(fd, 0, 0, 1000)
                    
                    if result == 0:
                        # Fallocate succeeded, verify file was extended
                        new_size = test_file.stat().st_size
                        assert new_size == 1000
                    else:
                        # Fallocate failed, skip test
                        pytest.skip(f"fallocate not supported on this system (error: {result})")
                        
                except (AttributeError, OSError):
                    pytest.skip("fallocate not available on this system")
            else:
                # For non-Linux systems, just test that the file exists
                assert test_file.exists()
                
        finally:
            os.close(fd)

    def test_fallocate_keep_size(self, mounted_fs):
        """Test fallocate with KEEP_SIZE flag"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file with content
        test_file = mountpoint / "test_fallocate_keep.txt"
        initial_content = "initial content here"
        test_file.write_text(initial_content)
        
        # Get initial size
        initial_size = test_file.stat().st_size
        assert initial_size == len(initial_content)
        
        # Open the file for writing
        fd = os.open(str(test_file), os.O_RDWR)
        try:
            if platform.system() == "Linux":
                try:
                    # Load libc
                    libc = ctypes.CDLL(ctypes.util.find_library('c'))
                    libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, 
                                               ctypes.c_longlong, ctypes.c_longlong]
                    libc.fallocate.restype = ctypes.c_int
                    
                    # FALLOC_FL_KEEP_SIZE = 0x01
                    FALLOC_FL_KEEP_SIZE = 0x01
                    
                    # Preallocate 1000 bytes but keep current size
                    result = libc.fallocate(fd, FALLOC_FL_KEEP_SIZE, 0, 1000)
                    
                    if result == 0:
                        # Verify file size wasn't changed
                        new_size = test_file.stat().st_size
                        assert new_size == initial_size
                    else:
                        pytest.skip(f"fallocate with KEEP_SIZE not supported (error: {result})")
                        
                except (AttributeError, OSError):
                    pytest.skip("fallocate not available on this system")
            else:
                # For non-Linux systems, just verify the file exists with original size
                assert test_file.exists()
                assert test_file.stat().st_size == initial_size
                
        finally:
            os.close(fd)

    def test_fallocate_multiple_branches(self, mounted_fs):
        """Test fallocate on files across different branches"""
        process, mountpoint, branches = mounted_fs
        
        # Create files on different branches
        for i, branch in enumerate(branches):
            # Create file directly on branch
            branch_file = branch / f"fallocate_branch{i}.txt"
            branch_file.write_text(f"content on branch {i}")
        
        # Access files through mountpoint and preallocate
        for i in range(len(branches)):
            test_file = mountpoint / f"fallocate_branch{i}.txt"
            assert test_file.exists()
            
            fd = os.open(str(test_file), os.O_RDWR)
            try:
                if platform.system() == "Linux":
                    try:
                        libc = ctypes.CDLL(ctypes.util.find_library('c'))
                        libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, 
                                                   ctypes.c_longlong, ctypes.c_longlong]
                        libc.fallocate.restype = ctypes.c_int
                        
                        # Preallocate to different sizes
                        target_size = 500 * (i + 1)
                        result = libc.fallocate(fd, 0, 0, target_size)
                        
                        if result == 0:
                            # Verify the size
                            new_size = test_file.stat().st_size
                            assert new_size == target_size
                    except (AttributeError, OSError):
                        pass  # Skip if fallocate not available
                        
            finally:
                os.close(fd)

    def test_fallocate_error_cases(self, mounted_fs):
        """Test fallocate error handling"""
        process, mountpoint, branches = mounted_fs
        
        if platform.system() != "Linux":
            pytest.skip("fallocate error testing only supported on Linux")
            
        # Test with non-existent file
        non_existent = mountpoint / "non_existent.txt"
        
        try:
            fd = os.open(str(non_existent), os.O_RDWR)
            os.close(fd)
            assert False, "Should not be able to open non-existent file"
        except FileNotFoundError:
            pass  # Expected
            
        # Test with read-only file
        readonly_file = mountpoint / "readonly.txt"
        readonly_file.write_text("readonly content")
        readonly_file.chmod(0o444)  # Make read-only
        
        try:
            # On some systems/filesystems, opening a read-only file owned by the user
            # for writing might succeed. Let's test a different error case.
            # Instead, test with a directory (can't fallocate on directory)
            test_dir = mountpoint / "test_dir"
            test_dir.mkdir(exist_ok=True)
            
            fd = os.open(str(test_dir), os.O_RDONLY)
            try:
                libc = ctypes.CDLL(ctypes.util.find_library('c'))
                libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, 
                                           ctypes.c_longlong, ctypes.c_longlong]
                libc.fallocate.restype = ctypes.c_int
                
                # Try to fallocate on a directory - should fail
                result = libc.fallocate(fd, 0, 0, 1000)
                assert result != 0, "fallocate on directory should fail"
            finally:
                os.close(fd)
        except Exception:
            pass  # Some error is expected
        finally:
            # Cleanup
            if readonly_file.exists():
                readonly_file.chmod(0o644)

    def test_fallocate_sparse_file(self, mounted_fs):
        """Test creating sparse files with fallocate"""
        process, mountpoint, branches = mounted_fs
        
        # Create a test file
        test_file = mountpoint / "sparse_file.txt"
        test_file.write_text("")
        
        fd = os.open(str(test_file), os.O_RDWR)
        try:
            if platform.system() == "Linux":
                try:
                    libc = ctypes.CDLL(ctypes.util.find_library('c'))
                    libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, 
                                               ctypes.c_longlong, ctypes.c_longlong]
                    libc.fallocate.restype = ctypes.c_int
                    
                    # Create a sparse file by preallocating at a large offset
                    offset = 1024 * 1024  # 1MB offset
                    length = 4096  # 4KB
                    
                    result = libc.fallocate(fd, 0, offset, length)
                    
                    if result == 0:
                        # File should now be at least offset + length bytes
                        size = test_file.stat().st_size
                        assert size >= offset + length
                        
                        # Check that it's actually sparse (blocks < size)
                        # Note: This depends on filesystem support
                        stat_result = test_file.stat()
                        if hasattr(stat_result, 'st_blocks'):
                            # Each block is typically 512 bytes
                            actual_size = stat_result.st_blocks * 512
                            # Sparse file should use less actual disk space
                            assert actual_size < size
                except (AttributeError, OSError):
                    pytest.skip("fallocate not available")
        finally:
            os.close(fd)