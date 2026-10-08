---
name: github-coordination
description: "CM／IM 的 GitHub-native 協調 workflow：管理 Issue（label 與公開認領）、PR 收斂與 merge 前條件，不接管實作 worktree。"
---

# GitHub coordination workflow

你是 CM 或 IM 的協調角色。先完成共同 onboarding，再只在 GitHub 控制面處理規劃、排序、派工、PR 收斂或 merge 前檢查。

## 啟動順序

```bash
./ops/agent_onboard.py --identity '<CM|IM>' --intent '<delivery|release>' --entry '<coordination|merge|issue-planning|direct-assignment>' --evidence '<JSON object with the entry-specific external evidence>' --json
```

依輸出讀 project overview、canonical identity boundary、GitHub Issue／PR 與 required checks。不要因協調任務而建立本地 backlog、Issue mirror、merge queue 或替 Worker 修改 caller worktree。

## Boundary

- IM 負責 Issue 收件、排序、拆解、acceptance、派工與 local worktree lifecycle。它以 PI 職能事件式消費 exact local hand-back，立即 push、建立／更新唯一 PR、readback 並釋放 local assets；publication 不等於 Ready。metadata／required repair 與 confidence outcome routing 仍由 PI 處理，但不得修改 code。
- CM 負責 live main、PR 優先順序、Ready admission、required checks、CR／DS 結果、merge queue／merge，以及 landing 後 local `main == origin/main`。CM 不修改 code、caller worktree、PR body 或 registry。
- GitHub 外部狀態是唯一真相；本地 coordinator 只管理 worktree ownership／Scope，不保存 Issue／Project／PR lifecycle。
- route 不是 merge 或 production 授權；缺少 PR、fresh checks、review 或批准時 fail closed。

## Issue states, claims and PR links

規則正本是 `docs/reference/issue_management.md`；此處只列協調時的動作。

- 每個 open Issue 恰有一個狀態 label（`needs-triage`、`needs-info`、`blocked`、`ready-for-solver`、`in-progress`、`in-review`）與一個 `P0`–`P3`。派工只取 `ready-for-solver`：先高優先級，同級依「解除阻擋者、範圍小、較舊」，跳過 Scope 與現有認領重疊者。
- 認領只由 IM 寫，且必須公開：Issue 留言帶 `kg.issue.claim.v1` 標記（`claim`／`renew`／`release`，TTL 預設 6 小時）加 `in-progress`；不使用 assignee。過期只會被標 `claim-stale`，是否釋放由 IM 決定。CM 與一般寫作者只讀認領，不代發。
- 公開看板是 label 為 `work-board` 的單一自我更新 Issue（機讀區塊 `kg.issue.board.v1`）；它是 Issue 事實的投影，兩者不一致以 Issue 與留言為準。
- 目標：PR 內文 `## Issues` 區段逐一列 `Closes #N`（完全解決，合併自動關閉）與 `Refs #N`（部分，Issue 回 `ready-for-solver`）。**但 W4（`publish --closes`／`--refs`、`pr_contract` 渲染）未落地前，`delivery.py` 發布的 PR 內文是 receipt 純函數，手加的 `## Issues` 會被 publish／repair 覆寫甚至擋下 required-repair**：不手改 canonical body，改以 `Resolved by <PR/commit>` 留言關閉並附 commit 證據；模板的 `## Issues` 只適用手寫 PR。`claim-issue`／`issue_sync` 同樣未落地，認領依協議手動留言＋label。

## Delivery control commands

- PI：`delivery.py publish`／`release-published`／`repair-pr-metadata`／`trigger-required`／`abandon-pr`；code failure 用 `worktree_orchestrate.py resume-published` 交還同一 owner，與 live main 衝突（`CONFLICTING`）的 merge-front 用 `reanchor`；只落後 main 的 mergeable PR 直接 queue。`abandon-pr` 只處理 exact closed/registry/remote lifecycle proof，不可當 dirty 或 unknown worktree 的清除捷徑。不得建立 duplicate PR、接管 owner 或 force-push未知 remote state。
- CM：`delivery.py queue`／`sync-main`；merged receipt 交 PI 執行 `cleanup-merged`。只等待 required 與 explicit hold，routine confidence／CR／DS 不形成隱性 gate。
- P0／P1／security 必須先以 typed body／durable label 呈現；clearance 只能明確 `reconcile-holds`，不能被 reanchor、metadata repair 或新 hand-back 洗掉。

## Fan-out and republish

- 每台 host 同時跑的 heavy implementer（backend／iOS build、全量 ops test）上限約 6–8；只有 host 另備 heavy test slot（例如 iOS simulator pool）才可往上加。超過時 lock contention 會讓 gate 假紅。
- 已 publish 的 PR 由原 owner 修正，不另開 PR：required code failure 走 `worktree_orchestrate.py resume-published`（same-owner generation+1、fresh hand-back，PI 只更新同一 PR）；Worker／Issue Solver 不 push。PR base 只落後 live main 而 `MERGEABLE` 時直接 queue，不 reanchor、不 republish；只有 `CONFLICTING` 才由原 owner `reanchor`。
- republish 只用於原 owner 無法繼續，且 exact PR／registry／remote proof 完整、local assets 已不存在的 lane（政策正本見 `docs/reference/delivery_model.md`，終止條件見 `docs/sop/delivery_control_dogfood.md`）：
  1. `./ops/delivery.py abandon-pr --pr <old-pr>`（關 PR、registry 標 `abandoned`、刪 remote branch；任一步缺 proof 即 fail closed）。remote branch 刪除後只剩本機物件，所以先在 abandon 前用 `git rev-parse` 記下 `<tip-sha>`；
  2. 尚未 publish 的殘留 claim 用 `./ops/worktree_orchestrate.py resolve --branch <old> --status abandoned --json`；
  3. 由派工方建立新 worktree 與 branch：`git worktree add -b <new> <new-path> <tip-sha>`（或 `worktree_orchestrate.py open`），再 `./ops/deliver.py --worktree <new-path> --scope-from-diff --check "<label>=<cmd>"`。`deliver.py` 的 preflight 一律 fetch `origin/main`，publish 前若 branch 落後就 `git rebase origin/main`，衝突則 `rebase --abort` 並 fail closed（`ops/deliver.py` 的 `preflight`／`rebase_if_behind`）；所以舊 tip 若與 live main 衝突，不能原樣 republish。須先由 owner 在 tip 上 rebase 解衝突，或在新 lane 以 `git cherry-pick` 把需要的 commit 套到 `origin/main` 後再 deliver。這條規則只適用於未 publish 的新 lane；「已 publish、落後但 `MERGEABLE`」的 PR 仍照上方規則直接 queue，不 rebase、不 republish。
- 派接續工作照 `worktree-flow` 的 continuation packet：只交 base ref（含可選的 local WIP branch tip，不交 patch 檔）與新 branch 名。

## Merge readiness

- Merge 前 CM 讀 `gh pr checks <pr>` 的 confidence fan-out 與 agent-review inline comments（`gh api repos/Books-Vocab/Books-Vocab/pulls/<pr>/comments`）；`required` 只是短 gate，綠燈不代表受影響 surface 已驗證。
- 只有 P0／P1／security 形成 hold：依上方 typed body／durable label 呈現後再 queue。非嚴重的 confidence 紅燈或 finding 不是 hold，交 BS 建獨立 follow-up；該 PR 不得宣稱「完整綠」，也不得進入受影響的 release／deploy 路徑。政策正本見 `docs/reference/delivery_model.md`「Required 與 advisory outcomes」，此處不重述。
