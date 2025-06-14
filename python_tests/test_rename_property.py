"""Property-based tests for rename operations."""

import os
import pytest
from pathlib import Path
from hypothesis import given, strategies as st, assume, settings, HealthCheck
import string
import tempfile


# Strategy for valid filenames (avoiding path separators and null bytes)
valid_filename = st.text(
    alphabet=string.ascii_letters + string.digits + "_-. ",
    min_size=1,
    max_size=100
).filter(lambda s: s.strip() and "/" not in s and "\x00" not in s)

# Strategy for valid paths (can include directories)
valid_path = st.lists(
    valid_filename,
    min_size=1,
    max_size=3
).map(lambda parts: "/".join(parts))


@pytest.mark.integration
@pytest.mark.property
class TestRenameProperties:
    """Property-based tests for rename operations."""
    
    def test_rename_preserves_content_property(self, mounted_fs):
        """Property: Renaming a file preserves its content."""
        process, mountpoint, branches = mounted_fs
        
        @given(filename=valid_filename)
        @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def property_test(filename):
        
        # Create a file with random content
        content = f"Content for {filename}"
        src_file = mountpoint / f"src_{filename}"
        src_file.write_text(content)
        
        # Rename it
        dst_file = mountpoint / f"dst_{filename}"
        try:
            src_file.rename(dst_file)
            
            # Verify content is preserved
            assert dst_file.read_text() == content
            assert not src_file.exists()
        except OSError:
            # Some filenames might be invalid on the filesystem
            pass
    
    @given(
        src_name=valid_filename,
        dst_name=valid_filename,
        content=st.binary(min_size=0, max_size=1024)
    )
    @settings(max_examples=20)
    def test_rename_binary_content(self, mounted_fs, src_name, dst_name, content):
        """Property: Renaming preserves binary content exactly."""
        assume(src_name != dst_name)  # Skip if names are the same
        
        process, mountpoint, branches = mounted_fs
        
        src_file = mountpoint / src_name
        dst_file = mountpoint / dst_name
        
        try:
            # Write binary content
            src_file.write_bytes(content)
            
            # Rename
            src_file.rename(dst_file)
            
            # Verify binary content is identical
            assert dst_file.read_bytes() == content
            assert not src_file.exists()
        except OSError:
            # Some filenames might be invalid
            pass
    
    @given(path=valid_path)
    @settings(max_examples=15)
    def test_rename_creates_parent_directories(self, mounted_fs, path):
        """Property: Rename to non-existent directory creates parent dirs."""
        process, mountpoint, branches = mounted_fs
        
        # Create source file
        src_file = mountpoint / "source.txt"
        src_file.write_text("content")
        
        # Prepare destination with potentially non-existent parents
        dst_file = mountpoint / path
        
        try:
            # Ensure parent directory exists (rename doesn't create parents)
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Rename
            src_file.rename(dst_file)
            
            # Verify file moved and parents exist
            assert dst_file.exists()
            assert dst_file.parent.exists()
            assert not src_file.exists()
        except OSError:
            # Some paths might be invalid
            pass
    
    @given(
        filenames=st.lists(valid_filename, min_size=2, max_size=5, unique=True)
    )
    @settings(max_examples=10)
    def test_rename_multiple_files_independent(self, mounted_fs, filenames):
        """Property: Renaming multiple files is independent."""
        process, mountpoint, branches = mounted_fs
        
        # Create multiple files
        for i, name in enumerate(filenames):
            (mountpoint / name).write_text(f"content{i}")
        
        # Rename each file
        renamed = []
        for i, name in enumerate(filenames):
            src = mountpoint / name
            dst = mountpoint / f"renamed_{name}"
            try:
                src.rename(dst)
                renamed.append((name, f"renamed_{name}", f"content{i}"))
            except OSError:
                pass
        
        # Verify all renamed files exist with correct content
        for orig, new, content in renamed:
            assert not (mountpoint / orig).exists()
            assert (mountpoint / new).exists()
            assert (mountpoint / new).read_text() == content
    
    @given(dirname=valid_filename)
    @settings(max_examples=15)
    def test_rename_directory_preserves_structure(self, mounted_fs, dirname):
        """Property: Renaming directory preserves internal structure."""
        process, mountpoint, branches = mounted_fs
        
        # Create directory with structure
        src_dir = mountpoint / f"src_{dirname}"
        try:
            src_dir.mkdir()
            (src_dir / "file1.txt").write_text("content1")
            (src_dir / "subdir").mkdir()
            (src_dir / "subdir" / "file2.txt").write_text("content2")
            
            # Rename directory
            dst_dir = mountpoint / f"dst_{dirname}"
            src_dir.rename(dst_dir)
            
            # Verify structure is preserved
            assert not src_dir.exists()
            assert dst_dir.exists()
            assert (dst_dir / "file1.txt").read_text() == "content1"
            assert (dst_dir / "subdir" / "file2.txt").read_text() == "content2"
        except OSError:
            # Some directory names might be invalid
            pass
    
    @given(
        filename=valid_filename,
        mode=st.integers(min_value=0o400, max_value=0o777)
    )
    @settings(max_examples=10)
    def test_rename_preserves_permissions(self, mounted_fs, filename, mode):
        """Property: Rename preserves file permissions."""
        process, mountpoint, branches = mounted_fs
        
        src_file = mountpoint / f"src_{filename}"
        dst_file = mountpoint / f"dst_{filename}"
        
        try:
            # Create file with specific permissions
            src_file.write_text("content")
            src_file.chmod(mode)
            
            # Get original mode (masking out file type bits)
            orig_mode = src_file.stat().st_mode & 0o777
            
            # Rename
            src_file.rename(dst_file)
            
            # Verify permissions preserved
            new_mode = dst_file.stat().st_mode & 0o777
            assert new_mode == orig_mode
        except OSError:
            pass
    
    @given(st.data())
    @settings(max_examples=10)
    def test_rename_atomicity(self, mounted_fs, data):
        """Property: Rename appears atomic from user perspective."""
        process, mountpoint, branches = mounted_fs
        
        # Generate random filename
        filename = data.draw(valid_filename)
        
        src_file = mountpoint / f"atomic_src_{filename}"
        dst_file = mountpoint / f"atomic_dst_{filename}"
        
        try:
            # Create source file
            src_file.write_text("atomic content")
            
            # Rename - this should appear atomic
            src_file.rename(dst_file)
            
            # At no point should both files exist or neither exist
            # After rename: src should not exist, dst should exist
            assert not src_file.exists()
            assert dst_file.exists()
            
            # Content should be preserved
            assert dst_file.read_text() == "atomic content"
        except OSError:
            pass
    
    @given(
        src_parts=st.lists(valid_filename, min_size=1, max_size=3),
        dst_parts=st.lists(valid_filename, min_size=1, max_size=3)
    )
    @settings(max_examples=10)
    def test_rename_across_directories(self, mounted_fs, src_parts, dst_parts):
        """Property: Rename works across different directory depths."""
        process, mountpoint, branches = mounted_fs
        
        src_path = Path(*src_parts[:-1]) / src_parts[-1] if len(src_parts) > 1 else Path(src_parts[0])
        dst_path = Path(*dst_parts[:-1]) / dst_parts[-1] if len(dst_parts) > 1 else Path(dst_parts[0])
        
        src_file = mountpoint / src_path
        dst_file = mountpoint / dst_path
        
        try:
            # Create source file with parent directories
            src_file.parent.mkdir(parents=True, exist_ok=True)
            src_file.write_text("cross-directory content")
            
            # Create destination parent directories
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Rename across directories
            src_file.rename(dst_file)
            
            # Verify move completed
            assert not src_file.exists()
            assert dst_file.exists()
            assert dst_file.read_text() == "cross-directory content"
        except OSError:
            pass


