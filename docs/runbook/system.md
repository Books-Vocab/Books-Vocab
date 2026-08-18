<!-- doc-meta
tier: runbook
authority: derived
update_trigger: workflow-change
scope:
  - .github/
  - ops/worktree_registry.py
  - ops/worktree_orchestrate.py
  - ops/devops_kg_safe.sh
  - ops/release.sh
verified_against: 202119f69a4be584f6bacf80b11a12a7bb8579c5
-->
# KG Change Runbook

## Standard path

1. 在 GitHub Issue 寫清楚背景、影響面、acceptance、非目標與必要的 domain context。
2. 以 Issue 建立 branch；若要並行修改，使用 local worktree 並先登記 structured Scope。
3. 依 Issue 實作與測試，commit 保持小而可 review。
4. 開 PR，描述變更、測試命令、風險、文件影響與 rollback 方式。
5. 等 GitHub Actions required checks、review、必要的 environment approval 都完成後 merge。
6. merge 後依 release 意圖執行版本發布；發布與 production deploy 不因一般 merge 自動發生。

## Local worktree boundary

`ops/worktree_registry.py` 是本機 ownership ledger：記錄 branch、path、thread、external IDs、Scope、hand-back 與 evidence。`ops/worktree_orchestrate.py` 是本機 coordinator：建立／接管工作樹、執行必要 gate、保存 log、交回或移除工作樹。

GitHub Issue、Project、PR、review、merge 與 release approval 不在本機 ledger 再存一份。當本機與 GitHub 顯示不同，以 GitHub ref、PR 與 Actions 為準；local evidence 只能說明本機曾經驗證過什麼。

## 變更前檢查

- `git status --short`、branch、HEAD、remote tracking ref。
- active worktree 是否已占用相同 Scope。
- `./ops/capability_matrix.py --json` 是否允許要做的動作。
- 受影響的 SoT 文件與 `./ops/docs_impact.py --files ...`。
- production／不可逆步驟是否有明確批准；沒有就停在 dry-run。

## 變更後檢查

- 只宣稱有當下輸出的驗證；不要以 clean tree 或舊 receipt 代替。
- code、ops 或 CI 變更跑相應的最小測試；`.github/` 變更跑 YAML／shell／entrypoint 檢查。
- 文件變更跑 `./ops/docs_lint.sh`；registry 變更跑 `./ops/docs_lint.sh --registry`。
- PR 內列出 exact command、exit status、風險與未解項。

## Production boundary

API、host、資料庫、CloudKit、App Store、TestFlight 與 rollback 依各自 SOP；所有生產寫入都經 `ops/devops_kg_safe.sh`、`ops/release.sh` 或被明確列出的領域入口。GitHub merge 不是 production approval。
