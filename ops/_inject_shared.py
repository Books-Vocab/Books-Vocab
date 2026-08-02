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

PBXPROJ = Path("ios/BooksAndVocab.xcodeproj/project.pbxproj")
SHIM = Path("ios/BooksAndVocab/Support/ObserveInjectionShim.swift")


def inject_package_linked() -> bool:
    """Is the real Inject SPM package linked into the app target?

    `import Inject` is a compile-time fact, not a style preference, so the
    generator and the gate must read it from the same place. This repo supplies
    @ObserveInjection / .enableInjection() from a local no-op shim (see SHIM) and
    links no such package: emitting the import yields "unable to resolve module
    dependency: 'Inject'". Until 2026-08-03 the codemod emitted it anyway and the
    lint demanded it, which left 90 of 130 baseline entries unfixable by
    construction — obeying the gate broke the build.

    Fail closed toward the shim world: it is the configuration that compiles.
    """
    try:
        return "Inject" in PBXPROJ.read_text(encoding="utf-8")
    except OSError:
        return False

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
