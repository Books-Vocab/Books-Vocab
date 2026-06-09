#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""UI dead-code scanner for the iOS app (production-orphan struct/class; enum/protocol opt-in).

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

Default kinds are struct + class (the trustworthy gate set). enum/protocol can be
requested via --kinds but produce false positives (Codable CodingKeys, caseless
namespace enums) and are for hand triage, not gating — see DEFAULT_KINDS.

Exit codes: 0 success (warn-only, even with orphans) | 1 with --strict if any
orphan found, or on build/scan failure | 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import kgindex_records  # noqa: E402  (ops/lib shared module)

SCHEMA = "kg.ui.deadcode.v1"
# struct + class is the trustworthy gate set (proven clean on a post-cleanup tree).
# enum/protocol are available via --kinds but surface systematic FALSE POSITIVES,
# so they are NOT in the default and must be triaged by hand, not gated on:
#   - Codable `CodingKeys` (compiler-synthesized; never an explicit reference)
#   - caseless namespace enums (e.g. `DesignTokens.Easing`): member access creates
#     a reference to the leaf member, not to the intermediate enum container, so a
#     heavily-used namespace enum still reads as zero-ref.
DEFAULT_KINDS = ("struct", "class")
# Names that are never explicitly referenced even when used (compiler synthesis).
ALWAYS_USED_NAMES = frozenset({"CodingKeys"})
# Markers are plain substrings tested against full paths (a deliberate, configurable
# primitive). Slashes anchor them: "/Debug/" matches the catalog dir but not a
# hypothetical "/Debugging/"; "Tests/" matches BooksBrowserTests/ and
# BooksBrowserUITests/ (segments ending in "Tests/") while the lowercase in dirs
# like "Contests/" does not collide. Callers passing custom markers should include
# slashes to keep the same anchoring.
DEFAULT_NONPROD_MARKERS = ("/Debug/", "Tests/")
DEFAULT_SOURCE_ROOT = "ios/BooksBrowser/"


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
        if sym.get("name") in ALWAYS_USED_NAMES:
            continue  # compiler-synthesized use; never a real orphan
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
# Reporting
# --------------------------------------------------------------------------- #
def build_payload(records: dict, orphans: list[dict], source_root: str) -> dict:
    return {
        "schema": SCHEMA,
        "generated_at": kgindex_records.utc_now(),
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

    records, source_root = kgindex_records.acquire(
        args.source_root, kinds,
        records_json=args.records_json, store_path=args.store_path, label="ui_deadcode",
    )

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
