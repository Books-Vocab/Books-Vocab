from __future__ import annotations

from catalog_review_repair import repair_review_state, summarize_repairs
from catalog_review_report import build_report_payload
from catalog_review_verify import verify_review_artifacts


PROMISE_WEIGHTS = {
    "Read": 5,
    "Connect": 4,
    "Retain": 4,
    "Continue": 3,
    "Weak": 1,
}
CORE_PROMISES = {"Read", "Connect", "Retain", "Continue"}


def build_focus_recommendations(report: dict, *, limit: int | None) -> list[dict]:
    recommendations: list[dict] = []
    action_by_promise: dict[str, list[dict]] = {}
    for action in report["nextActions"]:
        action_by_promise.setdefault(action["promise"], []).append(action)

    for promise in report["promises"]:
        weight = PROMISE_WEIGHTS.get(promise["promise"], 1)
        attention_score = (
            promise["heroUnmarked"] * weight * 10
            + promise["unmarked"] * weight
            + len(promise["topUnmarkedCategories"]) * 5
        )
        recommendations.append({
            "promise": promise["promise"],
            "attentionScore": attention_score,
            "heroUnmarked": promise["heroUnmarked"],
            "unmarked": promise["unmarked"],
            "topCategory": promise["topUnmarkedCategories"][0] if promise["topUnmarkedCategories"] else None,
            "recommendedActions": action_by_promise.get(promise["promise"], [])[:2],
        })

    recommendations.sort(
        key=lambda item: (
            -item["attentionScore"],
            -item["heroUnmarked"],
            -item["unmarked"],
            item["promise"],
        )
    )
    return recommendations if limit is None else recommendations[:limit]


def split_focus_lanes(recommendations: list[dict], *, limit: int | None) -> dict:
    core = [
        item for item in recommendations
        if item["promise"] in CORE_PROMISES and (item["heroUnmarked"] > 0 or item["unmarked"] > 0)
    ]
    cleanup = [
        item for item in recommendations
        if item["promise"] not in CORE_PROMISES
    ]
    if limit is not None:
        core = core[:limit]
        cleanup = cleanup[:limit]
    return {
        "coreRecommendations": core,
        "cleanupRecommendations": cleanup,
    }


def build_doctor_payload(
    manifest: dict,
    state: dict,
    html_text: str,
    *,
    effective_status_fn,
    root: str,
    limit: int | None,
) -> dict:
    verify = verify_review_artifacts(manifest, state, html_text)
    _, repairs = repair_review_state(manifest, state)
    repair = summarize_repairs(repairs, limit=limit)
    full_report = build_report_payload(manifest, state, effective_status_fn=effective_status_fn, root=root, limit=limit)
    focus_recommendations = build_focus_recommendations(full_report, limit=limit)
    focus_lanes = split_focus_lanes(focus_recommendations, limit=limit)
    report = dict(full_report)
    report["nextActions"] = report["nextActions"][:limit] if limit is not None else report["nextActions"]
    blocking_errors = [error for error in verify["errors"] if error not in {"state-schema-errors"}]
    status = "ok"
    if blocking_errors:
        status = "error"
    elif repair["repairCount"] > 0 or any(promise["heroUnmarked"] > 0 for promise in report["promises"]):
        status = "needs-attention"
    return {
        "status": status,
        "verify": verify,
        "repair": repair,
        "report": report,
        "focusRecommendations": focus_recommendations,
        **focus_lanes,
        "blockingErrors": blocking_errors,
    }
