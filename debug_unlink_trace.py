#!/usr/bin/env python3
import os
import tempfile
import subprocess
import time
import shutil

# Create test directories
test_dir = tempfile.mkdtemp(prefix="debug_unlink_trace_")
branch0 = os.path.join(test_dir, "branch0")
mount = os.path.join(test_dir, "mount")

os.makedirs(branch0)
os.makedirs(mount)

print(f"Test dir: {test_dir}")

# Start mergerfs with debug logging
env = os.environ.copy()
env['RUST_LOG'] = 'mergerfs_rs=debug'
cmd = ["/home/plecong/mergerfs-rs/target/release/mergerfs-rs", mount, branch0]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
time.sleep(1)

try:
    # Create original file
    original_path = os.path.join(mount, "original.txt")
    with open(original_path, "w") as f:
        f.write("test content")
    
    print("1. Created original file")
    
    # Create hard link
    link_path = os.path.join(mount, "link.txt")
    os.link(original_path, link_path)
    
    print("2. Created hard link")
    
    # Unlink original
    os.unlink(original_path)
    print("3. Unlinked original.txt")
    
    time.sleep(0.2)
    
    # Try to stat link.txt - this should trigger getattr with debug logs
    print("4. Calling stat on link.txt...")
    try:
        link_stat = os.stat(link_path)
        print(f"   stat successful: inode={link_stat.st_ino}, nlink={link_stat.st_nlink}")
    except Exception as e:
        print(f"   stat failed: {e}")
        
    # Try to read link.txt
    print("5. Calling read on link.txt...")
    try:
        with open(link_path, 'r') as f:
            content = f.read()
        print(f"   read successful: '{content}'")
    except Exception as e:
        print(f"   read failed: {e}")

finally:
    # Cleanup
    proc.terminate()
    time.sleep(0.5)
    subprocess.run(["fusermount", "-u", mount], capture_output=True)
    
    # Print stderr for debug logs
    _, stderr = proc.communicate()
    print("\n=== Debug logs ===")
    print(stderr.decode())
    
    shutil.rmtree(test_dir)