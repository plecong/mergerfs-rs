#!/bin/bash
# Script to run Python tests from the root of the mergerfs-rs workspace

# Get the directory where this script is located (workspace root)
WORKSPACE_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_TESTS_DIR="${WORKSPACE_ROOT}/python_tests"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right place
if [ ! -f "${WORKSPACE_ROOT}/Cargo.toml" ]; then
    print_error "This script must be run from the mergerfs-rs workspace root"
    exit 1
fi

# Check if python_tests directory exists
if [ ! -d "${PYTHON_TESTS_DIR}" ]; then
    print_error "Python tests directory not found at ${PYTHON_TESTS_DIR}"
    exit 1
fi

# Build the Rust project first
print_info "Building mergerfs-rs..."
cargo build
if [ $? -ne 0 ]; then
    print_error "Failed to build mergerfs-rs"
    exit 1
fi

# Change to python_tests directory
cd "${PYTHON_TESTS_DIR}"

# Check if uv is available
if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Please install it first."
    exit 1
fi

# Sync dependencies
print_info "Syncing Python dependencies..."
uv sync

# Default to running all tests
TEST_ARGS="$@"
if [ -z "$TEST_ARGS" ]; then
    TEST_ARGS="--test-type all"
fi

# Run tests
print_info "Running Python tests..."
print_info "Arguments: $TEST_ARGS"
echo

# Check if we're using run_tests.py or pytest directly
if [[ "$1" == *".py" ]] || [[ "$1" == "-"* ]] || [[ "$1" == "tests/"* ]]; then
    # Direct pytest invocation
    uv run pytest $TEST_ARGS
else
    # Use run_tests.py
    uv run python run_tests.py $TEST_ARGS
fi

# Return to original directory
cd "${WORKSPACE_ROOT}"