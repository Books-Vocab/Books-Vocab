#!/usr/bin/env -S uv run --python 3.13 python
"""
i18n_lint preview-stripper.

Reads a Swift file path (argv[1]) and writes to stdout the file content with
SwiftUI preview blocks blanked out. "Blanked out" = each stripped line is
emitted as an empty line, so original 1-based line numbers are preserved
(important: i18n_lint.sh prints `path:line:col:content`, and the line numbers
must still match the on-disk file).

Two patterns are stripped:

1. `#Preview` macro invocations, e.g.:
       #Preview("label") {
           ...
       }
   The trailing closure body (including nested braces) is blanked.

2. Private preview structs co-located with the type they preview, e.g.:
       private struct AppActionButtonPreview: View {
           var body: some View { ... }
       }
   Any `private struct <Name>Preview` (with or without protocol conformance
   list) is blanked. `<Name>Preview_Previews` (the legacy PreviewProvider
   style) is also covered by the same suffix match.

Lines outside these regions are passed through unchanged. We rely on
brace-balance counting that ignores braces appearing inside string literals
and `//` line comments — this is good enough for Swift source files
authored in this repo (no exotic raw-string preview labels, etc).

If an input file cannot be parsed for any reason, the original content is
emitted unchanged so the lint never produces a false-negative crash.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Detect `#Preview` macro start. Matches `#Preview {`, `#Preview("x") {`,
# `#Preview("x", traits: ...) {` etc. The opening brace must appear on the
# same line (Swift macro syntax requires it).
PREVIEW_MACRO_RE = re.compile(r"^\s*#Preview\b[^{]*\{")

# Detect a preview struct. We accept `Preview`, `Preview_Previews`, and any
# other identifier whose name ends in `Preview`. The access modifier is
# optional: harnesses are routinely lifted `private` → `internal` so the
# DEBUG Playbook catalog can reuse them, but they remain preview-only code
# (the `*Preview` name suffix is the reliable signal, not the access level).
# Conformance list / generic clause may follow. Opening brace on same line.
PREVIEW_STRUCT_RE = re.compile(
    r"^\s*(?:private\s+|fileprivate\s+|internal\s+|public\s+)?"
    r"struct\s+\w*Preview(?:_Previews)?\s*(?::\s*[^{]+)?\{"
)


def _strip_string_and_comment(line: str) -> str:
    """Return `line` with string-literal contents and // line comments removed,
    so brace counting won't be fooled by `"}"` or `// }`."""
    # Drop trailing line comment.
    # (Block comments are not handled — none span braces in this repo.)
    out: list[str] = []
    i = 0
    n = len(line)
    in_string = False
    in_string_raw_hashes = 0  # support `#"..."#` minimally
    while i < n:
        ch = line[i]
        if not in_string:
            # Detect // line comment.
            if ch == "/" and i + 1 < n and line[i + 1] == "/":
                break
            # Detect raw string `#"..."#` (count leading #s).
            if ch == "#":
                j = i
                hashes = 0
                while j < n and line[j] == "#":
                    hashes += 1
                    j += 1
                if j < n and line[j] == '"' and hashes > 0:
                    in_string = True
                    in_string_raw_hashes = hashes
                    i = j + 1
                    continue
            if ch == '"':
                in_string = True
                in_string_raw_hashes = 0
                i += 1
                continue
            out.append(ch)
            i += 1
        else:
            if ch == "\\" and in_string_raw_hashes == 0:
                # Skip escape sequence inside non-raw string.
                i += 2
                continue
            if ch == '"':
                if in_string_raw_hashes == 0:
                    in_string = False
                    i += 1
                    continue
                # raw string: need matching trailing #s
                j = i + 1
                hashes = 0
                while j < n and line[j] == "#":
                    hashes += 1
                    j += 1
                if hashes >= in_string_raw_hashes:
                    in_string = False
                    in_string_raw_hashes = 0
                    i = j
                    continue
            i += 1
    return "".join(out)


def strip_previews(text: str) -> str:
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if PREVIEW_MACRO_RE.search(line) or PREVIEW_STRUCT_RE.search(line):
            # Start of a preview region. Count braces from this line onward
            # until depth returns to 0.
            depth = 0
            j = i
            while j < n:
                sanitized = _strip_string_and_comment(lines[j])
                depth += sanitized.count("{")
                depth -= sanitized.count("}")
                out.append("")  # blank but preserves line number
                j += 1
                if depth <= 0:
                    break
            i = j
            continue
        out.append(line)
        i += 1
    # Preserve trailing newline if original had one.
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + suffix


def _stripped(path: Path) -> str | None:
    """Stripped content, the original on a strip error, None if unreadable."""
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[strip_previews] cannot read {path}: {e}\n")
        return None
    try:
        return strip_previews(original)
    except Exception as e:  # pragma: no cover
        # On any error, emit original so lint stays correct.
        sys.stderr.write(f"[strip_previews] error on {path}: {e}\n")
        return original


def mirror(src_root: Path, dest_root: Path, files: list[str]) -> int:
    """Write each file's stripped copy to dest_root/<path relative to src_root>.

    i18n_lint.sh used to start one interpreter per Swift file per pattern
    (~2x the tree, ~100s), which is what made the pre-commit fast tier time
    out. One process now strips the whole list and rg scans the mirror once.
    An unreadable file is left out of the mirror — the same "no hits" the
    single-file mode gives it by printing nothing.
    """
    for name in files:
        path = Path(name)
        rel = path.relative_to(src_root)
        content = _stripped(path)
        if content is None:
            continue
        out = dest_root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return 0


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--mirror":
        files = [line for line in sys.stdin.read().splitlines() if line]
        return mirror(Path(sys.argv[2]), Path(sys.argv[3]), files)
    if len(sys.argv) != 2:
        sys.stderr.write(
            "usage: _i18n_strip_previews.py <swift-file>\n"
            "       _i18n_strip_previews.py --mirror <src-root> <dest-root> < file-list\n"
        )
        return 2
    content = _stripped(Path(sys.argv[1]))
    if content is not None:
        sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
