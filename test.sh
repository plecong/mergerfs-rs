#!/bin/bash
# Convenient test runner script for mergerfs-rs

# Get the directory where this script is located (workspace root)
WORKSPACE_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print usage
usage() {
    echo -e "${GREEN}mergerfs-rs test runner${NC}"
    echo
    echo "Usage: $0 [command] [options]"
    echo
    echo "Commands:"
    echo "  unit                    Run Rust unit tests"
    echo "  integration, int        Run Python integration tests"
    echo "  all                     Run all tests (Rust + Python)"
    echo "  mfs                     Run MFS policy tests"
    echo "  policy                  Run all policy tests"
    echo "  specific <test>         Run a specific test file or test case"
    echo "  debug                   Run with debug logging (RUST_LOG=debug)"
    echo "  clean                   Clean build artifacts and temp files"
    echo
    echo "Examples:"
    echo "  $0 unit                                          # Run Rust unit tests"
    echo "  $0 int                                           # Run Python integration tests"
    echo "  $0 all                                           # Run all tests"
    echo "  $0 mfs                                           # Run MFS policy tests"
    echo "  $0 specific test_mfs_policy.py                   # Run specific test file"
    echo "  $0 specific test_mfs_policy.py::TestMFSPolicyBasic::test_mfs_selects_empty_branch_over_populated"
    echo "  $0 debug mfs                                     # Run MFS tests with debug logging"
    echo
}

# Parse command
if [ $# -eq 0 ]; then
    usage
    exit 0
fi

COMMAND=$1
shift

# Handle commands
case $COMMAND in
    unit)
        echo -e "${BLUE}Running Rust unit tests...${NC}"
        cargo test
        ;;
        
    integration|int)
        echo -e "${BLUE}Running Python integration tests...${NC}"
        "${WORKSPACE_ROOT}/run_python_tests.sh" "$@"
        ;;
        
    all)
        echo -e "${BLUE}Running all tests...${NC}"
        echo -e "${GREEN}=== Rust Unit Tests ===${NC}"
        cargo test
        RUST_RESULT=$?
        
        echo
        echo -e "${GREEN}=== Python Integration Tests ===${NC}"
        "${WORKSPACE_ROOT}/run_python_tests.sh" "$@"
        PYTHON_RESULT=$?
        
        if [ $RUST_RESULT -eq 0 ] && [ $PYTHON_RESULT -eq 0 ]; then
            echo -e "${GREEN}All tests passed!${NC}"
        else
            echo -e "${RED}Some tests failed${NC}"
            exit 1
        fi
        ;;
        
    mfs)
        echo -e "${BLUE}Running MFS policy tests...${NC}"
        "${WORKSPACE_ROOT}/run_python_tests.sh" tests/test_mfs_policy.py -v "$@"
        ;;
        
    policy)
        echo -e "${BLUE}Running all policy tests...${NC}"
        "${WORKSPACE_ROOT}/run_python_tests.sh" tests/test_policy_behavior.py tests/test_mfs_policy.py tests/test_random_policy.py -v "$@"
        ;;
        
    specific)
        if [ $# -eq 0 ]; then
            echo -e "${RED}Error: 'specific' command requires a test path${NC}"
            echo "Example: $0 specific test_mfs_policy.py"
            exit 1
        fi
        TEST_PATH="$1"
        shift
        # If the test path doesn't start with tests/, add it
        if [[ ! "$TEST_PATH" =~ ^tests/ ]] && [[ "$TEST_PATH" =~ \.py ]]; then
            TEST_PATH="tests/$TEST_PATH"
        fi
        echo -e "${BLUE}Running specific test: $TEST_PATH${NC}"
        "${WORKSPACE_ROOT}/run_python_tests.sh" "$TEST_PATH" "$@"
        ;;
        
    debug)
        if [ $# -eq 0 ]; then
            echo -e "${YELLOW}Running all tests with debug logging...${NC}"
            RUST_LOG=debug "${WORKSPACE_ROOT}/test.sh" all
        else
            echo -e "${YELLOW}Running '$1' with debug logging...${NC}"
            RUST_LOG=debug "${WORKSPACE_ROOT}/test.sh" "$@"
        fi
        ;;
        
    clean)
        echo -e "${BLUE}Cleaning build artifacts and temp files...${NC}"
        cargo clean
        cd "${WORKSPACE_ROOT}/python_tests" && rm -rf .pytest_cache __pycache__ .benchmarks
        find /tmp -name "mergerfs_test_*" -type d 2>/dev/null | xargs rm -rf
        echo -e "${GREEN}Clean complete${NC}"
        ;;
        
    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        echo
        usage
        exit 1
        ;;
esac