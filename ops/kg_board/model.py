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
    {
        "id": "manager",
        "english": "Manager",
        "chinese": "落地主管",
        "definition": "唯一負責把 staging handoff 經 Gate 收斂到 primary 與 origin/main 的角色。",
        "rule": "只有 Manager 可執行 gated continuation、current-main admission、cutover、resolve --via-integration、sync，並裁決 Gate BLOCK；deploy 另需 release 意圖。",
    },
    {
        "id": "integrator",
        "english": "Integrator",
        "chinese": "扇出／暫存協調者",
        "definition": "依 Scope 矩陣 fan-out child，將已 hand-back 的來源組裝成 staging tree。",
        "rule": "只可 integrate --no-gate、append、保留／回報衝突證據與清理未落地 staging；不解檔案衝突、不改 primary、不重簽 child seal。",
    },
    {
        "id": "child",
        "english": "Child",
        "chinese": "局部交付者",
        "definition": "三種 Child identity（Direct-assignment、Ticket Factory、Ticket Delivery）各自在自己的 Scope 內完成局部責任。",
        "rule": "先確認其中一種 Child identity；只跑該身份允許的 S0＋受影響 S1，完成後依其停止點 typed hand-back，不追蹤 primary。",
    },
    {
        "id": "staging-handoff",
        "english": "Staging handoff",
        "chinese": "暫存交接",
        "definition": "Integrator 將多個 child hand-back 組成可供 Manager 驗證的整合樹。",
        "rule": "state 必須保留 source hand-back SHA、phase 與 next_action=manager-gate；它不是 primary landed，也不是 child receipt。",
    },
    {
        "id": "verification-tiers",
        "english": "S0–S4",
        "chinese": "分層驗證",
        "definition": "依變更範圍與發布風險逐級增加成本的驗證模型。",
        "rule": "Child=S0＋受影響 S1；Manager 整合=S0＋受影響 S2；跨模組才升 S3；真正發布才做 S4。",
    },
    {
        "id": "gate-block-routing",
        "english": "Gate BLOCK routing",
        "chinese": "Gate 阻塞分流",
        "definition": "Manager 對整合後 Gate 紅燈的歸屬判斷與修復路徑。",
        "rule": "Child slice defect 依 exact source thread 退回原 thread；整合／檔案衝突由 Manager 在 staging 修復；baseline／工具問題具名登記或 defer，不偽造 PASS。",
    },
    {
        "id": "role-identity-gate",
        "english": "Role identity gate",
        "chinese": "角色身份閘門",
        "definition": "在任何任務命令前先確認角色，且只可屬於五種 canonical identity 之一。",
        "rule": "Manager、Integrator、Direct-assignment Child、Ticket Factory Child、Ticket Delivery Child；未確認只能做唯讀 identity/context bootstrap。",
    },
)

MODEL_IDENTITIES = (
    {
        "id": "manager",
        "english": "Manager",
        "chinese": "落地主管",
        "role": "manager",
        "work_mode": "none",
        "admission": "先宣告 Manager；確認 primary／current-main／origin/main 視野與當下落地授權。",
        "boundary": "唯一負責 Gate、current-main admission、檔案衝突修復、cutover、resolve、sync。",
    },
    {
        "id": "integrator",
        "english": "Integrator",
        "chinese": "扇出／暫存協調者",
        "role": "integrator",
        "work_mode": "none",
        "admission": "先宣告 Integrator；取得 assigned batch 與 Scope／檔案佔用矩陣。",
        "boundary": "只做 fan-out、integrate／append staging 與衝突證據回報，不改 primary、不解檔案衝突。",
    },
    {
        "id": "direct-assignment-child",
        "english": "Direct-assignment Child",
        "chinese": "直接派工 Child",
        "role": "child",
        "work_mode": "direct-assignment",
        "admission": "開工前必須有 structured Scope 與 exact source thread。",
        "boundary": "只做自己的 Scope；局部驗證後 commit＋typed hand-back。",
    },
    {
        "id": "ticket-factory-child",
        "english": "Ticket Factory Child",
        "chinese": "Ticket Factory Child",
        "role": "child",
        "work_mode": "ticket-factory",
        "admission": "開工前宣告 ticket-factory mode 與 structured Scope；不 claim delivery ticket。",
        "boundary": "只把問題收斂成可派工 contract，不做產品整合或 primary 落地。",
    },
    {
        "id": "ticket-delivery-child",
        "english": "Ticket Delivery Child",
        "chinese": "Ticket Delivery Child",
        "role": "child",
        "work_mode": "ticket-delivery",
        "admission": "開工前由 dispatch／campaign ticket 提供 Scope，不另猜 direct Scope。",
        "boundary": "只完成 ticket Scope；局部驗證後以 ticket outcomes、exact HEAD、typed seal hand-back。",
    },
)

