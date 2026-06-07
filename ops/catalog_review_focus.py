from __future__ import annotations

from catalog_review_actions import with_starter_plan_from_actions


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
    return {
        "heroFirstPlaybook": with_starter_plan_from_actions({
            "mode": "hero-first",
            "goal": "先抓最能代表產品承諾的 hero 候選，再進行變體比較與 shortlist。",
            "steps": [
                "先看第一名 promise 的 hero 候選，確認是否能單張自證承諾。",
                "對同一 promise 做 variant 比較，避免先被大面積 coverage 吸走注意力。",
                "確認 hero 候選後，再回頭處理該 promise 的 top category 收斂。",
            ],
        },
            hero_first[0]["recommendedActions"] if hero_first else [],
            source_mode="hero-first",
        ),
        "coverageFirstPlaybook": with_starter_plan_from_actions({
            "mode": "coverage-first",
            "goal": "先清最大覆蓋債，快速把高量未審分類壓縮到可管理範圍。",
            "steps": [
                "先處理第一名 promise 的最大未審 category，批量標成 review 候選。",
                "用 category 為單位做批次過濾，避免逐張翻圖。",
                "coverage 壓下來後，再回頭從該 promise 內挑 hero 圖做 shortlist。",
            ],
        },
            coverage_first[0]["recommendedActions"] if coverage_first else [],
            source_mode="coverage-first",
        ),
    }


def build_focus_payload(report: dict, *, limit: int | None) -> dict:
    recommendations = build_focus_recommendations(report, limit=limit)
    lanes = split_focus_lanes(recommendations, limit=limit)
    core_modes = build_core_modes(lanes["coreRecommendations"], limit=limit)
    core_playbooks = build_core_playbooks(core_modes)
    return {
        "focusRecommendations": recommendations,
        **lanes,
        **core_modes,
        **core_playbooks,
    }
