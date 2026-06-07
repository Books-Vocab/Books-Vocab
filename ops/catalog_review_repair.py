from __future__ import annotations

from collections import Counter

from catalog_review_state import review_timestamp


def repair_review_state(manifest: dict, state: dict) -> tuple[dict, list[dict]]:
    entries = state.setdefault("entries", {})
    item_map = {item["assetID"]: item for item in manifest["items"]}
    repaired_entries: dict[str, dict] = {}
    repairs: list[dict] = []

    for asset_id, item in item_map.items():
        previous = entries.get(asset_id, {})
        history_missing = "history" not in previous
        updated_at_missing = "updatedAt" not in previous
        entry = {
            "status": previous.get("status", "") if isinstance(previous.get("status", ""), str) else "",
            "note": previous.get("note", "") if isinstance(previous.get("note", ""), str) else "",
            "promise": item["promise"],
            "category": item["category"],
            "title": item["title"],
            "device": item["device"],
            "appearance": item["appearance"],
            "relPath": item["relPath"],
            "updatedAt": previous.get("updatedAt") if isinstance(previous.get("updatedAt"), str) else None,
            "history": previous.get("history", []) if isinstance(previous.get("history", []), list) else [],
        }

        entry_repairs: list[str] = []
        if asset_id not in entries:
            entry_repairs.append("created-missing-entry")
        elif any(previous.get(field) != entry[field] for field in ("promise", "category", "title", "device", "appearance", "relPath")):
            entry_repairs.append("refreshed-metadata")
        if not isinstance(previous.get("status", ""), str):
            entry_repairs.append("normalized-status")
        if not isinstance(previous.get("note", ""), str):
            entry_repairs.append("normalized-note")
        if history_missing:
            entry_repairs.append("initialized-history")
        if not isinstance(previous.get("history", []), list):
            entry_repairs.append("normalized-history")
        if updated_at_missing:
            entry_repairs.append("initialized-updatedAt")
        if previous.get("updatedAt") is not None and not isinstance(previous.get("updatedAt"), str):
            entry_repairs.append("normalized-updatedAt")

        if entry["history"]:
            last_event = entry["history"][-1] if isinstance(entry["history"][-1], dict) else None
            valid_event = (
                isinstance(last_event, dict)
                and all(isinstance(last_event.get(key), str) for key in ("at", "action", "status", "note"))
            )
            if valid_event:
                if entry["updatedAt"] != last_event["at"]:
                    entry["updatedAt"] = last_event["at"]
                    entry_repairs.append("synced-updatedAt-to-history")
            else:
                entry["history"] = []
                entry["updatedAt"] = None
                entry_repairs.append("cleared-invalid-history")

        if not entry["history"] and (entry["status"] or entry["note"]):
            event_time = entry["updatedAt"] or review_timestamp()
            entry["history"] = [{
                "at": event_time,
                "action": "repair",
                "status": entry["status"],
                "note": entry["note"],
            }]
            entry["updatedAt"] = event_time
            entry_repairs.append("backfilled-history")
        elif not entry["history"]:
            entry["updatedAt"] = None

        repaired_entries[asset_id] = entry
        if entry_repairs:
            repairs.append({"assetID": asset_id, "repairs": entry_repairs})

    dangling_ids = sorted(set(entries).difference(item_map))
    if dangling_ids:
        repairs.extend({"assetID": asset_id, "repairs": ["removed-dangling-entry"]} for asset_id in dangling_ids)

    return {
        "schema": "kg.catalog.review.state.v1",
        "profile": state.get("profile", {}),
        "entries": repaired_entries,
    }, repairs


def summarize_repairs(repairs: list[dict], *, limit: int | None) -> dict:
    repair_type_counts = Counter()
    for repair in repairs:
        repair_type_counts.update(repair["repairs"])
    if limit is None:
        sample_repairs = repairs
    else:
        sample_repairs = repairs[:limit]
    return {
        "repairCount": len(repairs),
        "repairTypeCounts": dict(repair_type_counts),
        "sampleRepairs": sample_repairs,
        "truncatedRepairCount": max(0, len(repairs) - len(sample_repairs)),
    }