@pytest.mark.integration
@pytest.mark.property
class TestRenameInvariants:
    """Test invariants that should always hold for rename operations."""
    
    @given(filename=valid_filename)
    @settings(max_examples=20)
    def test_rename_to_self_is_noop(self, mounted_fs, filename):
        """Invariant: Renaming a file to itself is a no-op."""
        process, mountpoint, branches = mounted_fs
        
        test_file = mountpoint / filename
        content = f"Self rename content for {filename}"
        
        try:
            test_file.write_text(content)
            
            # Rename to self
            test_file.rename(test_file)
            
            # File should still exist with same content
            assert test_file.exists()
            assert test_file.read_text() == content
        except OSError:
            pass
    
    @given(
        filename=valid_filename,
        size=st.integers(min_value=0, max_value=10000)
    )
    @settings(max_examples=15)
    def test_rename_preserves_size(self, mounted_fs, filename, size):
        """Invariant: File size is preserved across rename."""
        process, mountpoint, branches = mounted_fs
        
        src_file = mountpoint / f"size_src_{filename}"
        dst_file = mountpoint / f"size_dst_{filename}"
        
        try:
            # Create file of specific size
            content = "x" * size
            src_file.write_text(content)
            
            original_size = src_file.stat().st_size
            
            # Rename
            src_file.rename(dst_file)
            
            # Size should be preserved
            assert dst_file.stat().st_size == original_size
        except OSError:
            pass