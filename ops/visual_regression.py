#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Catalog visual regression: perceptual diff between two snapshot roots.

Generalizes the chrome-parity audit's pHash comparison to the whole Catalog:
pairs every `<device>/<surface>/<scenario>.png` across a baseline and a
current snapshot root and reports added / removed / changed surfaces.

  ops/visual_regression.py --baseline <root> --current <root> [opts]
  ops/visual_regression.py --auto    # newest usable root vs the previous one

Calibration samples (catalog-full-20260608-* roots): identical render = 0,
run-to-run noise = 0 (deterministic), small pixel perturbation ~5e-4; sampled
real differences ranged from ~3e2 (subtle layout shift) to ~3.5e4 (different
scenario). The default threshold (1.0) sits orders of magnitude above noise
and below every observed real change.

Exit: 0 = no changed/removed (added alone is informational), 1 = visual
regression candidates found, 2 = setup/usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_THRESHOLD = 1.0


def fail(msg: str) -> "SystemExit":
    print(f"ERROR: {msg}", file=sys.stderr)
    return SystemExit(2)


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    return Path(out)


def usable_roots(snapshots: Path) -> list[Path]:
    # Only full catalog runs qualify: build/snapshots also hosts side artifacts
    # (e.g. gallery-admin-preview) with a usable manifest but a curated subset
    # of surfaces — pairing against one yields bogus removed/changed noise.
    # catalog-full-<UTC> naming makes lexicographic order chronological.
    roots = []
    if not snapshots.is_dir():
        return roots
    for manifest_path in sorted(snapshots.glob("catalog-full-*/review_manifest.json")):
        root = manifest_path.parent
        try:
            if manifest_shot_paths(root):
                roots.append(root)
        except SystemExit:
            continue
    return roots


def manifest_shot_paths(root: Path) -> set[str]:
    manifest_path = root / "review_manifest.json"
    if not manifest_path.is_file():
        raise fail(f"catalog snapshot root is missing review_manifest.json: {root}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fail(f"review_manifest.json is unreadable: {manifest_path}: {exc}")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise fail(f"review_manifest.json items must be an array: {manifest_path}")

    paths: set[str] = set()
    root_resolved = root.resolve()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("relPath"), str):
            raise fail(f"review_manifest.json item {index} missing string relPath: {manifest_path}")
        rel = item["relPath"]
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root_resolved):
            raise fail(f"review_manifest.json item escapes snapshot root: {rel}")
        if candidate.suffix.lower() != ".png" or not candidate.is_file():
            raise fail(f"review_manifest.json item PNG missing: {rel}")
        paths.add(Path(rel).as_posix())
    if not paths:
        raise fail(f"review_manifest.json contains no PNG items: {manifest_path}")
    return paths


def auto_roots() -> tuple[Path, Path]:
    snapshots = Path(os.environ.get("KG_VISREG_SNAPSHOTS") or repo_root() / "build" / "snapshots")
    roots = usable_roots(snapshots)
    if len(roots) < 2:
        raise fail(
            f"--auto needs >= 2 usable snapshot roots under {snapshots} "
            "(generate with ./ops/ios_ops.sh catalog snapshots)"
        )
    return roots[-2], roots[-1]


def shot_paths(root: Path) -> set[str]:
    return manifest_shot_paths(root)


def magick(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["magick", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def dimensions(path: Path) -> str:
    result = magick(["identify", "-format", "%wx%h", str(path)])
    if result.returncode != 0:
        raise fail(f"identify failed for {path}: {result.stderr.strip()}")
    return result.stdout.strip()


def phash_distance(a: Path, b: Path) -> float:
    # `magick compare` exits 1 when images differ — the metric is on stderr.
    result = magick(["compare", "-metric", "PHASH", str(a), str(b), "null:"])
    if result.returncode not in (0, 1):
        raise fail(f"compare failed for {a} vs {b}: {result.stderr.strip()}")
    try:
        return float(result.stderr.strip().split()[0])
    except (IndexError, ValueError):
        raise fail(f"unparseable PHASH output for {a} vs {b}: {result.stderr.strip()!r}")


def compare_pair(baseline: Path, current: Path, rel: str, threshold: float) -> dict | None:
    a = baseline / rel
    b = current / rel
    dim_a = dimensions(a)
    dim_b = dimensions(b)
    if dim_a != dim_b:
        return {"path": rel, "reason": f"dimensions {dim_a} -> {dim_b}"}
    distance = phash_distance(a, b)
    if distance > threshold:
        return {"path": rel, "reason": "phash", "phash": distance}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, help="baseline snapshot root")
    parser.add_argument("--current", type=Path, help="current snapshot root")
    parser.add_argument("--auto", action="store_true", help="pair the two newest usable roots")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"pHash distance above which a pair counts as changed (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--only", metavar="SUBSTR", help="restrict to relative paths containing SUBSTR")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.auto == bool(args.baseline or args.current):
        raise fail("use either --auto or both --baseline and --current")
    if args.auto:
        baseline, current = auto_roots()
    else:
        if not (args.baseline and args.current):
            raise fail("--baseline and --current are both required")
        baseline, current = args.baseline, args.current
    for root in (baseline, current):
        if not root.is_dir():
            raise fail(f"not a directory: {root}")

    base_set = shot_paths(baseline)
    curr_set = shot_paths(current)
    if args.only:
        base_set = {p for p in base_set if args.only in p}
        curr_set = {p for p in curr_set if args.only in p}

    removed = sorted(base_set - curr_set)
    added = sorted(curr_set - base_set)
    common = sorted(base_set & curr_set)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda rel: compare_pair(baseline, current, rel, args.threshold), common))
    changed = [r for r in results if r]
    unchanged = len(common) - len(changed)

    report = {
        "baseline": str(baseline),
        "current": str(current),
        "threshold": args.threshold,
        "changed": changed,
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"baseline: {baseline}")
        print(f"current:  {current}")
        print(f"compared {len(common)} pairs (threshold {args.threshold}): "
              f"{len(changed)} changed, {len(added)} added, {len(removed)} removed, {unchanged} unchanged")
        for entry in changed:
            detail = entry.get("phash")
            suffix = f"phash={detail:.1f}" if detail is not None else entry["reason"]
            print(f"  changed  {entry['path']}  ({suffix})")
        for rel in removed:
            print(f"  removed  {rel}")
        for rel in added:
            print(f"  added    {rel}")

    return 1 if (changed or removed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
