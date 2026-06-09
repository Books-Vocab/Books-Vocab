#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""UI dead-code scanner for the iOS app (production-orphan struct/class/enum/protocol).

Pipeline:
  ios_ops.sh build (isolated DerivedData) -> Xcode IndexStore
    -> kgindex (neutral extraction) -> records JSON
    -> classify_orphans (policy, this file) -> report

A *production orphan* is a type defined in production source (not under /Debug/ or
Tests/) whose every reference is also outside production -- i.e. it is only kept
alive by the catalog (Debug/) or by tests, or has no references at all. Same-file
references DO count as production use: a type used within its own file is real use.

The extraction (kgindex, Swift) carries no policy; all judgement lives here so it
stays unit-testable. Feed captured records via --records-json to test or iterate
without a build.

Exit codes: 0 success (warn-only, even with orphans) | 1 with --strict if any
orphan found, or on build/scan failure | 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = "kg.ui.deadcode.v1"
DEFAULT_KINDS = ("struct", "class", "enum", "protocol")
DEFAULT_NONPROD_MARKERS = ("/Debug/", "Tests/")
DEFAULT_SOURCE_ROOT = "ios/BooksBrowser/"

OPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = OPS_DIR.parent


# --------------------------------------------------------------------------- #
# Policy (pure functions — unit-tested directly)
# --------------------------------------------------------------------------- #
def _has_marker(path: str, markers: tuple[str, ...]) -> bool:
    return any(m in path for m in markers)


def classify_orphans(
    records: dict,
    *,
    nonprod_path_markers: tuple[str, ...] = DEFAULT_NONPROD_MARKERS,
    kinds: tuple[str, ...] = DEFAULT_KINDS,
) -> list[dict]:
    """Return production-orphan symbols, sorted by (totalRefs asc, name).

    A symbol is a candidate iff its kind is in `kinds` and its definition path
    is production (no nonprod marker). It is an orphan iff it has zero production
    references. Same-file references count as production (they live in a
    production file, so they carry no nonprod marker).
    """
    kind_set = set(kinds)
    out: list[dict] = []
    for sym in records.get("symbols", []):
        if sym.get("kind") not in kind_set:
            continue
        def_path = sym.get("def", {}).get("path", "")
        if _has_marker(def_path, nonprod_path_markers):
            continue  # definition itself is debug/test code — not a production orphan
        total = 0
        prod = 0
        for ref in sym.get("refs", []):
            roles = ref.get("roles", [])
            if "definition" in roles:
                continue
            total += 1
            if not _has_marker(ref.get("path", ""), nonprod_path_markers):
                prod += 1
        if prod == 0:
            out.append(
                {
                    "kind": sym.get("kind"),
                    "name": sym.get("name"),
                    "usr": sym.get("usr"),
                    "def": sym.get("def"),
                    "totalRefs": total,
                    "prodRefs": prod,
                }
            )
    out.sort(key=lambda o: (o["totalRefs"], o["name"]))
    return out


# --------------------------------------------------------------------------- #
# Records acquisition (build + kgindex)  — side-effecting
# --------------------------------------------------------------------------- #
def _run_kgindex(store_path: str, source_root: str, kinds: tuple[str, ...]) -> dict:
    binary = subprocess.run(
        ["bash", str(OPS_DIR / "lib" / "kgindex_build.sh")],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    proc = subprocess.run(
        [binary, store_path, source_root, "--kinds", ",".join(kinds)],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(proc.stdout)


def _verdict_field(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for tok in path.read_text().split():
        if tok.startswith(key + "="):
            return tok[len(key) + 1 :]
    return None


def acquire_records_via_build(source_root: str, kinds: tuple[str, ...]) -> dict:
    """Run an isolated clean iOS build, then kgindex over its IndexStore.

    Isolation (KG_IOS_BUILD_DERIVED_DATA_ROOT) avoids the shared cache, whose
    cross-worktree records double-count USR references and make ref counts
    untrustworthy for orphan detection.
    """
    tmp_dd = Path(tempfile.mkdtemp(prefix="kg-ui-deadcode-dd."))
    try:
        env = dict(os.environ, KG_IOS_BUILD_DERIVED_DATA_ROOT=str(tmp_dd))
        print(f"[ui_deadcode] isolated build -> {tmp_dd}", file=sys.stderr)
        rc = subprocess.run(
            ["./ops/ios_ops.sh", "build"], cwd=PROJECT_ROOT, env=env
        ).returncode
        verdict = Path(os.environ.get("TMPDIR", "/tmp")) / "kg_ios_build_verdict"
        result = _verdict_field(verdict, "RESULT")
        if rc != 0 or result != "ok":
            raise SystemExit(
                f"[ui_deadcode] build failed (rc={rc}, RESULT={result}); see {verdict}"
            )
        store = tmp_dd / "Index.noindex" / "DataStore"
        if not store.is_dir():
            raise SystemExit(f"[ui_deadcode] IndexStore not found at {store}")
        return _run_kgindex(str(store), source_root, kinds)
    finally:
        subprocess.run(["rm", "-rf", str(tmp_dd)])


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(records: dict, orphans: list[dict], source_root: str) -> dict:
    return {
        "schema": SCHEMA,
        "generated_at": _utc_now(),
        "sourceRoot": source_root,
        "scanned": len(records.get("symbols", [])),
        "orphanCount": len(orphans),
        "orphans": orphans,
    }


def print_human(payload: dict) -> None:
    orphans = payload["orphans"]
    print(f"UI dead-code scan — {payload['scanned']} symbol(s) under {payload['sourceRoot']}")
    if not orphans:
        print("  no production orphans ✓")
        return
    print(f"  {len(orphans)} production orphan(s):")
    for o in orphans:
        loc = o.get("def", {})
        rel = loc.get("path", "").split(payload["sourceRoot"], 1)[-1]
        print(f"    {o['kind']:8} {o['name']:32} refs={o['totalRefs']:<3} {rel}:{loc.get('line')}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--build", action="store_true", help="run an isolated clean build, then scan (default)")
    src.add_argument("--store-path", help="scan an existing IndexStore DataStore, skip build")
    src.add_argument("--records-json", help="read pre-captured kgindex records JSON, skip build+scan")
    p.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"source-root substring (default: {DEFAULT_SOURCE_ROOT})")
    p.add_argument("--kinds", default=",".join(DEFAULT_KINDS), help=f"comma-separated symbol kinds (default: {','.join(DEFAULT_KINDS)})")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument("--strict", action="store_true", help="exit 1 if any orphan is found")
    args = p.parse_args(argv)

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    if args.records_json:
        records = json.loads(Path(args.records_json).read_text())
        source_root = records.get("sourceRoot", args.source_root)
    elif args.store_path:
        records = _run_kgindex(args.store_path, args.source_root, kinds)
        source_root = args.source_root
    else:
        records = acquire_records_via_build(args.source_root, kinds)
        source_root = args.source_root

    orphans = classify_orphans(records, kinds=kinds)
    payload = build_payload(records, orphans, source_root)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_human(payload)

    if args.strict and orphans:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
