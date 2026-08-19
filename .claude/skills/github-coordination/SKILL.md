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

- IM 負責 Issue 收件、排序、拆解、acceptance 與派工；可把工作直接交給 Worker，也可交給 Issue Solver。
- CM 負責 codebase、PR 優先順序、required checks、CR／DS 結果與 merge 決定；release／deploy 仍經獨立 SOP。
- GitHub 外部狀態是唯一真相；本地 coordinator 只管理 worktree ownership／Scope，不保存 Issue／Project／PR lifecycle。
- route 不是 merge 或 production 授權；缺少 PR、fresh checks、review 或批准時 fail closed。
