use std::path::Path;
use std::fs;
use tempfile::TempDir;

fn main() {
    let temp_dir = TempDir::new().unwrap();
    let fifo_path = temp_dir.path().join("test.fifo");
    
    // Create a FIFO
    nix::unistd::mkfifo(&fifo_path, nix::sys::stat::Mode::from_bits_truncate(0o644)).unwrap();
    
    // Get metadata
    let metadata = fs::symlink_metadata(&fifo_path).unwrap();
    
    // Check file type
    if metadata.is_dir() {
        println\!("Directory");
    } else if metadata.is_symlink() {
        println\!("Symlink");
    } else {
        // Check for special file types on Unix platforms
        #[cfg(unix)]
        {
            use std::os::unix::fs::FileTypeExt;
            let ft = metadata.file_type();
            if ft.is_fifo() {
                println\!("NamedPipe");
            } else if ft.is_char_device() {
                println\!("CharDevice");
            } else if ft.is_block_device() {
                println\!("BlockDevice");
            } else if ft.is_socket() {
                println\!("Socket");
            } else {
                println\!("RegularFile");
            }
        }
        #[cfg(not(unix))]
        {
            println\!("RegularFile");
        }
    }
}
EOF < /dev/null