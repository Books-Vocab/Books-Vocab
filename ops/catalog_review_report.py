from __future__ import annotations

from collections import Counter, defaultdict


PROMISE_ORDER = ["Read", "Connect", "Retain", "Continue", "Weak"]


def build_report_payload(manifest: dict, state: dict, *, effective_status_fn, root: str, limit: int | None) -> dict:
    by_promise: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0,
            "shortlist": 0,
            "review": 0,
            "reject": 0,
            "unmarked": 0,
            "heroTotal": 0,
            "heroUnmarked": 0,
            "unmarkedCategories": Counter(),
        }
    )

    for item in manifest["items"]:
        promise = item["promise"]
        bucket = by_promise[promise]
        bucket["total"] += 1
        effective = effective_status_fn(item, state) or "unmarked"
        bucket[effective] += 1
        if item.get("heroCandidate"):
            bucket["heroTotal"] += 1
            if effective == "unmarked":
                bucket["heroUnmarked"] += 1
        if effective == "unmarked":
            bucket["unmarkedCategories"][item["category"]] += 1

    promise_report = []
    next_actions = []
    for promise in PROMISE_ORDER:
        if promise not in by_promise:
            continue
        bucket = by_promise[promise]
        top_unmarked = [
            {"category": category, "count": count}
            for category, count in bucket["unmarkedCategories"].most_common(limit)
        ] if limit is not None else [
            {"category": category, "count": count}
            for category, count in bucket["unmarkedCategories"].most_common()
        ]
        promise_report.append(
            {
                "promise": promise,
                "total": bucket["total"],
                "shortlist": bucket["shortlist"],
                "review": bucket["review"],
                "reject": bucket["reject"],
                "unmarked": bucket["unmarked"],
                "heroTotal": bucket["heroTotal"],
                "heroUnmarked": bucket["heroUnmarked"],
                "topUnmarkedCategories": top_unmarked,
            }
        )
        if bucket["heroUnmarked"] > 0:
            next_actions.append({
                "kind": "hero-unmarked",
                "promise": promise,
                "count": bucket["heroUnmarked"],
                "command": (
                    f"./ops/catalog_review_cli.py {root} list --promise {promise} --search hero --limit {limit or 10}"
                ),
            })
        if top_unmarked:
            top_category = top_unmarked[0]["category"]
            next_actions.append({
                "kind": "top-unmarked-category",
                "promise": promise,
                "category": top_category,
                "count": top_unmarked[0]["count"],
                "command": (
                    f"./ops/catalog_review_cli.py {root} apply --promise {promise} --category '{top_category}' "
                    f"--status review --limit {limit or 10} --dry-run"
                ),
            })

    return {
        "status": "ok",
        "totalImages": manifest["totalImages"],
        "stateCounts": manifest.get("stateCounts", {}),
        "promises": promise_report,
        "nextActions": next_actions,
    }
