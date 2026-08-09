#!/usr/bin/env -S uv run --python 3.13 python
"""InjectionNext rollout codemod (Phase A + A.5).

Two passes:
  1. Inserts `import Inject` and `@ObserveInjection private var inject` into
     Swift View structs.
  2. For each annotated View whose `var body: some View { ... }` is a single
     root expression (not opening with `if` / `switch` / `return`), appends
     `.enableInjection()` as the final modifier.

Idempotent. Skips ViewModifier / PreviewProvider, private View structs, files
under Debug/Readium/PDFReader paths, structs already annotated, `#Preview {}`
blocks, and bodies starting with if/switch/return (logged for manual Phase B).

Usage:
    ./ops/inject_codemod.py --dry-run --report
    ./ops/inject_codemod.py --apply [--scope Welcome]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWS_ROOT = ROOT / "ios/BooksAndVocab/Views"
# View-injection grammar shared with the lint (single source of truth).
from _inject_shared import (  # noqa: E402
    STRUCT_VIEW_RE,
    PREVIEW_OPEN_RE,
    SKIP_PATH_FRAGMENTS,
    inject_package_linked,
    should_skip_path,
)

# Codemod-only patterns (not shared with the lint).
IMPORT_RE = re.compile(r"^import\s+\S+")
BODY_OPEN_RE = re.compile(r"^(?P<indent>\s*)var\s+body\s*:\s*some\s+View\s*\{")


def find_close_at_indent(lines: list[str], start: int, indent: str) -> int:
    """Return index of the first line after `start` matching exactly
    f'{indent}}}' (closing brace at that indent). -1 if not found."""
    needle = f"{indent}}}"
    for k in range(start + 1, len(lines)):
        if lines[k].rstrip() == needle:
            return k
    return -1


def first_body_token(lines: list[str], body_open_idx: int, close_idx: int) -> str:
    """Find the first significant token inside the body (skip blank lines & comments)."""
    in_block_comment = False
    for k in range(body_open_idx + 1, close_idx):
        stripped = lines[k].strip()
        if not stripped:
            continue
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue
        # First real token
        return stripped.split(None, 1)[0]
    return ""


def find_last_modifier_line(lines: list[str], body_open_idx: int, close_idx: int) -> int:
    """Find the last non-blank, non-comment line before the body's closing brace."""
    for k in range(close_idx - 1, body_open_idx, -1):
        stripped = lines[k].strip()
        if not stripped or stripped.startswith("//"):
            continue
        return k
    return -1


