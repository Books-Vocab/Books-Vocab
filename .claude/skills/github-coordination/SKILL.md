---
name: github-coordination
description: "CM／IM 的 GitHub-native 協調 workflow：管理 Issue、Project、PR 收斂與 merge 前條件，不接管實作 worktree。"
---

# GitHub coordination workflow

你是 CM 或 IM 的協調角色。先完成共同 onboarding，再只在 GitHub 控制面處理規劃、排序、派工、PR 收斂或 merge 前檢查。

## 啟動順序

```bash
./ops/agent_onboard.py --identity '<CM|IM>' --intent '<delivery|release>' --entry '<coordination|merge|issue-planning|direct-assignment>' --evidence '<JSON object with the entry-specific external evidence>' --json
```

依輸出讀 project overview、canonical identity boundary、GitHub Issue／Project／PR 與 required checks。不要因協調任務而建立本地 backlog、Issue mirror、merge queue 或替 Worker 修改 caller worktree。

## Boundary

- IM 負責 Issue 收件、排序、拆解、acceptance、派工與 local worktree lifecycle。它以 PI 職能事件式消費 exact local hand-back，立即 push、建立／更新唯一 PR、readback 並釋放 local assets；publication 不等於 Ready。metadata／required repair 與 confidence outcome routing 仍由 PI 處理，但不得修改 code。
- CM 負責 live main、PR 優先順序、Ready admission、required checks、CR／DS 結果、merge queue／merge，以及 landing 後 local `main == origin/main`。CM 不修改 code、caller worktree、PR body 或 registry。
- GitHub 外部狀態是唯一真相；本地 coordinator 只管理 worktree ownership／Scope，不保存 Issue／Project／PR lifecycle。
- route 不是 merge 或 production 授權；缺少 PR、fresh checks、review 或批准時 fail closed。

## Delivery control commands

- PI：`delivery.py publish`／`release-published`／`repair-pr-metadata`／`trigger-required`／`abandon-pr`；code failure 用 `worktree_orchestrate.py resume-published` 交還同一 owner，stale merge-front 用 `reanchor`。`abandon-pr` 只處理 exact closed/registry/remote lifecycle proof，不可當 dirty 或 unknown worktree 的清除捷徑。不得建立 duplicate PR、接管 owner 或 force-push未知 remote state。
- CM：`delivery.py queue`／`sync-main`；merged receipt 交 PI 執行 `cleanup-merged`。只等待 required 與 explicit hold，routine confidence／CR／DS 不形成隱性 gate。
- P0／P1／security 必須先以 typed body／durable label 呈現；clearance 只能明確 `reconcile-holds`，不能被 reanchor、metadata repair 或新 hand-back 洗掉。
