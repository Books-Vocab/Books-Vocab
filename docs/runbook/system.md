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
verified_against: 2a7930c04f661c266ce05b3568f375e1db2a39f1
-->
# KG Change Runbook

角色、入口與 PR 收斂規則以 [`docs/reference/delivery_model.md`](../reference/delivery_model.md) 為準。本 runbook 只描述執行順序與本機邊界。

## Entry paths

### Direct assignment → Worker

適用於 User 或 IM 已經給出明確目標、範圍與驗收的工作；不需要先建立 Issue。

1. Worker 確認 assignment、branch、worktree 與 structured Scope。
2. 在 branch/worktree 以 TDD 實作與測試，commit 保持小而可 review。
3. 開 PR，具名寫出 assignment、範圍、驗收、測試、文件影響與安全風險。

### GitHub Issue → Issue Solver

適用於需要排序、Project／milestone、討論、拆解或長期追蹤的工作。

1. IM 在 GitHub Issue 寫清楚背景、影響、acceptance、非目標與必要 domain context。
2. IM 依 GitHub Project／triage 決定優先順序，Issue Solver claim 後確認 branch、worktree 與 structured Scope。
3. Issue Solver 依 Issue 實作與測試，commit 保持小而可 review，開 PR 並關聯 Issue。

## Common PR convergence

1. Worker 與 Issue Solver 都把所有 code change 收進同一個 PR 流程：`branch → commit → PR`。
2. PR 描述變更、測試命令與 exit status、風險、文件影響、rollback 方式，並標明 direct assignment 或關聯 Issue。
3. 等 GitHub Actions workflow `pr-gate` 的 check run `required`、CR review、DS 文件判斷與必要的 environment approval 滿足後，由 CM 依優先順序 merge。`required` 的上游 job 各有 3 分鐘 hard stop，聚合本身 1 分鐘；backend／ops／iOS 的完整**受影響** `confidence` suite 依 fail-closed changed-path policy 同時平行收斂，不形成所有 PR 的全域串行門檻。
4. merge 後 `main` 是產品真相；依 release 意圖執行版本發布。發布與 production deploy 不因一般 merge 自動發生。

workflow `pr-gate` 的 check run `confidence` 失敗、非預期 skip、取消或缺失必須保留為真實偏離並追蹤 fix-forward／rollback；它不會被 `required` 覆蓋，也不能被重新描述成 PASS。只有 CM 已確認 exact `main` 對相同受影響 surface 啟動等價驗證時，才可取消已被取代的 PR run；完整結論仍等主線 terminal result。合併速度與完整驗證是兩個不同的控制面。

## Local worktree boundary

`ops/worktree_registry.py` 是本機 ownership ledger：記錄 branch、path、thread、external IDs、Scope、hand-back 與 evidence。`ops/worktree_orchestrate.py` 是本機 coordinator：建立／接管工作樹、檢查 overlap、執行必要 gate、保存 log、交回或移除工作樹。

GitHub Issue、Project、PR、CR／DS review、merge 與 release approval 不在本機 ledger 再存一份，也沒有本地 backlog、merge queue 或批次整合狀態。當本機與 GitHub 顯示不同，以 GitHub ref、PR 與 Actions 為準；local evidence 只能說明本機曾經驗證過什麼。

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
