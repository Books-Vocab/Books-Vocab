#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""UI quality control plane: query/validate ops/ui_quality_plane.yml.

Subcommands:
  validate            schema + referenced-path existence check (CI-able)
  list [--json]       enumerate registered mechanisms
  impact --files ...  map changed paths -> mechanisms whose triggers match
  impact --since REF  same, over `git diff --name-only REF...HEAD`

Triggers are path hints, not auto-run commands: `dir/` prefix, glob, or exact
file; `!`-prefixed entries exclude. Semantic judgment stays with the agent —
same contract as docs/registry.yml.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

LAYERS = {
    "static-value",
    "static-code",
    "structure",
    "state-snapshot",
    "behavior",
    "perf",
    "cross-platform",
    "visual-regression",
}
GATES = {"ci", "test_ops", "ios-test", "xcode", "manual"}
REQUIRED_KEYS = {"id", "layer", "entrypoint", "gate", "triggers", "verdict", "docs"}
KNOWN_KEYS = REQUIRED_KEYS | {"regression", "notes"}
LIST_KEYS = {"triggers", "docs"}


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    return Path(out)


def plane_path(root: Path) -> Path:
    override = os.environ.get("KG_UI_PLANE_FILE")
    if override:
        return Path(override)
    return root / "ops" / "ui_quality_plane.yml"


def strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_plane(path: Path) -> tuple[str, list[dict]]:
    """Minimal parser for the subset of YAML this plane file uses.

    Supports: top-level scalars, `mechanisms:` list of `- id:` blocks with
    4-space scalar keys, 6-space `- item` lists, and `>`/`|` folded blocks.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    version = ""
    mechanisms: list[dict] = []
    current: dict | None = None
    i = 0
    n = len(lines)
    in_mechanisms = False

    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())

        if not in_mechanisms:
            if stripped == "mechanisms:":
                in_mechanisms = True
            elif indent == 0 and stripped.startswith("version:"):
                version = strip_scalar(stripped.partition(":")[2])
            i += 1
            continue

        if indent == 2 and stripped.startswith("- id:"):
            current = {"id": strip_scalar(stripped[len("- id:") :])}
            mechanisms.append(current)
            i += 1
            continue

        if current is None or indent != 4 or ":" not in stripped:
            i += 1
            continue

        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest in {">", ">-", "|", "|-"}:
            block: list[str] = []
            i += 1
            while i < n:
                nxt = lines[i]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= 4:
                    break
                if nxt.strip():
                    block.append(nxt.strip())
                i += 1
            current[key] = " ".join(block)
            continue

        if rest == "":
            items: list[str] = []
            i += 1
            while i < n:
                nxt = lines[i]
                st = nxt.strip()
                if not st:
                    i += 1
                    continue
                ind = len(nxt) - len(nxt.lstrip())
                if st.startswith("- ") and ind >= 6:
                    items.append(strip_scalar(st[2:]))
                    i += 1
                else:
                    break
            current[key] = items
            continue

        current[key] = strip_scalar(rest)
        i += 1

    return version, mechanisms


def trigger_matches(file: str, trigger: str) -> bool:
    if trigger.endswith("/"):
        return file.startswith(trigger)
    if any(ch in trigger for ch in "*?["):
        return fnmatch.fnmatch(file, trigger)
    return file == trigger


def matched_files(mech: dict, files: list[str]) -> list[str]:
    triggers = mech.get("triggers", [])
    includes = [t for t in triggers if not t.startswith("!")]
    excludes = [t[1:] for t in triggers if t.startswith("!")]
    hits = []
    for f in files:
        if any(trigger_matches(f, ex) for ex in excludes):
            continue
        if any(trigger_matches(f, inc) for inc in includes):
            hits.append(f)
    return hits


def cmd_validate(root: Path, mechanisms: list[dict], version: str) -> int:
    errors: list[str] = []
    if not version:
        errors.append("missing top-level `version:`")
    if not mechanisms:
        errors.append("no mechanisms declared")

    seen_ids: set[str] = set()
    for mech in mechanisms:
        mid = mech.get("id", "<missing id>")
        if mid in seen_ids:
            errors.append(f"{mid}: duplicate id")
        seen_ids.add(mid)

        missing = REQUIRED_KEYS - mech.keys()
        if missing:
            errors.append(f"{mid}: missing keys {sorted(missing)}")
        unknown = mech.keys() - KNOWN_KEYS
        if unknown:
            errors.append(f"{mid}: unknown keys {sorted(unknown)}")

        layer = mech.get("layer", "")
        if layer and layer not in LAYERS:
            errors.append(f"{mid}: unknown layer {layer!r} (allowed: {sorted(LAYERS)})")
        gate = mech.get("gate", "")
        if gate and gate not in GATES:
            errors.append(f"{mid}: unknown gate {gate!r} (allowed: {sorted(GATES)})")

        for key in LIST_KEYS:
            value = mech.get(key)
            if value is not None and (not isinstance(value, list) or not value):
                errors.append(f"{mid}: `{key}` must be a non-empty list")

        entrypoint = mech.get("entrypoint", "")
        if entrypoint and not (root / entrypoint).exists():
            errors.append(f"{mid}: entrypoint not found: {entrypoint}")
        for doc in mech.get("docs", []) or []:
            if not (root / doc).exists():
                errors.append(f"{mid}: doc not found: {doc}")
        if isinstance(mech.get("verdict"), str) and not mech["verdict"].strip():
            errors.append(f"{mid}: empty verdict")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"ui_quality_plane: {len(mechanisms)} mechanisms valid")
    return 0


def cmd_list(mechanisms: list[dict], as_json: bool) -> int:
    if as_json:
        print(json.dumps(mechanisms, ensure_ascii=False, indent=2))
        return 0
    width = max((len(m.get("id", "")) for m in mechanisms), default=0)
    for mech in mechanisms:
        print(
            f"{mech.get('id', ''):<{width}}  "
            f"{mech.get('layer', ''):<17} "
            f"{mech.get('gate', ''):<9} "
            f"{mech.get('entrypoint', '')}"
        )
    return 0


def changed_since(ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def cmd_impact(mechanisms: list[dict], files: list[str], as_json: bool) -> int:
    impacted = []
    for mech in mechanisms:
        hits = matched_files(mech, files)
        if hits:
            impacted.append(
                {
                    "id": mech.get("id", ""),
                    "layer": mech.get("layer", ""),
                    "gate": mech.get("gate", ""),
                    "entrypoint": mech.get("entrypoint", ""),
                    "matched": hits,
                }
            )
    if as_json:
        print(json.dumps(impacted, ensure_ascii=False, indent=2))
        return 0
    if not impacted:
        print("no UI quality mechanisms triggered")
        return 0
    for entry in impacted:
        print(f"{entry['id']}  {entry['entrypoint']}  ({entry['gate']}; {len(entry['matched'])} file(s))")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="schema + path existence check")
    p_list = sub.add_parser("list", help="enumerate mechanisms")
    p_list.add_argument("--json", action="store_true")
    p_impact = sub.add_parser("impact", help="map changed files to mechanisms")
    p_impact.add_argument("--json", action="store_true")
    group = p_impact.add_mutually_exclusive_group(required=True)
    group.add_argument("--files", nargs="+")
    group.add_argument("--since", metavar="REF")
    args = parser.parse_args()

    root = repo_root()
    path = plane_path(root)
    if not path.exists():
        print(f"ERROR: plane file not found: {path}", file=sys.stderr)
        return 1
    version, mechanisms = parse_plane(path)

    if args.command == "validate":
        return cmd_validate(root, mechanisms, version)
    if args.command == "list":
        return cmd_list(mechanisms, args.json)
    files = args.files if args.files else changed_since(args.since)
    return cmd_impact(mechanisms, files, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
