#!/bin/bash

# Test script for hard link functionality

set -e

# Create temporary directories
TEMP_DIR=$(mktemp -d)
BRANCH1="$TEMP_DIR/branch1"
BRANCH2="$TEMP_DIR/branch2"
MOUNT_POINT="$TEMP_DIR/mount"

mkdir -p "$BRANCH1" "$BRANCH2" "$MOUNT_POINT"

echo "Setting up test environment..."
echo "Branch 1: $BRANCH1"
echo "Branch 2: $BRANCH2"
echo "Mount point: $MOUNT_POINT"

# Build the project
echo "Building mergerfs-rs..."
cargo build --release

# Mount the filesystem
echo "Mounting filesystem..."
./target/release/mergerfs-rs "$MOUNT_POINT" "$BRANCH1" "$BRANCH2" &
MOUNT_PID=$!

# Wait for mount
sleep 2

# Create a test file
echo "Creating test file..."
echo "Hello, World!" > "$MOUNT_POINT/test.txt"

# Create a hard link
echo "Creating hard link..."
ln "$MOUNT_POINT/test.txt" "$MOUNT_POINT/link.txt"

# Verify the hard link
echo "Verifying hard link..."
if [ -f "$MOUNT_POINT/link.txt" ]; then
    echo "✓ Hard link created successfully"
    
    # Check content
    CONTENT=$(cat "$MOUNT_POINT/link.txt")
    if [ "$CONTENT" = "Hello, World!" ]; then
        echo "✓ Content matches"
    else
        echo "✗ Content mismatch"
    fi
    
    # Check inode (on Linux)
    if command -v stat >/dev/null 2>&1; then
        INODE1=$(stat -c %i "$MOUNT_POINT/test.txt" 2>/dev/null || stat -f %i "$MOUNT_POINT/test.txt")
        INODE2=$(stat -c %i "$MOUNT_POINT/link.txt" 2>/dev/null || stat -f %i "$MOUNT_POINT/link.txt")
        if [ "$INODE1" = "$INODE2" ]; then
            echo "✓ Same inode ($INODE1)"
        else
            echo "✗ Different inodes: $INODE1 vs $INODE2"
        fi
    fi
else
    echo "✗ Hard link not created"
fi

# Clean up
echo "Cleaning up..."
fusermount -u "$MOUNT_POINT" 2>/dev/null || umount "$MOUNT_POINT" 2>/dev/null || true
wait $MOUNT_PID 2>/dev/null || true
rm -rf "$TEMP_DIR"

echo "Test complete!"