#!/usr/bin/env -S uv run --python 3.13 python
"""Record an append-only human visual review for one stable UITest run."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uitest_evidence_contract import bundle_sha256_for_run_root
from uitest_review_page import load_manifest


def evidence_root_sha256(run_root: Path, manifest: dict[str, Any]) -> str:
    return bundle_sha256_for_run_root(run_root, manifest)


def attestation_matches_current_bundle(
    run_root: Path,
    entry: dict[str, Any],
) -> bool:
    expected = entry.get("bundleSHA256") or entry.get("evidenceRootSHA256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    try:
        manifest = load_manifest(run_root / "review_manifest.json", screenshot_dir=run_root)
        return bundle_sha256_for_run_root(run_root, manifest) == expected
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _load_review_state(state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return {"schema": "kg.ui.review-state.v2", "entries": []}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("review_state.json must be an object")
    entries = state.get("entries")
    # v1 was emitted by the review-page bootstrap with an unusable empty object.
    # Migrate only that empty shape; never reinterpret non-empty legacy data.
    if state.get("schema") == "kg.ui.review-state.v1" and entries == {}:
        return {"schema": "kg.ui.review-state.v2", "entries": []}
    if state.get("schema") not in {None, "kg.ui.review-state.v1", "kg.ui.review-state.v2"}:
        raise ValueError(f"unsupported review_state.json schema: {state.get('schema')!r}")
    if not isinstance(entries, list):
        raise ValueError("review_state.json entries must be an append-only list")
    return state


def _atomic_write_review_state(state_path: Path, state: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.", suffix=".tmp", dir=state_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, state_path)
        directory_descriptor = os.open(state_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def attest(
    run_root: Path,
    *,
    reviewer: str,
    status: str,
    notes: str,
    asset_ids: list[str] | None = None,
    all_steps: bool = False,
    visual_checks: list[str] | None = None,
) -> dict[str, Any]:
    if status not in {"pass", "fail"}:
        raise ValueError("visual attestation status must be pass or fail")
    if not reviewer.strip():
        raise ValueError("reviewer must not be empty")
    if not notes.strip():
        raise ValueError("visual attestation notes must not be empty")

    manifest_path = run_root / "review_manifest.json"
    manifest = load_manifest(manifest_path, screenshot_dir=run_root)
    available = [str(item["assetID"]) for item in manifest["items"]]
    if len(available) != len(set(available)):
        raise ValueError("visual evidence manifest assetIDs must be unique")
    requested = available if all_steps else list(dict.fromkeys(asset_ids or []))
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"attestation references unknown assetID(s): {unknown}")
    if not requested:
        raise ValueError("attestation must name reviewed assets or use --all-steps")
    if status == "pass" and set(requested) != set(available):
        raise ValueError("a pass attestation must cover every manifest asset; use --all-steps")
    checks = list(dict.fromkeys(check.strip() for check in (visual_checks or []) if check.strip()))
    if status == "pass" and not checks:
        raise ValueError("a pass attestation must name visual checks with --visual-check")

    bundle_sha256 = evidence_root_sha256(run_root, manifest)
    entry = {
        "reviewer": reviewer.strip(),
        "status": status,
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assetIDs": requested,
        "notes": notes.strip(),
        "visualChecks": checks,
        "manifestSHA256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "bundleSHA256": bundle_sha256,
        "evidenceRootSHA256": bundle_sha256,
        "provenance": manifest.get("provenance"),
    }
    state_path = run_root / "review_state.json"
    run_root.mkdir(parents=True, exist_ok=True)
    lock_path = Path(tempfile.gettempdir()) / (
        "kg-ui-review-state-" + hashlib.sha256(str(state_path.resolve()).encode()).hexdigest() + ".lock"
    )
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _load_review_state(state_path)
        state["schema"] = "kg.ui.review-state.v2"
        state["entries"] = [*state["entries"], entry]
        _atomic_write_review_state(state_path, state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--status", required=True, choices=["pass", "fail"])
    parser.add_argument("--notes", required=True)
    parser.add_argument("--asset-id", action="append", default=[])
    parser.add_argument("--visual-check", action="append", default=[])
    parser.add_argument("--all-steps", action="store_true")
    args = parser.parse_args()
    try:
        entry = attest(
            args.run_root,
            reviewer=args.reviewer,
            status=args.status,
            notes=args.notes,
            asset_ids=args.asset_id,
            all_steps=args.all_steps,
            visual_checks=args.visual_check,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "kg.ui.review-attestation.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps({"schema": "kg.ui.review-attestation.v1", "status": "recorded", "entry": entry}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
