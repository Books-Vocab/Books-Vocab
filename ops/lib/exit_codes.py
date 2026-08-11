"""Shared process exit-code contract for KG command-line tools.

The numeric values are intentionally centralized so callers can distinguish a
bad invocation from a blocked operation or a temporary claim race without
depending on which CLI produced the result.
"""

EXIT_OK = 0
EXIT_USAGE = 64
EXIT_BLOCK = 1
EXIT_PARTIAL = 1
EXIT_CLAIMED = 75
