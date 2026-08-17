"""Canonical delivery-board terms and state classification.

The board is a projection, but its vocabulary is a contract.  Keep the labels,
definitions, and mutually exclusive decision buckets here so the live board,
the terminology page, and tests cannot quietly invent different meanings.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .scope import scope_status

MODEL_SCHEMA = "kg.board.model.v1"
RESOLVED_STATUSES = ("fixed", "wont-fix")
DECISION_ORDER = (
    "dispatchable",
    "held",
    "dependency-blocked",
    "needs-grooming",
    "contract-not-ready",
)

MODEL_TERMS = (
    {
        "id": "ticket",
        "english": "Ticket",
        "chinese": "票",
        "definition": "一個已被記錄、可以被追蹤的問題或改善事項。",
        "rule": "來源是 backlog entry；不等於有人正在做。",
    },
    {
        "id": "open",
        "english": "Open",
        "chinese": "已立單",
        "definition": "問題已記錄，但尚未完成可執行的修法規格。",
        "rule": "Open 不是失敗；它代表仍在 triage／grooming 前。",
    },
    {
        "id": "groomed",
        "english": "Groomed",
        "chinese": "已梳理",
        "definition": "接手者不必重新探索，就知道要改什麼、怎麼驗收、改哪裡。",
        "rule": "由 `backlog.py list --ungroomed` 的反面判定；它是進入 queued 的必要條件，不是 claim。",
    },
    {
        "id": "contract-ready",
        "english": "Contract-ready",
        "chinese": "契約就緒",
        "definition": "修法契約已通過 preflight，且目前驗收基線確實是 red。",
        "rule": "`contract_status=ready`、`contract_baseline=red`，並有完整檢查 metadata。",
    },
    {
        "id": "queued",
        "english": "Queued",
        "chinese": "已入列",
        "definition": "已梳理、未結案、尚未被 worktree 認領的 ticket 所在的交付佇列；它是 lifecycle label，不是互斥 decision bucket。",
        "rule": "Queued 包含 dispatchable、dependency-blocked、contract-not-ready；held／active 已離開 queued。Groomed 是必要條件，但不是充分條件。",
    },
    {
        "id": "dispatchable",
        "english": "Dispatchable",
        "chinese": "可派工",
        "definition": "現在可以安全地被下一個 worker 取得。",
        "rule": "Groomed ∧ unresolved ∧ unclaimed ∧ unblocked ∧ contract-ready。",
    },
    {
        "id": "held",
        "english": "Held / Active",
        "chinese": "已認領／進行中",
        "definition": "worktree 登記簿已經把票交給一個 active worktree。",
        "rule": "認領真相在 worktree registry；不是 backlog status。",
    },
    {
        "id": "needs-grooming",
        "english": "Needs grooming",
        "chinese": "待梳理",
        "definition": "還缺可執行的修法規格，不能直接派給 worker。",
        "rule": "canonical source 是 `list --ungroomed`；互斥 board partition 由 held 優先，因此持有中的 investigation 可顯示為 held，但仍保留在 canonical ungroomed source。",
    },
    {
        "id": "dependency-blocked",
        "english": "Dependency-blocked",
        "chinese": "依賴阻塞",
        "definition": "票本身可能已梳理，但仍有未解的 `blocked_by` 依賴。",
        "rule": "先處理 waiting-on tickets；不能用 claim 繞過。",
    },
    {
        "id": "contract-not-ready",
        "english": "Contract-not-ready",
        "chinese": "契約未就緒",
        "definition": "已有修法方向，但 preflight 證明不足或基線不是 red。",
        "rule": "不是待梳理，也不是依賴阻塞；修 contract evidence／baseline。",
    },
    {
        "id": "scope",
        "english": "Scope",
        "chinese": "檔案範圍",
        "definition": "這張 ticket 預期會觸碰的 repository 檔案清單。",
        "rule": "`scope.files[]` 每項標 `add` 或 `modify`；不從 fix_site、散文或 git diff 猜。",
    },
    {
        "id": "scope-unknown",
        "english": "Scope unknown",
        "chinese": "Scope 未知",
        "definition": "ticket 沒有可機器讀的實際檔案範圍。",
        "rule": "這會阻止可靠的 collision 判定，但本身不是 queue status。",
    },
    {
        "id": "collision",
        "english": "Collision",
        "chinese": "檔案碰撞",
        "definition": "queued ticket 的已知 Scope 與 active worktree 的已知 Scope 重疊。",
        "rule": "只在 queued 對 active 判定；Scope 未知不等於 collision。",
    },
    {
        "id": "fixed",
        "english": "Fixed",
        "chinese": "已修復",
        "definition": "票面寫下的 acceptance criterion 已在當下驗證為綠。",
        "rule": "必須有可追溯的 verification 與 fixed_by；不是 commit 存在就算。",
    },
    {
        "id": "wont-fix",
        "english": "Wont-fix",
        "chinese": "不修",
        "definition": "明確決定不修，並留下理由。",
        "rule": "它是終態，不代表問題不存在。",
    },
    {
        "id": "sot",
        "english": "Source of Truth",
        "chinese": "唯一真相來源／SoT",
        "definition": "回答某一類問題時唯一有權威的資料面。",
        "rule": "票看 backlog/lifecycle；認領看 worktree registry；看板只做唯讀 projection。",
    },
    {
        "id": "projection",
        "english": "Projection",
        "chinese": "投影",
        "definition": "把多個 SoT 的當下資料整理成適合人閱讀的畫面。",
        "rule": "看板不回寫票面、不取代 CLI，也不自創另一個 dispatch predicate。",
    },
)

MODEL_FLOW = {
    "main_path": (
        {"id": "observed", "english": "Observed", "chinese": "發現問題"},
        {"id": "ticket", "english": "Ticket", "chinese": "建立票"},
        {"id": "groomed", "english": "Groomed", "chinese": "完成梳理"},
        {"id": "queued", "english": "Queued", "chinese": "入列等待"},
        {"id": "contract", "english": "Contract preflight", "chinese": "契約預檢"},
        {"id": "dispatchable", "english": "Dispatchable", "chinese": "可派工"},
        {"id": "active", "english": "Claimed / Active", "chinese": "認領／進行中"},
        {"id": "handoff", "english": "Commit + hand-back", "chinese": "提交並交回"},
        {"id": "verify", "english": "Verify acceptance", "chinese": "驗收"},
        {"id": "resolved", "english": "Fixed / Wont-fix", "chinese": "已修復／不修"},
    ),
    "branches": (
        {
            "id": "needs-grooming",
            "label": "待梳理",
            "when": "沒有 plan／acceptance／fix_site 的可執行規格",
            "returns_to": "groomed",
        },
        {
            "id": "contract-not-ready",
            "label": "契約未就緒",
            "when": "preflight evidence 缺失、失敗，或 baseline 不是 red",
            "returns_to": "contract",
        },
        {
            "id": "dependency-blocked",
            "label": "依賴阻塞",
            "when": "blocked_by 仍指向未解票",
            "returns_to": "queued",
        },
        {
            "id": "scope-unknown",
            "label": "Scope 未知（橫向旗標）",
            "when": "沒有結構化 scope.files[]",
            "returns_to": "scope 補齊；不改 queue status",
        },
    ),
}


def classify_decision(
    entry: dict,
    *,
    held_ids: set[str],
    dispatch_ids: set[str],
    blocked_ids: set[str],
    ungroomed_ids: set[str],
    contract_not_ready_ids: set[str] | None = None,
) -> str:
    """Classify one unresolved row into one canonical, mutually exclusive bucket.

    The CLI owns contract preflight. The board consumes its explicit withheld IDs
    when available and only uses the non-dispatch remainder as a fail-closed
    compatibility fallback; it never recreates the preflight predicate here.
    """
    ticket_id = str(entry.get("id") or "")
    if ticket_id in held_ids:
        return "held"
    if ticket_id in blocked_ids:
        return "dependency-blocked"
    if ticket_id in ungroomed_ids:
        return "needs-grooming"
    if ticket_id in dispatch_ids:
        return "dispatchable"
    if contract_not_ready_ids is None or ticket_id in contract_not_ready_ids:
        return "contract-not-ready"
    raise ValueError(f"canonical decision partition missing ticket: {ticket_id}")


def scope_kind(value) -> str:
    if scope_status(value) == "known":
        return "structured"
    if isinstance(value, str) and value.strip():
        return "legacy_text"
    return "missing"


def scope_audit(entries: Iterable[dict]) -> dict[str, int]:
    rows = list(entries)
    unresolved = [row for row in rows if row.get("status") not in RESOLVED_STATUSES]
    all_counts = Counter(scope_kind(row.get("scope")) for row in rows)
    open_counts = Counter(scope_kind(row.get("scope")) for row in unresolved)
    return {
        "total": len(rows),
        "unresolved": len(unresolved),
        "structured": all_counts["structured"],
        "legacy_text": all_counts["legacy_text"],
        "missing": all_counts["missing"],
        "unresolved_structured": open_counts["structured"],
        "unresolved_legacy_text": open_counts["legacy_text"],
        "unresolved_missing": open_counts["missing"],
    }
