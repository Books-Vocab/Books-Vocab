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

ROOT = Path(__file__).resolve().parents[1]

# Read from disk by inject_package_linked(), so it must be anchored to the repo:
# relative, it resolved against the caller's cwd and silently answered False
# from anywhere but the repo root — flipping R3 for every file without a word.
PBXPROJ = ROOT / "ios/BooksAndVocab.xcodeproj/project.pbxproj"

# Display only (it appears inside a finding string). Deliberately left
# repo-relative: findings are written into the version-controlled
# ops/injection_baseline.txt, and an absolute path there would embed one
# machine's home directory in a file every checkout has to match.
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
    """`path` MUST be relative to the scan root, never absolute.

    This is a substring match, so an absolute path drags the checkout's own
    directory names into the decision: a clone living under any directory named
    Debug/ or Readium would skip every file and produce an empty, clean-looking
    scan. ops/injection_lint.py passes `f.relative_to(VIEWS_ROOT)` for exactly
    that reason; ops/inject_codemod.py still passes absolutes and carries the
    hazard (IMP-20260808-e03c92). The fragments are also written WITHOUT a
    leading slash here, unlike ui_token_lint.py / plain_deadzone_lint.py's
    ("/Debug/",) — copy a fragment across in that form and it would match
    nothing under this contract.
    """
    s = str(path)
    return any(f in s for f in SKIP_PATH_FRAGMENTS)
