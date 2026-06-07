from __future__ import annotations

from pathlib import Path

from catalog_review_actions import build_action_plan, with_action_plan_fields, with_starter_plan
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
DOCTOR_MODES = {"overview", "hero-first", "coverage-first", "cleanup"}


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


def build_core_modes(core_recommendations: list[dict], *, limit: int | None) -> dict:
    hero_first = sorted(
        core_recommendations,
        key=lambda item: (
            -item["heroUnmarked"],
            -item["attentionScore"],
            -item["unmarked"],
            item["promise"],
        ),
    )
    coverage_first = sorted(
        core_recommendations,
        key=lambda item: (
            -item["unmarked"],
            -item["attentionScore"],
            -item["heroUnmarked"],
            item["promise"],
        ),
    )
    if limit is not None:
        hero_first = hero_first[:limit]
        coverage_first = coverage_first[:limit]
    return {
        "heroFirstCoreRecommendations": hero_first,
        "coverageFirstCoreRecommendations": coverage_first,
    }


def build_core_playbooks(core_modes: dict) -> dict:
    hero_first = core_modes["heroFirstCoreRecommendations"]
    coverage_first = core_modes["coverageFirstCoreRecommendations"]

    def followup_command(items: list[dict]) -> str | None:
        if not items or len(items[0]["recommendedActions"]) <= 1:
            return None
        return items[0]["recommendedActions"][1]["command"]

    def first_command(items: list[dict]) -> str | None:
        if not items or not items[0]["recommendedActions"]:
            return None
        inspect_action = next(
            (
                action for action in items[0]["recommendedActions"]
                if action.get("commandAction", {}).get("kind") == "inspect"
            ),
            None,
        )
        if inspect_action:
            return inspect_action["command"]
        return items[0]["recommendedActions"][0]["command"]

    hero_first_command = first_command(hero_first)
    coverage_first_command = first_command(coverage_first)
    hero_followup_command = followup_command(hero_first)
    coverage_followup_command = followup_command(coverage_first)
    return {
        "heroFirstPlaybook": with_starter_plan({
            "mode": "hero-first",
            "goal": "先抓最能代表產品承諾的 hero 候選，再進行變體比較與 shortlist。",
            "steps": [
                "先看第一名 promise 的 hero 候選，確認是否能單張自證承諾。",
                "對同一 promise 做 variant 比較，避免先被大面積 coverage 吸走注意力。",
                "確認 hero 候選後，再回頭處理該 promise 的 top category 收斂。",
            ],
        },
            primary_command=hero_first_command,
            followup_command=hero_followup_command,
            source_mode="hero-first",
        ),
        "coverageFirstPlaybook": with_starter_plan({
            "mode": "coverage-first",
            "goal": "先清最大覆蓋債，快速把高量未審分類壓縮到可管理範圍。",
            "steps": [
                "先處理第一名 promise 的最大未審 category，批量標成 review 候選。",
                "用 category 為單位做批次過濾，避免逐張翻圖。",
                "coverage 壓下來後，再回頭從該 promise 內挑 hero 圖做 shortlist。",
            ],
        },
            primary_command=coverage_first_command,
            followup_command=coverage_followup_command,
            source_mode="coverage-first",
        ),
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
    core_modes = build_core_modes(focus_lanes["coreRecommendations"], limit=limit)
    core_playbooks = build_core_playbooks(core_modes)
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
        **core_modes,
        **core_playbooks,
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
            primary_command=f"./ops/catalog_review_cli.py {root} repair",
            followup_command=f"./ops/catalog_review_cli.py {root} verify",
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
    cleanup_primary = (
        payload["cleanupRecommendations"][0]["recommendedActions"][0]["command"]
        if payload["cleanupRecommendations"] and payload["cleanupRecommendations"][0]["recommendedActions"]
        else None
    )
    cleanup_followup = (
        payload["cleanupRecommendations"][0]["recommendedActions"][1]["command"]
        if payload["cleanupRecommendations"] and len(payload["cleanupRecommendations"][0]["recommendedActions"]) > 1
        else None
    )
    return with_starter_plan({
        "mode": "cleanup",
        "goal": "清掉弱訊號與工程性 screenshot debt，避免污染行銷審稿視野。",
        "steps": [
            "先按 category 批量處理 Weak promise，避免逐張消耗注意力。",
            "優先清掉 count 最大的非核心分類，讓 review desk 聚焦在核心承諾。",
            "只有在 cleanup 降到可控後，再回到核心 promise 做最終選圖。",
        ],
    },
        primary_command=cleanup_primary,
        followup_command=cleanup_followup,
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
