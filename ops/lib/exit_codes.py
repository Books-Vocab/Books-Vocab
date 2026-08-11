"""Shared process exit-code contract for KG command-line tools.

The numeric values are intentionally centralized so callers can distinguish a
bad invocation from a blocked operation or a temporary claim race without
depending on which CLI produced the result.
"""

# Public process contract shared by the Python entrypoints. Keep the names
# semantic so callers do not infer meaning from a command-specific integer.
EXIT_OK = 0
EXIT_TOOL_ERROR = 1
EXIT_BLOCK = 2
EXIT_WARN = 3
EXIT_USAGE = 64
EXIT_CLAIMED = 75

# Existing registry callers use this for an operational partial failure.
EXIT_PARTIAL = EXIT_TOOL_ERROR
