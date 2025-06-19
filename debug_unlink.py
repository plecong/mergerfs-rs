#!/usr/bin/env python3
import os
import tempfile
import subprocess
import time
import shutil

# Create test directories
test_dir = tempfile.mkdtemp(prefix="debug_unlink_")
branch0 = os.path.join(test_dir, "branch0")
mount = os.path.join(test_dir, "mount")

os.makedirs(branch0)
os.makedirs(mount)

print(f"Test dir: {test_dir}")

# Start mergerfs
cmd = ["/home/plecong/mergerfs-rs/target/release/mergerfs-rs", mount, branch0]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(1)

try:
    # Create original file
    original_path = os.path.join(mount, "original.txt")
    with open(original_path, "w") as f:
        f.write("test content")
    
    print("1. Created original file")
    print(f"   Branch0 contents: {os.listdir(branch0)}")
    
    # Create hard link
    link_path = os.path.join(mount, "link.txt")
    os.link(original_path, link_path)
    
    print("2. Created hard link")
    print(f"   Mount contents: {os.listdir(mount)}")
    print(f"   Branch0 contents: {os.listdir(branch0)}")
    
    # Check inodes and nlink before unlink
    orig_stat = os.stat(original_path)
    link_stat = os.stat(link_path)
    print(f"3. Before unlink:")
    print(f"   original.txt: inode={orig_stat.st_ino}, nlink={orig_stat.st_nlink}")
    print(f"   link.txt: inode={link_stat.st_ino}, nlink={link_stat.st_nlink}")
    
    # Check underlying filesystem
    branch_orig = os.path.join(branch0, "original.txt")
    branch_link = os.path.join(branch0, "link.txt")
    if os.path.exists(branch_orig):
        branch_orig_stat = os.stat(branch_orig)
        print(f"   branch0/original.txt: inode={branch_orig_stat.st_ino}, nlink={branch_orig_stat.st_nlink}")
    if os.path.exists(branch_link):
        branch_link_stat = os.stat(branch_link)
        print(f"   branch0/link.txt: inode={branch_link_stat.st_ino}, nlink={branch_link_stat.st_nlink}")
    
    # Unlink original
    os.unlink(original_path)
    print("4. Unlinked original.txt")
    
    time.sleep(0.2)
    
    # Check what remains
    print(f"   Mount contents: {[f for f in os.listdir(mount) if not f.startswith('.')]}")
    print(f"   Branch0 contents: {os.listdir(branch0)}")
    
    # Check if link still works
    if os.path.exists(link_path):
        link_stat_after = os.stat(link_path)
        print(f"   link.txt after unlink: inode={link_stat_after.st_ino}, nlink={link_stat_after.st_nlink}")
        try:
            content = open(link_path).read()
            print(f"   link.txt content: '{content}'")
        except Exception as e:
            print(f"   Error reading link.txt: {e}")
    else:
        print("   link.txt no longer exists!")
        
    # Check underlying filesystem
    if os.path.exists(branch_link):
        branch_link_stat_after = os.stat(branch_link)
        print(f"   branch0/link.txt after: inode={branch_link_stat_after.st_ino}, nlink={branch_link_stat_after.st_nlink}")
    else:
        print("   branch0/link.txt no longer exists!")

finally:
    # Cleanup
    proc.terminate()
    time.sleep(0.5)
    subprocess.run(["fusermount", "-u", mount], capture_output=True)
    shutil.rmtree(test_dir)