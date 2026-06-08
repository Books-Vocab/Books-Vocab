from __future__ import annotations

from collections import Counter


def verify_review_artifacts(manifest: dict, state: dict, html_text: str) -> dict:
    manifest_items = manifest["items"]
    manifest_ids = [item["assetID"] for item in manifest_items]
    manifest_item_map = {item["assetID"]: item for item in manifest_items}
    state_entries = state["entries"]
    state_ids = set(state_entries)

    missing_state_ids = [asset_id for asset_id in manifest_ids if asset_id not in state_ids]
    dangling_state_ids = sorted(state_ids.difference(manifest_ids))
    duplicate_manifest_ids = [asset_id for asset_id, count in Counter(manifest_ids).items() if count > 1]
    derived_state_counts = Counter(
        (entry.get("status") or "")
        for entry in state_entries.values()
        if entry.get("status")
    )

    schema_errors: list[dict] = []
    metadata_drift_ids: list[str] = []

    for asset_id in manifest_ids:
        entry = state_entries.get(asset_id)
        if entry is None:
            continue
        expected = manifest_item_map[asset_id]
        drift_fields = [
            field
            for field in ("promise", "category", "title", "device", "appearance", "relPath")
            if entry.get(field) != expected.get(field)
        ]
        if drift_fields:
            metadata_drift_ids.append(asset_id)

        status = entry.get("status")
        note = entry.get("note")
        updated_at = entry.get("updatedAt")
        history = entry.get("history")

        if not isinstance(status, str):
            schema_errors.append({"assetID": asset_id, "error": "invalid-status-type"})
        if not isinstance(note, str):
            schema_errors.append({"assetID": asset_id, "error": "invalid-note-type"})
        if history is None:
            schema_errors.append({"assetID": asset_id, "error": "missing-history"})
            continue
        if not isinstance(history, list):
            schema_errors.append({"assetID": asset_id, "error": "invalid-history-type"})
            continue
        if updated_at is not None and not isinstance(updated_at, str):
            schema_errors.append({"assetID": asset_id, "error": "invalid-updatedAt-type"})

        if history:
            last_event = history[-1]
            if not isinstance(last_event, dict):
                schema_errors.append({"assetID": asset_id, "error": "invalid-history-event"})
                continue
            for key in ("at", "action", "status", "note"):
                if not isinstance(last_event.get(key), str):
                    schema_errors.append({"assetID": asset_id, "error": f"invalid-history-{key}"})
            if updated_at != last_event.get("at"):
                schema_errors.append({"assetID": asset_id, "error": "updatedAt-history-mismatch"})
        else:
            if status or note:
                schema_errors.append({"assetID": asset_id, "error": "annotation-without-history"})
            if updated_at:
                schema_errors.append({"assetID": asset_id, "error": "updatedAt-without-history"})

    errors = []
    if manifest.get("schema") != "kg.catalog.review.v1":
        errors.append("invalid-manifest-schema")
    if state.get("schema") != "kg.catalog.review.state.v1":
        errors.append("invalid-state-schema")
    if manifest["totalImages"] != len(manifest_items):
        errors.append("manifest-total-mismatch")
    if len(state_entries) != len(manifest_items):
        errors.append("state-entry-count-mismatch")
    if duplicate_manifest_ids:
        errors.append("duplicate-manifest-asset-ids")
    if missing_state_ids:
        errors.append("missing-state-entries")
    if dangling_state_ids:
        errors.append("dangling-state-entries")
    if manifest.get("stateCounts", {}) != dict(derived_state_counts):
        errors.append("state-counts-mismatch")
    if metadata_drift_ids:
        errors.append("state-metadata-drift")
    if schema_errors:
        errors.append("state-schema-errors")
    if f'"stateFile": "{manifest.get("stateFile")}"' not in html_text:
        errors.append("html-missing-statefile")
    if '"assetID": "' not in html_text:
        errors.append("html-missing-assetid-payload")

    return {
        "status": "ok" if not errors else "error",
        "totalImages": manifest["totalImages"],
        "manifestItemCount": len(manifest_items),
        "stateEntryCount": len(state_entries),
        "duplicateManifestAssetIDs": duplicate_manifest_ids,
        "missingStateAssetIDs": missing_state_ids,
        "danglingStateAssetIDs": dangling_state_ids,
        "metadataDriftAssetIDs": metadata_drift_ids,
        "schemaErrors": schema_errors,
        "manifestStateCounts": manifest.get("stateCounts", {}),
        "derivedStateCounts": dict(derived_state_counts),
        "errors": errors,
    }
