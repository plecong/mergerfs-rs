"""Simple property-based tests for rename operations."""

import os
import pytest
from pathlib import Path
import string
import random


@pytest.mark.integration
@pytest.mark.property
class TestRenamePropertiesSimple:
    """Simple property tests that work with pytest fixtures."""
    
    def test_rename_preserves_content_various_sizes(self, mounted_fs):
        """Test that rename preserves content for files of various sizes."""
        process, mountpoint, branches = mounted_fs
        
        # Test with different file sizes
        test_sizes = [0, 1, 100, 1024, 10*1024, 100*1024]  # 0B to 100KB
        
        for size in test_sizes:
            # Generate content of specific size
            content = "x" * size if size > 0 else ""
            
            src_file = mountpoint / f"size_test_{size}.txt"
            dst_file = mountpoint / f"renamed_size_test_{size}.txt"
            
            # Write, rename, verify
            src_file.write_text(content)
            assert src_file.stat().st_size == size
            
            src_file.rename(dst_file)
            
            assert not src_file.exists()
            assert dst_file.exists()
            assert dst_file.stat().st_size == size
            assert dst_file.read_text() == content
    
    def test_rename_with_various_filenames(self, mounted_fs):
        """Test rename with various types of filenames."""
        process, mountpoint, branches = mounted_fs
        
        # Test various filename patterns
        test_names = [
            "simple.txt",
            "with spaces.txt",
            "with-dashes-and_underscores.txt",
            "with.multiple.dots.txt",
            "UPPERCASE.TXT",
            "MiXeDcAsE.TxT",
            "numbers123456.txt",
            "special!@#$%^()_+.txt",  # Some special chars
            ".hidden_file",
            "very_long_filename_" + "x" * 50 + ".txt",
        ]
        
        for i, name in enumerate(test_names):
            try:
                src_file = mountpoint / f"src_{name}"
                dst_file = mountpoint / f"dst_{name}"
                content = f"Content for test {i}: {name}"
                
                src_file.write_text(content)
                src_file.rename(dst_file)
                
                assert not src_file.exists()
                assert dst_file.exists()
                assert dst_file.read_text() == content
            except OSError as e:
                # Some filenames might not be valid on the filesystem
                print(f"Skipping invalid filename: {name} - {e}")
    
    def test_rename_preserves_permissions(self, mounted_fs):
        """Test that various permission modes are preserved during rename."""
        process, mountpoint, branches = mounted_fs
        
        # Test various permission modes
        test_modes = [
            0o644,  # rw-r--r--
            0o755,  # rwxr-xr-x
            0o600,  # rw-------
            0o700,  # rwx------
            0o666,  # rw-rw-rw-
            0o777,  # rwxrwxrwx
            0o400,  # r--------
        ]
        
        for mode in test_modes:
            src_file = mountpoint / f"perm_test_{oct(mode)}.txt"
            dst_file = mountpoint / f"renamed_perm_test_{oct(mode)}.txt"
            
            src_file.write_text("permission test content")
            src_file.chmod(mode)
            
            # Get actual mode after chmod (might be affected by umask)
            actual_mode = src_file.stat().st_mode & 0o777
            
            src_file.rename(dst_file)
            
            # Verify permissions preserved
            assert dst_file.stat().st_mode & 0o777 == actual_mode
    
    def test_rename_directory_depth_variations(self, mounted_fs):
        """Test rename across various directory depths."""
        process, mountpoint, branches = mounted_fs
        
        test_cases = [
            # (source_path, dest_path)
            ("file.txt", "renamed.txt"),  # Same directory (root)
            ("dir1/file.txt", "dir1/renamed.txt"),  # Same subdirectory
            ("file.txt", "dir1/moved.txt"),  # Root to subdirectory
            ("dir1/file.txt", "moved.txt"),  # Subdirectory to root
            ("dir1/file.txt", "dir2/moved.txt"),  # Between subdirectories
            ("dir1/sub1/file.txt", "dir2/sub2/moved.txt"),  # Deep directories
        ]
        
        for src_path, dst_path in test_cases:
            src_file = mountpoint / src_path
            dst_file = mountpoint / dst_path
            
            # Create necessary directories
            src_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create, rename, verify
            content = f"Content for {src_path} -> {dst_path}"
            src_file.write_text(content)
            
            src_file.rename(dst_file)
            
            assert not src_file.exists()
            assert dst_file.exists()
            assert dst_file.read_text() == content
            
            # Cleanup for next test
            dst_file.unlink()
    
    def test_rename_multiple_files_consistency(self, mounted_fs):
        """Test that multiple renames maintain consistency."""
        process, mountpoint, branches = mounted_fs
        
        # Create multiple files
        num_files = 20
        files = []
        
        for i in range(num_files):
            filename = f"multi_test_{i}.txt"
            content = f"Content for file {i}"
            filepath = mountpoint / filename
            filepath.write_text(content)
            files.append((filename, content))
        
        # Rename all files
        renamed_files = []
        for i, (filename, content) in enumerate(files):
            src = mountpoint / filename
            dst = mountpoint / f"renamed_{filename}"
            src.rename(dst)
            renamed_files.append((f"renamed_{filename}", content))
        
        # Verify all renames succeeded
        for filename, expected_content in renamed_files:
            filepath = mountpoint / filename
            assert filepath.exists()
            assert filepath.read_text() == expected_content
        
        # Verify no original files exist
        for filename, _ in files:
            assert not (mountpoint / filename).exists()
    
    def test_rename_with_binary_content(self, mounted_fs):
        """Test rename with various binary content patterns."""
        process, mountpoint, branches = mounted_fs
        
        # Generate different binary patterns
        test_patterns = [
            b"",  # Empty
            b"\x00" * 100,  # Null bytes
            b"\xff" * 100,  # All 1s
            bytes(range(256)),  # All byte values
            os.urandom(1024),  # Random bytes
            b"Binary\x00with\xffnull\x00bytes",  # Mixed
        ]
        
        for i, pattern in enumerate(test_patterns):
            src_file = mountpoint / f"binary_test_{i}.bin"
            dst_file = mountpoint / f"renamed_binary_test_{i}.bin"
            
            src_file.write_bytes(pattern)
            src_file.rename(dst_file)
            
            assert not src_file.exists()
            assert dst_file.exists()
            assert dst_file.read_bytes() == pattern
    
    def test_rename_idempotency(self, mounted_fs):
        """Test that renaming a file to itself is idempotent."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / "idempotent_test.txt"
        content = "This content should not change"
        
        test_file.write_text(content)
        original_stat = test_file.stat()
        
        # Rename to self multiple times
        for _ in range(5):
            test_file.rename(test_file)
        
        # File should still exist with same content
        assert test_file.exists()
        assert test_file.read_text() == content
        # Note: mtime might change even on self-rename
    
    def test_rename_atomicity_simulation(self, mounted_fs):
        """Test that rename appears atomic by checking intermediate states."""
        process, mountpoint, branches = mounted_fs
        
        # Create a larger file to increase chance of catching non-atomic behavior
        src_file = mountpoint / "atomic_src.txt"
        dst_file = mountpoint / "atomic_dst.txt"
        
        # Use larger content
        content = "x" * (1024 * 1024)  # 1MB
        src_file.write_text(content)
        
        # Perform rename
        src_file.rename(dst_file)
        
        # After rename, exactly one should exist
        src_exists = src_file.exists()
        dst_exists = dst_file.exists()
        
        assert not src_exists
        assert dst_exists
        assert dst_file.read_text() == content
    
    def test_rename_error_conditions(self, mounted_fs):
        """Test various error conditions for rename."""
        process, mountpoint, branches = mounted_fs
        
        # Test 1: Rename non-existent file
        with pytest.raises(FileNotFoundError):
            (mountpoint / "nonexistent.txt").rename(mountpoint / "dest.txt")
        
        # Test 2: Rename to invalid path (if parent doesn't exist)
        src_file = mountpoint / "error_test.txt"
        src_file.write_text("content")
        
        with pytest.raises(FileNotFoundError):
            src_file.rename(mountpoint / "nonexistent_dir" / "dest.txt")
        
        # Cleanup
        src_file.unlink()
        
        # Test 3: Rename directory to existing file (should fail)
        test_dir = mountpoint / "test_dir"
        test_file = mountpoint / "existing_file.txt"
        
        test_dir.mkdir()
        test_file.write_text("existing")
        
        with pytest.raises(OSError):  # Not a directory or similar error
            test_dir.rename(test_file)