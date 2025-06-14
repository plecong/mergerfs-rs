#!/bin/bash
# setup_tmpfs.sh - Create tmpfs mounts for mergerfs-rs Python integration testing
#
# This script creates multiple tmpfs filesystems with different size limits
# to enable testing of space-based policies (mfs, lfs) with predictable behavior.
#
# Usage: sudo ./setup_tmpfs.sh
#
# The script will create tmpfs mounts at:
#   /tmp/mergerfs_test_10mb   - 10MB limit
#   /tmp/mergerfs_test_50mb   - 50MB limit
#   /tmp/mergerfs_test_100mb  - 100MB limit
#   /tmp/mergerfs_test_200mb  - 200MB limit
#   /tmp/mergerfs_test_500mb  - 500MB limit

set -e

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run as root (use sudo)"
   echo "Usage: sudo $0"
   exit 1
fi

# Configuration
MOUNT_PREFIX="/tmp/mergerfs_test"
declare -a SIZES=(10 50 100 200 500)

echo "Setting up tmpfs mounts for mergerfs-rs testing..."
echo "================================================"

# Create and mount tmpfs filesystems
for size in "${SIZES[@]}"; do
    mount_point="${MOUNT_PREFIX}_${size}mb"
    
    # Check if already mounted
    if mountpoint -q "$mount_point" 2>/dev/null; then
        echo "⚠️  $mount_point is already mounted, skipping..."
        continue
    fi
    
    # Create mount point directory
    mkdir -p "$mount_point"
    
    # Mount tmpfs with size limit
    if mount -t tmpfs -o size="${size}M" tmpfs "$mount_point"; then
        # Set permissions to allow non-root users to write
        chmod 777 "$mount_point"
        echo "✓ Created tmpfs at $mount_point with ${size}MB limit"
        
        # Create a marker file to identify this as a test tmpfs
        echo "${size}MB tmpfs for mergerfs-rs testing" > "$mount_point/.mergerfs_test_marker"
    else
        echo "✗ Failed to create tmpfs at $mount_point"
        exit 1
    fi
done

echo ""
echo "✅ All tmpfs mounts created successfully!"
echo ""
echo "To verify the mounts, run: df -h | grep mergerfs_test"
echo "To cleanup when done, run: sudo ./cleanup_tmpfs.sh"
echo ""
echo "You can now run the Python integration tests."