# Policy Implementation Status

This document tracks the implementation status of all mergerfs policies in mergerfs-rs.

## Summary

- **Implemented**: 6 of 20 policies (30%)
- **Remaining**: 14 policies

## Policy Categories

### Create Policies (For creating new files/directories)

| Policy | Name | Status | Description |
|--------|------|--------|-------------|
| ff | First Found | ✅ Implemented | First branch in order |
| mfs | Most Free Space | ✅ Implemented | Branch with most available space |
| lfs | Least Free Space | ✅ Implemented | Branch with least available space |
| lus | Least Used Space | ❌ Not Implemented | Branch with least used space |
| rand | Random | ❌ Not Implemented | Random selection from all branches |
| pfrd | Percentage Free Random Distribution | ❌ Not Implemented | Random weighted by free space |
| epmfs | Existing Path Most Free Space | ❌ Not Implemented | Most free space where path exists |
| eplfs | Existing Path Least Free Space | ❌ Not Implemented | Least free space where path exists |
| eplus | Existing Path Least Used Space | ❌ Not Implemented | Least used space where path exists |
| eprand | Existing Path Random | ❌ Not Implemented | Random from existing paths |
| eppfrd | Existing Path Percentage Free Random Distribution | ❌ Not Implemented | Percentage free random from existing paths |
| mspmfs | Most Shared Path Most Free Space | ❌ Not Implemented | Most shared path, most free space |
| msplfs | Most Shared Path Least Free Space | ❌ Not Implemented | Most shared path, least free space |
| msplus | Most Shared Path Least Used Space | ❌ Not Implemented | Most shared path, least used space |
| msppfrd | Most Shared Path Percentage Free Random Distribution | ❌ Not Implemented | Most shared path, percentage free random |
| newest | Newest | ❌ Not Implemented | Select file/directory with largest mtime |

### Action Policies (For operations on existing files)

| Policy | Name | Status | Description |
|--------|------|--------|-------------|
| all | All | ✅ Implemented | Apply to all branches |
| epall | Existing Path All | ✅ Implemented | All branches where path exists |
| epff | Existing Path First Found | ✅ Implemented | First found where path exists |
| erofs | Error Read-Only Filesystem | ❌ Not Implemented | Always returns read-only filesystem error |

### Search Policies (For finding existing files)

| Policy | Name | Status | Description |
|--------|------|--------|-------------|
| ff | First Found | ❌ Not Implemented | First branch in order |
| all | All | ❌ Not Implemented | Search all branches |
| newest | Newest | ❌ Not Implemented | Select file/directory with largest mtime |

## Implementation Priority

Based on common usage patterns, the recommended implementation order is:

1. **High Priority** (commonly used):
   - `rand` (create) - Random distribution
   - `epmfs` (create) - Common for balanced distribution
   - `ff` (search) - Most common search policy
   
2. **Medium Priority** (specialized use cases):
   - `lus` (create) - Least used space
   - `pfrd` (create) - Weighted random distribution
   - `eprand` (create) - Random from existing
   - `all` (search) - Union search
   
3. **Low Priority** (rarely used):
   - `msp*` policies - Most shared path variants
   - `eppfrd` (create) - Complex weighted distribution
   - `erofs` (action) - Special error policy
   - `newest` - Time-based selection

## Notes

- All create policies should implement path-preserving behavior when appropriate
- Search policies will need to be integrated with the FUSE operations
- The `erofs` policy is primarily for testing and special configurations
- Most shared path (msp) policies require complex path analysis