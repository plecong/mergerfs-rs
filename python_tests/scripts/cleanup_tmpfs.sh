#!/bin/bash
# cleanup_tmpfs.sh - Remove tmpfs mounts created for mergerfs-rs testing
#
# This script unmounts and removes the tmpfs filesystems created by setup_tmpfs.sh
#
# Usage: sudo ./cleanup_tmpfs.sh

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

echo "Cleaning up tmpfs mounts for mergerfs-rs testing..."
echo "=================================================="

# Track results
unmounted=0
errors=0

# Unmount and remove tmpfs filesystems
for size in "${SIZES[@]}"; do
    mount_point="${MOUNT_PREFIX}_${size}mb"
    
    # Check if mount point exists
    if [[ ! -d "$mount_point" ]]; then
        continue
    fi
    
    # Check if it's mounted and is our test tmpfs
    if mountpoint -q "$mount_point" 2>/dev/null; then
        # Verify it's our test tmpfs by checking for marker file
        if [[ -f "$mount_point/.mergerfs_test_marker" ]]; then
            # Attempt to unmount
            if umount "$mount_point" 2>/dev/null; then
                echo "✓ Unmounted $mount_point"
                unmounted=$((unmounted + 1))
            else
                # Force unmount if regular unmount fails
                echo "⚠️  Regular unmount failed for $mount_point, trying force unmount..."
                if umount -f "$mount_point" 2>/dev/null; then
                    echo "✓ Force unmounted $mount_point"
                    unmounted=$((unmounted + 1))
                else
                    echo "✗ Failed to unmount $mount_point (may be in use)"
                    errors=$((errors + 1))
                    continue
                fi
            fi
        else
            echo "⚠️  $mount_point is mounted but not a test tmpfs, skipping..."
            continue
        fi
    fi
    
    # Remove the mount point directory
    if rmdir "$mount_point" 2>/dev/null; then
        echo "✓ Removed directory $mount_point"
    else
        # Directory might not be empty or might not exist
        if [[ -d "$mount_point" ]]; then
            echo "⚠️  Could not remove $mount_point (directory not empty?)"
        fi
    fi
done

echo ""
echo "Cleanup Summary:"
echo "================"
echo "✓ Unmounted: $unmounted filesystems"

if [[ $errors -gt 0 ]]; then
    echo "✗ Errors: $errors filesystems could not be unmounted"
    echo ""
    echo "If filesystems are in use, try:"
    echo "  1. Stop any processes using the mount points"
    echo "  2. Run: lsof | grep mergerfs_test"
    echo "  3. Kill any processes and retry this script"
    exit 1
else
    echo ""
    echo "✅ All test tmpfs mounts cleaned up successfully!"
fi