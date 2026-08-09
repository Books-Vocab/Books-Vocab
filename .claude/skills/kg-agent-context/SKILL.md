---
name: kg-agent-context
description: "KG 角色感知的 progressive disclosure 與未知問題 authority escalation。當 session 是 Ticket Factory、Delivery Team Integrator、Delivery Child、review service，或不知道該讀哪份 context 時觸發。"
user-invocable: true
version: 1.0.0
---

# KG Agent Context

這是薄路由，不是第二份業務手冊。角色視野與 authority mapping 的唯一 SoT 是
`docs/reference/agent_context.md`；本 skill 只執行載入順序。

## Bootstrap

1. 判定自己是 `Ticket Factory`、`Delivery Team Integrator`、`Delivery Child` 或 `Review service`。
2. 讀 `docs/reference/agent_context.md` 對應 role row；該索引是 role context 與 authority lookup 的 SoT。
3. 保留根 `CLAUDE.md` 的 global kernel；只載入 role row 的 minimum context 與 assigned ticket。
4. 遇到未知，依 index 的 `unknown → first authority → next authority` 查找；不要先載入兄弟角色或全 repo。
5. 仍無法判定時，依 index 的 `Unknown escalation contract` 交給具名 owner；交回前不宣稱已解決。

各角色的工作動詞與停止點由 role row 指向的既有 authority 負責：Ticket Factory 看 backlog
lifecycle，Delivery Team Integrator 看 `worktree-flow`，Delivery Child 看 child hand-back，Review
service 看 `review_discipline`。本 skill 只負責載入順序，不重新定義那些契約。

## Loading discipline

`worktree-flow`、`kg-receipt`、`docs/sop/review_discipline.md`、`policy.safety` 各自仍是 authority；
本 skill 不複製它們的規則。只在角色 row 或未知索引要求時讀取，並在 receipt 列出實際 authority 與未讀
的深層文件。這使「知道得少」成為可追蹤的邊界，而不是隱性遺漏。
