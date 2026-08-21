"""Stable process exits and Git references for the registry CLI."""

from __future__ import annotations

import re

ORIGIN_MAIN_REF = "refs/heads/main"
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CLAIMED = 75
EXIT_USAGE = 64
