<!-- doc-meta
tier: reference
authority: SoT
update_trigger: agent_context_changed
scope:
  - CLAUDE.md
  - .claude/agents/
  - .claude/skills/
  - docs/registry.yml
  - ops/context_plane.json
  - ops/context_route.py
  - ops/skill_route.py
verified_against: 202119f69a4be584f6bacf80b11a12a7bb8579c5
-->
# Agent Context Index

這份索引只回答兩個問題：目前工作應由誰負責，以及下一步應讀哪個 SoT。產品語義仍由產品文件與程式碼擁有，不在這裡重複。

## 角色

- **Manager**：決定本輪範圍、批准本機 coordinator 的高風險動作，並在 GitHub 上管理 PR／merge／release 邊界。
- **Contributor**：在一個明確 Issue、branch 與 worktree Scope 內修改產品或測試，交付 commit、驗證結果與 PR 素材。
- **Reviewer**：以 PR diff、required checks、測試證據和安全影響做獨立審查；結果留在 GitHub PR。
- **Docs steward**：只維護 registry、文件 metadata、impact 與 docs lint，不建立工作項目資料庫。
- **Release operator**：依 `docs/sop/release.md`、`docs/sop/deploy.md` 與安全 wrapper 執行批准後的發版／回滾。

角色是 context routing，不是權限系統。真正的權限來自 GitHub repository rules、branch protection、Actions environment approval、production wrapper 與帳號本身。

## 啟動順序

1. 先確認 repo、branch、HEAD、工作樹 dirty state 與 active worktree ownership。
2. 讀 GitHub Issue／PR 的目標與 acceptance，再建立或確認 structured Scope。
3. 依變更面讀 `docs/registry.yml` 的 SoT；不確定 endpoint、schema、env、deployment 或 UI 狀態時，不用記憶補空白。
4. 執行最小充分驗證；若是長操作，保留可讀 heartbeat 與完整 log。
5. 以 commit + PR 交付。PR 是討論、審查、checks 與 merge 的唯一交付紀錄。

## SoT 導航

| 問題 | 先讀 |
|---|---|
| 產品是否已存在 | `docs/reference/product_surface.md` |
| endpoint、模組、env、ops 入口 | `docs/reference/tech_index.md` |
| 文件 owner、trigger、impact | `docs/registry.yml`、`./ops/docs_impact.py` |
| worktree ownership 與 Scope | `ops/worktree_registry.py`、`ops/lib/worktree_scope.py` |
| CI／PR checks | `.github/workflows/`、`docs/sop/review_discipline.md` |
| 部署、批准、rollback | `docs/sop/deploy.md`、`docs/sop/release.md`、`docs/policy/safety.md` |
| iOS UI／Simulator | `docs/sop/ui-design.md`、對應 feature boundary、iOS verification skill |

## Scope 與證據

Scope 是檔案 ownership 與 collision 判定，不是產品需求本身。產品需求、優先序與 acceptance 在 GitHub Issue；實作意圖與驗證摘要在 PR。若 Issue、Scope、diff 或測試結果互相矛盾，停止宣稱完成並回報具體衝突。

最小 hand-back 包含：Issue／PR opaque ID（若已有）、branch、worktree path、exact HEAD、Scope、執行過的命令與 exit status、尚未解的 blocker。它是本機交接證據，不取代 GitHub PR。

## 路由輸出

context route 必須輸出可機讀的 `status`、`role`、`intent`、`skill`、`sources` 與 `next_action`。缺少 source、manifest 或必要 scope 時 fail closed；不要透過預設值假裝已經知道產品邊界。
