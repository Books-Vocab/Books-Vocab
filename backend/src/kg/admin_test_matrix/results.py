from __future__ import annotations

from typing import Any

from .catalog import TEST_MATRIX_ITEMS


def bucket_status(status: str) -> str:
    s = status.upper()
    if s in {"FAILED", "XPASSED"}:
        return "failed"
    if s == "ERROR":
        return "errors"
    if s in {"SKIPPED", "XFAILED"}:
        return "skipped"
    return "passed"


def item_results(cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_item: list[dict[str, Any]] = []
    for item in TEST_MATRIX_ITEMS:
        matched = [c for c in cases if any(c["id"].startswith(prefix) for prefix in item["nodeids"])]
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for c in matched:
            counts[c["bucket"]] += 1
        if not matched:
            status = "not_run"
        elif counts["failed"] > 0 or counts["errors"] > 0:
            status = "failed"
        elif counts["passed"] > 0:
            status = "passed"
        else:
            status = "skipped"
        by_item.append({
            "id": item["id"],
            "status": status,
            "counts": counts,
            "total": len(matched),
        })
    return by_item
