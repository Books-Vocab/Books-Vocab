#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Report docs/registry.yml coverage over linted docs."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path


STRICT_TIERS = {"reference", "sop", "policy", "runbook"}


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
    return sorted(
        path
        for path in (root / "docs").rglob("*.md")
        if not path.relative_to(root).as_posix().startswith(("docs/assets/", "docs/legal/"))
    )


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


def build_report(root: Path, registry: Path) -> dict[str, object]:
    registered = registry_paths(registry)
    docs = linted_docs(root)
    unregistered: list[dict[str, str]] = []
    registered_count = 0
    by_tier: dict[str, list[str]] = defaultdict(list)

    for path in docs:
        rel = path.relative_to(root).as_posix()
        tier = doc_tier(path)
        if rel in registered:
            registered_count += 1
        else:
            unregistered.append({"path": rel, "tier": tier})
            by_tier[tier].append(rel)

    return {
        "total_docs": len(docs),
        "registered_count": registered_count,
        "unregistered_count": len(unregistered),
        "unregistered": unregistered,
        "unregistered_by_tier": {tier: paths for tier, paths in sorted(by_tier.items())},
        "strict_unregistered": [
            item for item in unregistered if item["tier"] in STRICT_TIERS or item["tier"] == "missing"
        ],
    }


def print_human(report: dict[str, object]) -> None:
    print(
        "docs_registry_coverage: "
        f"total={report['total_docs']} "
        f"registered={report['registered_count']} "
        f"unregistered={report['unregistered_count']}"
    )
    by_tier = report["unregistered_by_tier"]
    assert isinstance(by_tier, dict)
    for tier, paths in by_tier.items():
        print(f"UNREGISTERED tier={tier} count={len(paths)}")
        for path in paths:
            print(f"  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="docs/registry.yml", help="Registry path.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when active docs are unregistered.")
    args = parser.parse_args()

    root = repo_root()
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
