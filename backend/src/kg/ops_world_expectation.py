"""從 seed/steps 靜態導出 world expectation（kg.ops_world_expectation.v1）。

**防 tautology 鐵則**：本模組只讀宣告 spec（seed JSON + capture profile steps），
**絕不讀 DB / 不跑 ops_edit**。導出的 expectation 交給 ``ops_world_diff.diff_world_state``
與 ``ops_world_projection.project_user_world``（真讀盤的 actual 側）比對，驗的是
「宣告意圖 vs 儲存實況」的語意落差，而非自我確認。

**只導 verbatim 落地欄位**（identity + 直寫描述欄）。刻意排除由 ops_edit 計算/轉換的
欄位（card ``review.state`` → review_count/last_reviewed_at、active-notebook 的
name→id 解析），因為導 raw 值會 false-fail、導 computed 值會重耦合成 tautology。
這些留給真讀盤側，不在 expectation 斷言範圍。

**不在斷言範圍**：card↔notebook membership（derive 不導 card.notebook），與
``ops_world_diff`` 以 content 為 card key 的 scope 一致；卡片落錯 notebook 不由此 diff 抓。
"""

from __future__ import annotations

from typing import Any

SPEC_SCHEMA = "kg.ops_world_expectation.v1"

# card 上可 verbatim 斷言的欄位。判準是 (ops_edit 直寫) ∩ (project_user_world 有 surface)
# —— 缺後者會 false-fail：欄位確實寫進 DB，但 projection 的 SELECT 沒撈，actual 側永遠
# 缺鍵。pos 即屬此例（寫入但 _load_cards 不撈），故不導。
_CARD_VERBATIM_FIELDS = ("meaning",)
# notebook 上可 verbatim 斷言的欄位。
_NOTEBOOK_VERBATIM_FIELDS = ("cover_pattern", "color")


def _derive_notebooks(seed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for nb in seed.get("notebooks", []):
        if not isinstance(nb, dict):
            continue
        name = nb.get("name")
        if not isinstance(name, str) or not name:
            continue
        entry: dict[str, Any] = {"name": name}
        for field in _NOTEBOOK_VERBATIM_FIELDS:
            if field in nb:
                entry[field] = nb[field]
        out.append(entry)
    return out


def _derive_cards(seed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in seed.get("cards", []):
        if not isinstance(card, dict):
            continue
        content = card.get("content")
        if not isinstance(content, str) or not content:
            continue
        entry: dict[str, Any] = {"content": content}
        for field in _CARD_VERBATIM_FIELDS:
            if field in card:
                entry[field] = card[field]
        out.append(entry)
    return out


def _derive_graphs(seed: dict[str, Any]) -> list[dict[str, Any]]:
    by_notebook: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for link in seed.get("links", []):
        if not isinstance(link, dict):
            continue
        nb = link.get("notebook")
        frm, to, kind = link.get("from"), link.get("to"), link.get("kind")
        if not all(isinstance(x, str) and x for x in (nb, frm, to, kind)):
            continue
        if nb not in by_notebook:
            by_notebook[nb] = []
            order.append(nb)
        by_notebook[nb].append({"from": frm, "to": to, "kind": kind})
    return [{"notebook": nb, "links": by_notebook[nb]} for nb in order]


def _derive_config(steps: list[dict[str, Any]] | None) -> dict[str, Any]:
    """只從 steps 的 user-config-set 導出 verbatim-safe config 斷言。

    目前僅 ``--review-clock paused|running`` → ``review_clock.is_paused``。
    ``--active-notebook`` 需 name→id 解析（transform），刻意不導。
    """
    config: dict[str, Any] = {}
    for step in steps or []:
        if not isinstance(step, dict) or step.get("subcommand") != "user-config-set":
            continue
        args = step.get("args") or []
        if "--review-clock" in args:
            idx = args.index("--review-clock")
            if idx + 1 < len(args):
                value = args[idx + 1]
                if value in ("paused", "running"):
                    config["review_clock"] = {"is_paused": value == "paused"}
    return config


def derive_expectation(
    seed: dict[str, Any], steps: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """純宣告轉換：seed + capture profile steps → kg.ops_world_expectation.v1。

    不接觸 DB；產物可直接餵 ``diff_world_state`` 對 ``project_user_world`` 比對。
    """
    spec: dict[str, Any] = {"schema": SPEC_SCHEMA}
    config = _derive_config(steps)
    if config:
        spec["config"] = config
    notebooks = _derive_notebooks(seed)
    if notebooks:
        spec["notebooks"] = notebooks
    cards = _derive_cards(seed)
    if cards:
        spec["cards"] = cards
    graphs = _derive_graphs(seed)
    if graphs:
        spec["graphs"] = graphs
    return spec
