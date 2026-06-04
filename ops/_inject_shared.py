"""Shared View-injection grammar for inject_codemod.py (generator) and
injection_lint.py (enforcement gate).

The codemod inserts the three-piece InjectionNext scaffold that the lint then
verifies, so both MUST agree on what a SwiftUI View struct looks like and which
paths to skip. Keeping the grammar here means a rule tweak updates one place
instead of two files that can silently drift apart.
"""
from __future__ import annotations

import re
from pathlib import Path

# Path fragments excluded from injection (debug-only / vendored readers).
SKIP_PATH_FRAGMENTS = ("Debug/", "Readium", "PDFReader")

# A top-level `struct Name: <protocols> {` declaration (the View candidates).
STRUCT_VIEW_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<access>(public |internal |fileprivate |private )?)"
    r"struct\s+(?P<name>[A-Z][A-Za-z0-9_]*)"
    r"(?P<generics><[^>]+>)?"
    r"\s*:\s*"
    r"(?P<protocols>[^{]+?)"
    r"\s*\{"
)

# Opening of a `#Preview { ... }` block.
PREVIEW_OPEN_RE = re.compile(r"#Preview\b[^{]*\{")


def should_skip_path(path: Path) -> bool:
    s = str(path)
    return any(f in s for f in SKIP_PATH_FRAGMENTS)
