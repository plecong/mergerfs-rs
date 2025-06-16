#!/usr/bin/env python3
"""
Test to verify comprehensive tracing has been added to FUSE operations.
This test enables debug-level tracing and performs various operations to ensure
tracing spans are properly instrumented.
"""

import os
import subprocess
import tempfile
import time
import signal
from pathlib import Path
import xattr
import pytest


@pytest.mark.integration
class TestTracingVerification:
    """Verify that comprehensive tracing is working for all FUSE operations."""
    
    def test_tracing_enabled_operations(self, temp_branches, temp_mountpoint):
        """Test that all major FUSE operations emit proper tracing spans."""
        # Create temporary branches
        branch1 = temp_branches[0]
        branch2 = temp_branches[1]
        mountpoint = temp_mountpoint
        
        # Start mergerfs with debug tracing enabled
        env = os.environ.copy()
        env['RUST_LOG'] = 'mergerfs_rs=debug,info'
        
        # Mount the filesystem
        cmd = ['cargo', 'run', '--', str(mountpoint), str(branch1), str(branch2)]
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Give it time to mount
        time.sleep(2)
        
        try:
            # Test file creation (create operation)
            test_file = mountpoint / "test_tracing.txt"
            with open(test_file, 'w') as f:
                f.write("Testing tracing")
            
            # Test file write operation
            with open(test_file, 'a') as f:
                f.write(" - additional content")
            
            # Test directory creation (mkdir operation)
            test_dir = mountpoint / "test_dir"
            test_dir.mkdir()
            
            # Test rename operation
            renamed_file = mountpoint / "renamed_file.txt"
            test_file.rename(renamed_file)
            
            # Test chmod operation (setattr)
            os.chmod(renamed_file, 0o644)
            
            # Test xattr operations
            xattr.set(str(renamed_file), 'user.test_attr', b'test_value')
            value = xattr.get(str(renamed_file), 'user.test_attr')
            attrs = xattr.list(str(renamed_file))
            xattr.remove(str(renamed_file), 'user.test_attr')
            
            # Test file removal (unlink)
            renamed_file.unlink()
            
            # Test directory removal (rmdir)
            test_dir.rmdir()
            
        finally:
            # Terminate the process
            process.terminate()
            process.wait(timeout=5)
            
            # Capture stderr which contains tracing output
            _, stderr = process.communicate(timeout=1)
            
            # Verify tracing spans are present
            expected_spans = [
                'fuse::create',
                'file_ops::create_file',
                'fuse::write',
                'file_ops::write_to_file',
                'fuse::mkdir',
                'file_ops::create_directory',
                'fuse::rename',
                'rename::rename',
                'fuse::setattr',
                'metadata::chmod',
                'fuse::setxattr',
                'xattr::set_xattr',
                'fuse::getxattr',
                'xattr::get_xattr',
                'fuse::listxattr',
                'xattr::list_xattr',
                'fuse::removexattr',
                'xattr::remove_xattr',
                'fuse::unlink',
                'file_ops::remove_file',
                'fuse::rmdir',
                'file_ops::remove_directory'
            ]
            
            # Check that each expected span appears in the output
            missing_spans = []
            for span in expected_spans:
                if span not in stderr:
                    missing_spans.append(span)
            
            if missing_spans:
                print("=== STDERR OUTPUT ===")
                print(stderr)
                print("=== MISSING SPANS ===")
                for span in missing_spans:
                    print(f"  - {span}")
                pytest.fail(f"Missing tracing spans: {missing_spans}")
    
    def test_tracing_includes_context(self, temp_branches, temp_mountpoint):
        """Test that tracing includes relevant context like paths, modes, etc."""
        branch1 = temp_branches[0]
        branch2 = temp_branches[1]
        mountpoint = temp_mountpoint
        
        # Start mergerfs with info-level tracing
        env = os.environ.copy()
        env['RUST_LOG'] = 'mergerfs_rs=info'
        
        # Mount the filesystem
        cmd = ['cargo', 'run', '--', str(mountpoint), str(branch1), str(branch2)]
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Give it time to mount
        time.sleep(2)
        
        try:
            # Create a file with specific mode
            test_file = mountpoint / "context_test.txt"
            with open(test_file, 'w') as f:
                f.write("Context test")
            
            # Change permissions to a specific mode
            os.chmod(test_file, 0o755)
            
            # Rename with specific paths
            new_name = mountpoint / "renamed_context.txt"
            test_file.rename(new_name)
            
        finally:
            # Terminate the process
            process.terminate()
            process.wait(timeout=5)
            
            # Capture stderr which contains tracing output
            _, stderr = process.communicate(timeout=1)
            
            # Verify context is included
            assert "context_test.txt" in stderr, "File path not found in tracing"
            assert "755" in stderr or "0755" in stderr, "Mode not found in chmod tracing"
            assert "renamed_context.txt" in stderr, "Rename target not found in tracing"
            
            # Verify timing/performance info is included
            assert "bytes" in stderr, "Byte count information not found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])