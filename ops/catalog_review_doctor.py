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

    def first_action(items: list[dict]) -> str | None:
        if not items or not items[0]["recommendedActions"]:
            return None
        return items[0]["recommendedActions"][0]["command"]

    return {
        "heroFirstPlaybook": {
            "mode": "hero-first",
            "goal": "先抓最能代表產品承諾的 hero 候選，再進行變體比較與 shortlist。",
            "steps": [
                "先看第一名 promise 的 hero 候選，確認是否能單張自證承諾。",
                "對同一 promise 做 variant 比較，避免先被大面積 coverage 吸走注意力。",
                "確認 hero 候選後，再回頭處理該 promise 的 top category 收斂。",
            ],
            "firstCommand": first_action(hero_first),
        },
        "coverageFirstPlaybook": {
            "mode": "coverage-first",
            "goal": "先清最大覆蓋債，快速把高量未審分類壓縮到可管理範圍。",
            "steps": [
                "先處理第一名 promise 的最大未審 category，批量標成 review 候選。",
                "用 category 為單位做批次過濾，避免逐張翻圖。",
                "coverage 壓下來後，再回頭從該 promise 內挑 hero 圖做 shortlist。",
            ],
            "firstCommand": first_action(coverage_first),
        },
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


def project_doctor_view(payload: dict, *, mode: str) -> dict:
    if mode == "overview":
        return payload
    view = {
        "status": payload["status"],
        "mode": mode,
        "verify": payload["verify"],
        "repair": payload["repair"],
        "blockingErrors": payload["blockingErrors"],
    }
    if mode == "hero-first":
        view["recommendations"] = payload["heroFirstCoreRecommendations"]
        view["playbook"] = payload["heroFirstPlaybook"]
        return view
    if mode == "coverage-first":
        view["recommendations"] = payload["coverageFirstCoreRecommendations"]
        view["playbook"] = payload["coverageFirstPlaybook"]
        return view
    if mode == "cleanup":
        view["recommendations"] = payload["cleanupRecommendations"]
        view["playbook"] = {
            "mode": "cleanup",
            "goal": "清掉弱訊號與工程性 screenshot debt，避免污染行銷審稿視野。",
            "steps": [
                "先按 category 批量處理 Weak promise，避免逐張消耗注意力。",
                "優先清掉 count 最大的非核心分類，讓 review desk 聚焦在核心承諾。",
                "只有在 cleanup 降到可控後，再回到核心 promise 做最終選圖。",
            ],
            "firstCommand": payload["cleanupRecommendations"][0]["recommendedActions"][0]["command"]
            if payload["cleanupRecommendations"] and payload["cleanupRecommendations"][0]["recommendedActions"]
            else None,
        }
        return view
    raise ValueError(f"Unsupported doctor mode: {mode}")
