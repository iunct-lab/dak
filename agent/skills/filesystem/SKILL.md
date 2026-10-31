---
name: filesystem
description: Manage files and directories (list, read, write, search).
tools:
  - list_files
  - read_file
  - write_file
  - search_files
---
# Filesystem Management

You have access to the local filesystem. Use these tools to navigate, read, and modify files.

## Workflow
1. **Explore**: Use `list_files` to see what's in a directory.
2. **Search**: Use `search_files` to find specific files by pattern (e.g., `*.py`).
3. **Read**: Use `read_file` to examine file content.
4. **Edit**: Use `write_file` to create or overwrite files.

## Safety Guidelines
- **Check Existence**: Before reading or writing, verify the path exists or is correct.
- **Read First**: Before overwriting a file with `write_file`, read it to ensure you don't lose important data.
- **Relative Paths**: Always use paths relative to the project root.