MODEL_ROLES = (
    {
        "id": "manager",
        "english": "Manager",
        "chinese": "落地主管",
        "owns": ("primary", "origin/main", "current-main admission", "integration repair", "final delivery decision"),
        "can_do": ("gated continuation", "Gate BLOCK adjudication", "close-wave --commit", "cutover --commit", "resolve --via-integration", "sync --commit"),
        "stops_at": "primary 與 origin/main 完成收斂；deploy 仍需另外的 release 意圖",
    },
    {
        "id": "integrator",
        "english": "Integrator",
        "chinese": "扇出／暫存協調者",
        "owns": ("Scope／檔案佔用矩陣", "fan-out", "staging"),
        "can_do": ("integrate --commit --no-gate", "--append", "衝突證據整理／回報", "未落地 staging tree 清理"),
        "stops_at": "把 source hand-back 與 staging manifest 交給 Manager；不改 primary main",
    },
    {
        "id": "direct-assignment-child",
        "english": "Direct-assignment Child",
        "chinese": "直接派工 Child",
        "owns": ("structured Scope", "局部實作", "局部驗證"),
        "can_do": ("S0", "受影響的 S1", "commit", "typed hand-back"),
        "stops_at": "commit + hand-back：把 exact HEAD、source thread、seal 與證據交回 Manager；不追蹤 primary、不 catchup",
    },
    {
        "id": "ticket-factory-child",
        "english": "Ticket Factory Child",
        "chinese": "票務工廠 Child",
        "owns": ("factory Scope", "backlog contract", "dispatchable definition"),
        "can_do": ("add", "verify", "groom", "contract evidence"),
        "stops_at": "contract-ready／dispatchable 或具名外部阻塞；不做產品整合、不落地 primary",
    },
    {
        "id": "ticket-delivery-child",
        "english": "Ticket Delivery Child",
        "chinese": "票務交付 Child",
        "owns": ("ticket Scope", "局部實作", "局部驗證"),
        "can_do": ("S0", "受影響的 S1", "ticket outcomes", "typed hand-back"),
        "stops_at": "ticket Scope 完成後把 exact HEAD、source thread、seal 與 outcomes 交回 Manager；不追蹤 primary、不 catchup",
    },
)

MODEL_WORK_MODES = (
    {
        "id": "direct-assignment",
        "english": "Direct assignment",
        "chinese": "直接派工",
        "admission": "開工前必須有 structured Scope；不持有 delivery ticket",
        "scope_source": "agent／使用者明示 Scope",
        "handback": "child 直接 hand-back 給 Manager",
    },
    {
        "id": "ticket-factory",
        "english": "Ticket Factory",
        "chinese": "票務工廠",
        "admission": "先產生／梳理可派工 ticket；本身不 claim delivery ticket，仍需 structured Scope",
        "scope_source": "factory 任務明示 Scope",
        "handback": "factory 結果回到派工佇列，不冒充 delivery 完成",
    },
    {
        "id": "ticket-delivery",
        "english": "Ticket delivery",
        "chinese": "票務交付",
        "admission": "由 dispatch／campaign 取得 ticket；不另宣告 direct Scope",
        "scope_source": "ticket 的 scope.files[]",
        "handback": "child 以 ticket outcomes、exact HEAD 與 typed seal 直接交回 Manager",
    },
)

MODEL_RESPONSIBILITY_FLOW = (
    {"id": "identity", "owner": "所有 agent", "label": "先確認身份", "detail": "五種 canonical identity 未確認前，只能做唯讀 identity／context bootstrap。"},
    {"id": "scope", "owner": "Integrator／Manager", "label": "定 Scope", "detail": "先看檔案佔用矩陣，決定可否 fan-out。"},
    {"id": "child", "owner": "三種 Child", "label": "局部實作", "detail": "依 direct-assignment、ticket-factory 或 ticket-delivery identity 開工；只跑 S0＋受影響 S1。"},
    {"id": "handback", "owner": "Child → Manager", "label": "Typed hand-back", "detail": "交回 exact source thread、HEAD、seal、測試與耗時。"},
    {"id": "staging", "owner": "Integrator", "label": "Fan-in staging", "detail": "可先 integrate／append；遇檔案衝突只保留證據交 Manager，保留 source provenance，不重簽 child seal。"},
    {"id": "gate", "owner": "Manager", "label": "Gate／落地", "detail": "整合後跑受影響 S2；跨模組才升 S3，必要時才做 S4 發布級驗證。"},
    {"id": "sync", "owner": "Manager", "label": "Sync／Release", "detail": "cutover、resolve、sync；deploy 另需 release 意圖。"},
)

MODEL_FLOW = {
    "main_path": (
        {"id": "role-identity", "english": "Role identity", "chinese": "先確認角色"},
        {"id": "observed", "english": "Observed", "chinese": "發現問題"},
        {"id": "ticket", "english": "Ticket", "chinese": "建立票"},
        {"id": "groomed", "english": "Groomed", "chinese": "完成梳理"},
        {"id": "queued", "english": "Queued", "chinese": "入列等待"},
        {"id": "contract", "english": "Contract preflight", "chinese": "契約預檢"},
        {"id": "dispatchable", "english": "Dispatchable", "chinese": "可派工"},
        {"id": "active", "english": "Claimed / Active", "chinese": "認領／進行中"},
        {"id": "handoff", "english": "Commit + hand-back", "chinese": "提交並交回"},
        {"id": "staging", "english": "Staging handoff", "chinese": "暫存交接"},
        {"id": "manager-gate", "english": "Manager Gate / cutover", "chinese": "Manager Gate／落地"},
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
