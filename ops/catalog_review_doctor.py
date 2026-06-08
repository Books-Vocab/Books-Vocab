from __future__ import annotations

from pathlib import Path

from catalog_review_actions import (
    build_action_plan,
    build_shell_command,
    with_action_plan_fields,
    with_starter_plan_from_actions,
)
from catalog_review_focus import build_focus_payload
from catalog_review_repair import repair_review_state, summarize_repairs
from catalog_review_report import build_report_payload
from catalog_review_verify import verify_review_artifacts


DOCTOR_MODES = {"overview", "hero-first", "coverage-first", "cleanup"}


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
    focus_payload = build_focus_payload(full_report, limit=limit)
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
        **focus_payload,
        "blockingErrors": blocking_errors,
    }


def _build_health_base(payload: dict, *, mode: str, root: str) -> dict:
    severity = "ok"
    if payload["blockingErrors"]:
        severity = "error"
    elif payload["repair"]["repairCount"] > 0 or payload["status"] == "needs-attention":
        severity = "warn"
    can_proceed = not payload["blockingErrors"]
    should_repair_first = payload["repair"]["repairCount"] > 0
    needs_review_attention = payload["status"] == "needs-attention"
    if not can_proceed:
        recommended_operator_action = "stop-blocking-error"
    elif should_repair_first:
        recommended_operator_action = "repair-first"
    elif needs_review_attention:
        recommended_operator_action = "proceed-review"
    else:
        recommended_operator_action = "healthy-idle"
    action_plan = build_action_plan(
        primary_command=None,
        followup_command=None,
        source="idle",
        source_mode=mode,
    )
    if recommended_operator_action == "repair-first":
        action_plan = build_action_plan(
            primary_command=build_shell_command(["./ops/catalog_review_cli.py", root, "repair"]),
            followup_command=build_shell_command(["./ops/catalog_review_cli.py", root, "verify"]),
            source="repair",
            source_mode=mode,
        )
    return with_action_plan_fields({
        "severity": severity,
        "verifyStatus": payload["verify"]["status"],
        "repairCount": payload["repair"]["repairCount"],
        "blockingErrors": payload["blockingErrors"],
        "canProceed": can_proceed,
        "shouldRepairFirst": should_repair_first,
        "needsReviewAttention": needs_review_attention,
        "recommendedOperatorAction": recommended_operator_action,
        "summary": {
            "status": payload["status"],
            "blockingErrorCount": len(payload["blockingErrors"]),
        },
    }, action_plan)


def _build_cleanup_playbook(payload: dict) -> dict:
    cleanup_actions = (
        payload["cleanupRecommendations"][0]["recommendedActions"]
        if payload["cleanupRecommendations"] else []
    )
    return with_starter_plan_from_actions({
        "mode": "cleanup",
        "goal": "清掉弱訊號與工程性 screenshot debt，避免污染行銷審稿視野。",
        "steps": [
            "先按 category 批量處理 Weak promise，避免逐張消耗注意力。",
            "優先清掉 count 最大的非核心分類，讓 review desk 聚焦在核心承諾。",
            "只有在 cleanup 降到可控後，再回到核心 promise 做最終選圖。",
        ],
    },
        cleanup_actions,
        source_mode="cleanup",
    )


def _resolve_mode_view(payload: dict, *, mode: str) -> tuple[list[dict], dict]:
    if mode == "hero-first":
        return payload["heroFirstCoreRecommendations"], payload["heroFirstPlaybook"]
    if mode == "coverage-first":
        return payload["coverageFirstCoreRecommendations"], payload["coverageFirstPlaybook"]
    if mode == "cleanup":
        return payload["cleanupRecommendations"], _build_cleanup_playbook(payload)
    raise ValueError(f"Unsupported doctor mode: {mode}")


def project_doctor_view(payload: dict, *, mode: str) -> dict:
    if mode == "overview":
        return payload
    root = str(Path(payload["state"]).parent)
    health = _build_health_base(payload, mode=mode, root=root)
    recommendations, playbook = _resolve_mode_view(payload, mode=mode)
    view = {
        "status": payload["status"],
        "mode": mode,
        "health": health,
        "recommendations": recommendations,
        "playbook": playbook,
    }
    if health["recommendedOperatorAction"] == "proceed-review":
        health = with_action_plan_fields(health, playbook["starterPlan"])
        view["health"] = health
    return view
