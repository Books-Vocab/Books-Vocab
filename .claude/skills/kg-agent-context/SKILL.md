---
name: kg-agent-context
description: "KG 五種 canonical identity 的 progressive disclosure 與未知問題 authority escalation；並提供 Docs Steward／Review service 的內部支援 route。當不知道該讀哪份 context 時觸發。"
user-invocable: true
version: 1.1.0
---

# KG Agent Context

這是薄路由，不是第二份業務手冊。角色視野與 authority mapping 的唯一 SoT 是
`docs/reference/agent_context.md`；本 skill 只執行載入順序。

## Bootstrap

1. 先從五種且僅五種 canonical identity 選一個：`manager`、`integrator`、`direct-assignment-child`、`ticket-factory-child`、`ticket-delivery-child`。不要把聊天層的主要 AI、Docs Steward 或 Review service 當成交付身份。
2. 在任何修改或任務命令前，先跑唯讀 `./ops/context_route.py identify --role <identity> [--work-mode <mode>] --json`；未取得 `status=confirmed` 前，只能讀 identity／registry／context，不能改檔、claim、open、adopt、Gate、integrate、cutover、resolve、sync 或 deploy。
3. 確認後用同一組 identity／mode 跑 `./ops/context_route.py route`，再以 `render` 只載入選中的 slices；`docs/reference/agent_context.md` 是 role context 與 authority lookup 的 SoT。
4. 保留根 `CLAUDE.md` 的 global kernel；只載入 identity row 的 minimum context 與 assigned ticket。缺 section、anchor 不唯一、registry ownership 不符、HEAD/source race 或 budget overflow 都 fail-closed，不 fallback 到全文。
5. 遇到未知，依 index 的 `unknown → first authority → next authority` 查找；不要先載入兄弟角色或全 repo。仍無法判定時，交給具名 owner，交回前不宣稱已解決。

五種 identity 的工作動詞與停止點由 `docs/reference/agent_context.md` role row 指向的 authority 負責：Manager 看
primary／current-main，Integrator 看 `worktree-flow` staging，三種 Child 看自己的 Scope 與 child hand-back（回報 exact source thread ID）。
Docs Steward／Review service 只作內部支援 route，不加入 identity gate；Child 不追蹤主幹前進、不 catchup，Integrator 只交 staging handoff 與衝突證據。
本 skill 只負責載入順序，不重新定義那些契約。

## Loading discipline

`worktree-flow`、`kg-receipt`、`docs/sop/review_discipline.md`、`policy.safety` 各自仍是 authority；
本 skill 不複製它們的規則。只在角色 row 或未知索引要求時讀取，並在 receipt 列出實際 authority 與未讀
的深層文件。Docs Steward 的一般 route 不讀 `worktree-flow`；交回時才用 `task=handback` 明示載入
child stop／handoff。這使「知道得少」成為可追蹤的邊界，而不是隱性遺漏。
