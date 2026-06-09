"""Shared kgindex records acquisition for ops/ UI tooling (ui_deadcode, ui_graph).

A plain stdlib module (no shebang / PEP723) imported by the uv-script CLIs via
`sys.path.insert(..., ops/lib)`. It centralizes the three ways to obtain neutral
kgindex records so policy/graph consumers stay DRY:

  - records_json: read a pre-captured kgindex JSON (test / fast-iterate seam)
  - store_path:   run kgindex over an existing IndexStore DataStore
  - build:        isolated clean iOS build → kgindex (the default, trustworthy)

All diagnostics go to stderr so a caller's stdout stays machine-clean for --json.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = OPS_DIR.parent


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_kgindex(store_path: str, source_root: str, kinds: tuple[str, ...]) -> dict:
    """Build (or reuse cached) kgindex, run it over an IndexStore, return records."""
    binary = subprocess.run(
        ["bash", str(OPS_DIR / "lib" / "kgindex_build.sh")],
        check=True, text=True, capture_output=True,
    ).stdout.strip()
    proc = subprocess.run(
        [binary, store_path, source_root, "--kinds", ",".join(kinds)],
        check=True, text=True, capture_output=True,
    )
    return json.loads(proc.stdout)


def verdict_field(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for tok in path.read_text().split():
        if tok.startswith(key + "="):
            return tok[len(key) + 1:]
    return None


def acquire_via_build(source_root: str, kinds: tuple[str, ...], *, label: str = "kgindex") -> dict:
    """Run an isolated clean iOS build, then kgindex over its IndexStore.

    Isolation (KG_IOS_BUILD_DERIVED_DATA_ROOT) avoids the shared cache, whose
    cross-worktree records double-count USR references and make ref/edge data
    untrustworthy.
    """
    tmp_dd = Path(tempfile.mkdtemp(prefix=f"kg-{label}-dd."))
    try:
        env = dict(os.environ, KG_IOS_BUILD_DERIVED_DATA_ROOT=str(tmp_dd))
        print(f"[{label}] isolated build -> {tmp_dd}", file=sys.stderr)
        # Redirect the build's stdout to stderr: ios_build.sh prints [ios_build]
        # progress to stdout, which would otherwise corrupt the caller's --json.
        rc = subprocess.run(
            ["./ops/ios_ops.sh", "build"], cwd=PROJECT_ROOT, env=env, stdout=sys.stderr
        ).returncode
        verdict = Path(os.environ.get("TMPDIR", "/tmp")) / "kg_ios_build_verdict"
        result = verdict_field(verdict, "RESULT")
        if rc != 0 or result != "ok":
            raise SystemExit(f"[{label}] build failed (rc={rc}, RESULT={result}); see {verdict}")
        store = tmp_dd / "Index.noindex" / "DataStore"
        if not store.is_dir():
            raise SystemExit(f"[{label}] IndexStore not found at {store}")
        return run_kgindex(str(store), source_root, kinds)
    finally:
        # best-effort cleanup; a leak is harmless (mkdtemp) but surface nonzero rm.
        rc = subprocess.run(["rm", "-rf", str(tmp_dd)], check=False).returncode
        if rc != 0:
            print(f"[{label}] warning: failed to remove {tmp_dd} (rc={rc})", file=sys.stderr)


def acquire(
    source_root: str,
    kinds: tuple[str, ...],
    *,
    records_json: str | None = None,
    store_path: str | None = None,
    label: str = "kgindex",
) -> tuple[dict, str]:
    """Unified records acquisition. Returns (records, effective_source_root).

    records_json takes precedence, then store_path, else an isolated build.
    """
    if records_json:
        records = json.loads(Path(records_json).read_text())
        return records, records.get("sourceRoot", source_root)
    if store_path:
        return run_kgindex(store_path, source_root, kinds), source_root
    return acquire_via_build(source_root, kinds, label=label), source_root
