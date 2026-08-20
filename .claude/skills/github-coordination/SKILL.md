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

- IM 負責 Issue 收件、排序、拆解、acceptance、派工與 local worktree lifecycle；接收 Worker／Issue Solver 的 exact local hand-back，push commit、建立／更新 PR 並交付 Ready candidate。IM 不修改 code。
- CM 負責 live main、PR 優先順序、Ready admission、required checks、CR／DS 結果、merge queue／merge，以及 landing 後 local `main == origin/main`。CM 不修改 code、caller worktree、PR body 或 registry。
- GitHub 外部狀態是唯一真相；本地 coordinator 只管理 worktree ownership／Scope，不保存 Issue／Project／PR lifecycle。
- route 不是 merge 或 production 授權；缺少 PR、fresh checks、review 或批准時 fail closed。
