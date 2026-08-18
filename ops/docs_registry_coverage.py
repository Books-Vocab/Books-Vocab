#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Report docs/registry.yml coverage over linted docs.

Coverage debt is split into:
- active_unregistered: should usually be added to docs/registry.yml
    - historical_unregistered: path-based informational debt under docs/archive|plans|specs|snapshot
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path


STRICT_TIERS = {"reference", "sop", "policy", "runbook"}
HISTORICAL_PREFIXES = (
    "docs/archive/",
    "docs/plans/",
    "docs/snapshot/",
    "docs/specs/",
)


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def repo_root() -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"]).strip())


def strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def registry_paths(registry: Path) -> set[str]:
    paths: set[str] = set()
    for raw in registry.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("path:"):
            paths.add(strip_scalar(stripped.split(":", 1)[1]))
    return paths


def linted_docs(root: Path) -> list[Path]:
    """Every doc on disk EXCEPT the ones git is told to ignore.

    `rglob` alone counts gitignored artifacts as repo documents. Ignored generated
    artifacts are excluded so coverage reports only documents that can be reviewed
    and registered consistently on every checkout.

    Ignored-minus, NOT tracked-only. `git ls-files` would have been the shorter fix
    and it is the wrong one: a doc that has been ADDED but not yet committed is
    untracked, and it is exactly the case coverage exists to catch. Excluding it
    would trade a false positive for a false negative, in the direction that goes
    unnoticed.

    Falls back to the unfiltered list when git cannot answer (the tests drive this
    function against a plain fixture directory that is not a repo). That is correct
    rather than lenient: without a repo there is no ignore rule to honour.
    """
    candidates = sorted(
        path
        for path in (root / "docs").rglob("*.md")
        if not path.relative_to(root).as_posix().startswith(("docs/assets/", "docs/legal/"))
    )
    if not candidates:
        return []
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin"],
        input="\n".join(str(p) for p in candidates),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False,
    )
    # 0 = some paths are ignored, 1 = none are, 128 = not a repo / git unusable.
    if proc.returncode not in (0, 1):
        return candidates
    ignored = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return [p for p in candidates if str(p) not in ignored]


def doc_tier(path: Path) -> str:
    in_meta = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("<!-- doc-meta"):
            in_meta = True
            continue
        if in_meta and line.startswith("-->"):
            return "missing"
        if in_meta and line.startswith("tier:"):
            return strip_scalar(line.split(":", 1)[1])
    return "missing"


def is_historical_doc(rel_path: str) -> bool:
    return rel_path.startswith(HISTORICAL_PREFIXES)


def build_report(root: Path, registry: Path) -> dict[str, object]:
    registered = registry_paths(registry)
    docs = linted_docs(root)
    unregistered: list[dict[str, str]] = []
    active_unregistered: list[dict[str, str]] = []
    historical_unregistered: list[dict[str, str]] = []
    registered_count = 0
    by_tier: dict[str, list[str]] = defaultdict(list)
    active_by_tier: dict[str, list[str]] = defaultdict(list)
    historical_by_tier: dict[str, list[str]] = defaultdict(list)

    for path in docs:
        rel = path.relative_to(root).as_posix()
        tier = doc_tier(path)
        if rel in registered:
            registered_count += 1
        else:
            item = {"path": rel, "tier": tier}
            unregistered.append(item)
            by_tier[tier].append(rel)
            if is_historical_doc(rel):
                historical_unregistered.append(item)
                historical_by_tier[tier].append(rel)
            elif tier in STRICT_TIERS or tier == "missing":
                active_unregistered.append(item)
                active_by_tier[tier].append(rel)

    return {
        "total_docs": len(docs),
        "registered_count": registered_count,
        "unregistered_count": len(unregistered),
        "unregistered": unregistered,
        "unregistered_by_tier": {tier: paths for tier, paths in sorted(by_tier.items())},
        "active_unregistered_count": len(active_unregistered),
        "active_unregistered": active_unregistered,
        "active_unregistered_by_tier": {tier: paths for tier, paths in sorted(active_by_tier.items())},
        "historical_unregistered_count": len(historical_unregistered),
        "historical_unregistered": historical_unregistered,
        "historical_unregistered_by_tier": {tier: paths for tier, paths in sorted(historical_by_tier.items())},
        "strict_unregistered": active_unregistered,
    }


def print_human(report: dict[str, object]) -> None:
    print(
        "docs_registry_coverage: "
        f"total={report['total_docs']} "
        f"registered={report['registered_count']} "
        f"unregistered={report['unregistered_count']} "
        f"active_unregistered={report['active_unregistered_count']} "
        f"historical_unregistered={report['historical_unregistered_count']}"
    )
    if report["active_unregistered_count"] == 0:
        if report["historical_unregistered_count"] == 0:
            print("docs_registry_coverage: no registry coverage debt for linted docs")
        else:
            print("docs_registry_coverage: no active registry debt; historical docs below are informational only")
            print(
                "docs_registry_coverage: historical classification is path-based "
                "(docs/archive|docs/plans|docs/specs|docs/snapshot)"
            )
    else:
        print("docs_registry_coverage: active docs below should be registered; use --strict to fail on them")
    active_by_tier = report["active_unregistered_by_tier"]
    assert isinstance(active_by_tier, dict)
    for tier, paths in active_by_tier.items():
        print(f"ACTIVE_UNREGISTERED tier={tier} count={len(paths)}")
        for path in paths:
            print(f"  {path}")

    historical_by_tier = report["historical_unregistered_by_tier"]
    assert isinstance(historical_by_tier, dict)
    for tier, paths in historical_by_tier.items():
        print(f"HISTORICAL_UNREGISTERED tier={tier} count={len(paths)}")
        for path in paths:
            print(f"  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root override, mainly for fixtures.")
    parser.add_argument("--registry", default="docs/registry.yml", help="Registry path.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON with full active/historical breakdown.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero only when active_unregistered docs exist; historical docs remain informational.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else repo_root()
    registry = root / args.registry
    if not registry.is_file():
        raise SystemExit(f"ERROR registry 不存在: {args.registry}")

    report = build_report(root, registry)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human(report)

    if args.strict and report["strict_unregistered"]:
        print(f"STRICT FAIL: {len(report['strict_unregistered'])} active docs are not in registry")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
