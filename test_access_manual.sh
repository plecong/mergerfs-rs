#!/bin/bash
set -ex

# Create test directories
mkdir -p /tmp/test_branch1 /tmp/test_mount

# Mount mergerfs
./target/release/mergerfs-rs /tmp/test_mount /tmp/test_branch1 &
FUSE_PID=$!
sleep 1

# Create a test file
echo "test content" > /tmp/test_mount/test.txt

# Check initial permissions
echo "Initial permissions:"
ls -l /tmp/test_mount/test.txt
ls -l /tmp/test_branch1/test.txt

# Remove all permissions
chmod 000 /tmp/test_mount/test.txt

echo "After chmod 000:"
ls -l /tmp/test_mount/test.txt
ls -l /tmp/test_branch1/test.txt

# Test access
echo "Testing access (should all fail):"
if [ -r /tmp/test_mount/test.txt ]; then echo "READ: ALLOWED (WRONG!)"; else echo "READ: DENIED (correct)"; fi
if [ -w /tmp/test_mount/test.txt ]; then echo "WRITE: ALLOWED (WRONG!)"; else echo "WRITE: DENIED (correct)"; fi
if [ -x /tmp/test_mount/test.txt ]; then echo "EXEC: ALLOWED (WRONG!)"; else echo "EXEC: DENIED (correct)"; fi

# Clean up
umount /tmp/test_mount || fusermount -u /tmp/test_mount
kill $FUSE_PID 2>/dev/null || true
rm -rf /tmp/test_branch1 /tmp/test_mount