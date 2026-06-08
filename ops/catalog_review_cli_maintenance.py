from __future__ import annotations

import json
from pathlib import Path

from catalog_review_cli_artifacts import build_artifact_refs, load_review_artifacts, write_json
from catalog_review_cli_serialization import effective_status
from catalog_review_doctor import build_doctor_payload, project_doctor_view
from catalog_review_repair import repair_review_state, summarize_repairs
from catalog_review_sync import hydrate_manifest, write_review_outputs
from catalog_review_verify import verify_review_artifacts


def cmd_verify(root: Path) -> int:
    artifacts = load_review_artifacts(root, hydrate=False, include_html=True)
    payload = {
        **build_artifact_refs(root),
        **verify_review_artifacts(artifacts["manifest"], artifacts["state"], artifacts["html_text"]),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "ok" else 1


def cmd_repair(root: Path, *, dry_run: bool, limit: int | None, include_repairs: bool) -> int:
    artifacts = load_review_artifacts(root, hydrate=False, include_html=False)
    repaired_state, repairs = repair_review_state(artifacts["manifest"], artifacts["state"])
    hydrated_manifest = hydrate_manifest(artifacts["manifest"], repaired_state)
    repair_summary = summarize_repairs(repairs, limit=limit)
    payload = {
        "status": "ok",
        "dryRun": dry_run,
        **build_artifact_refs(root),
        "repairCount": repair_summary["repairCount"],
        "repairTypeCounts": repair_summary["repairTypeCounts"],
        "sampleRepairs": repair_summary["sampleRepairs"],
        "truncatedRepairCount": repair_summary["truncatedRepairCount"],
    }
    if include_repairs:
        payload["repairs"] = repairs
    if dry_run or not repairs:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    write_json(artifacts["state_path"], repaired_state)
    write_review_outputs(root, hydrated_manifest, repaired_state)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_doctor(root: Path, *, limit: int | None, mode: str) -> int:
    artifacts = load_review_artifacts(root, hydrate=False, include_html=True)
    full_payload = {
        **build_artifact_refs(root),
        **build_doctor_payload(
            artifacts["manifest"],
            artifacts["state"],
            artifacts["html_text"],
            effective_status_fn=effective_status,
            root=str(root),
            limit=limit,
        ),
    }
    payload = project_doctor_view(full_payload, mode=mode)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] != "error" else 1


def cmd_doctor_shortcut(root: Path, *, limit: int | None, mode: str) -> int:
    return cmd_doctor(root, limit=limit, mode=mode)