def process_file(path: Path):
    """Return (new_text, summary) or (None, summary) if no change."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()

    annotations: list[tuple[int, str, str, bool]] = []  # (struct_line, name, indent, already_has_observe)
    last_import_idx = -1
    preview_depth = 0

    for i, line in enumerate(lines):
        if IMPORT_RE.match(line.strip()):
            last_import_idx = i

        if preview_depth > 0:
            preview_depth += line.count("{") - line.count("}")
            if preview_depth <= 0:
                preview_depth = 0
            continue

        if PREVIEW_OPEN_RE.search(line):
            preview_depth = line.count("{") - line.count("}")
            if preview_depth < 0:
                preview_depth = 0
            continue

        m = STRUCT_VIEW_RE.match(line)
        if not m:
            continue

        access = m.group("access").strip()
        if access in ("private", "fileprivate"):
            continue

        protocol_list = [p.strip() for p in m.group("protocols").split(",")]
        if "View" not in protocol_list:
            continue

        # Idempotency: skip if @ObserveInjection already follows
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        already_has_observe = j < len(lines) and "@ObserveInjection" in lines[j]
        annotations.append((i, m.group("name"), m.group("indent"), already_has_observe))

    if not annotations:
        return None, {"obs": [], "mod": [], "skip_body": []}

    # ---- Plan modifications -----------------------------------------------
    # Collect insertions and replacements; apply at end (in reverse).
    inserts: dict[int, list[str]] = {}  # line_idx -> lines to insert AFTER
    obs_added: list[str] = []
    mod_added: list[str] = []
    skip_body: list[str] = []

    for struct_line, name, indent, already_obs in annotations:
        # Pass 1: @ObserveInjection
        if not already_obs:
            inserts.setdefault(struct_line, []).append(
                f"{indent}    @ObserveInjection private var inject"
            )
            obs_added.append(name)

        # Pass 2: locate this struct's body and append .enableInjection()
        struct_close = find_close_at_indent(lines, struct_line, indent)
        if struct_close < 0:
            skip_body.append(f"{name} (struct close not found)")
            continue

        # Find `var body: some View {` within struct
        body_open = -1
        body_indent = ""
        for k in range(struct_line + 1, struct_close):
            bm = BODY_OPEN_RE.match(lines[k])
            if bm:
                body_open = k
                body_indent = bm.group("indent")
                break
        if body_open < 0:
            # No body in this struct (rare — but a View must have body; might be
            # extension-defined or pattern we don't recognize). Skip silently.
            continue

        body_close = find_close_at_indent(lines, body_open, body_indent)
        if body_close < 0 or body_close > struct_close:
            skip_body.append(f"{name} (body close not found)")
            continue

        first_tok = first_body_token(lines, body_open, body_close)
        # Only skip true multi-branch roots (if/switch). Group {} and `return X`
        # are single-root expressions and accept `.enableInjection()` as a
        # trailing modifier on the next line.
        if first_tok in ("if", "switch"):
            skip_body.append(f"{name} ({first_tok} body — Phase B)")
            continue

        last_mod = find_last_modifier_line(lines, body_open, body_close)
        if last_mod < 0:
            skip_body.append(f"{name} (empty body)")
            continue

        # Idempotency: already has .enableInjection() in this body?
        body_text = "\n".join(lines[body_open : body_close + 1])
        if ".enableInjection()" in body_text:
            continue

        # Insert .enableInjection() on a new line after `last_mod`, at same
        # indentation as the last modifier line.
        last_indent = re.match(r"^(\s*)", lines[last_mod]).group(1)
        inserts.setdefault(last_mod, []).append(f"{last_indent}.enableInjection()")
        mod_added.append(name)

    if not obs_added and not mod_added:
        return None, {
            "obs": obs_added,
            "mod": mod_added,
            "skip_body": skip_body,
        }

    # `import Inject` is only correct when the Inject SPM package is actually
    # linked. This repo provides @ObserveInjection / .enableInjection() from a
    # local shim (ios/BooksAndVocab/Support/ObserveInjectionShim.swift) and links
    # no such package, so emitting the import produced code that does not
    # compile ("unable to resolve module dependency: 'Inject'") — every file this
    # codemod touched was left unbuildable. Mirror injection_lint's rule and let
    # the project's own linkage decide.
    needs_import = (
        inject_package_linked()
        and "import Inject" not in [l.strip() for l in lines]
        and (obs_added or mod_added)
    )

    # Apply inserts in reverse line order
    new_lines = list(lines)
    for idx in sorted(inserts.keys(), reverse=True):
        for entry in reversed(inserts[idx]):
            new_lines.insert(idx + 1, entry)

    if needs_import:
        if last_import_idx >= 0:
            new_lines.insert(last_import_idx + 1, "import Inject")
        else:
            new_lines.insert(0, "import Inject")

    trailing_nl = "\n" if original.endswith("\n") else ""
    return "\n".join(new_lines) + trailing_nl, {
        "obs": obs_added,
        "mod": mod_added,
        "skip_body": skip_body,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--scope", default=None, help="Limit to Views/<scope>")
    ap.add_argument("--baseline-out", default=None, help="Write skipped bodies here")
    args = ap.parse_args()

    root = VIEWS_ROOT / args.scope if args.scope else VIEWS_ROOT
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        return 2

    files = sorted(root.rglob("*.swift"))
    total = modified = obs_total = mod_total = 0
    baseline_lines: list[str] = []
    for f in files:
        if should_skip_path(f.relative_to(root)):
            continue
        total += 1
        result, summary = process_file(f)
        skipped = summary.get("skip_body", [])
        for s in skipped:
            baseline_lines.append(f"{f}: {s}")
        if result is None:
            continue
        modified += 1
        obs_total += len(summary["obs"])
        mod_total += len(summary["mod"])
        if args.report:
            obs = ", ".join(summary["obs"]) or "-"
            mod = ", ".join(summary["mod"]) or "-"
            sk = (" SKIP: " + "; ".join(skipped)) if skipped else ""
            print(f"{f}: obs[{obs}] mod[{mod}]{sk}")
        if args.apply:
            f.write_text(result, encoding="utf-8")

    if total == 0:
        why = (
            "no .swift file exists under it"
            if not files
            else f"all {len(files)} .swift file(s) under it are excluded by "
            f"{list(SKIP_PATH_FRAGMENTS)}"
        )
        print(
            f"ERROR: scanned 0 files under {root} — {why}. A codemod that "
            "examined nothing has not shown that anything is safe to change; "
            "refusing to report a successful scan.",
            file=sys.stderr,
        )
        return 2

    print(
        f"\nScanned: {total}, files modified: {modified}, "
        f"@ObserveInjection added: {obs_total}, .enableInjection() added: {mod_total}",
        file=sys.stderr,
    )
    if baseline_lines:
        print(f"Bodies skipped (Phase B manual): {len(baseline_lines)}", file=sys.stderr)
        if args.baseline_out:
            Path(args.baseline_out).write_text("\n".join(baseline_lines) + "\n")
            print(f"  → written to {args.baseline_out}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run, no files written)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
