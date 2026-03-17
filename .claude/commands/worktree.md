---
description: 在 worktree 中親自實作計劃、提交 PR、清理退出
---

# Worktree 實作流程

你必須**親自完成所有實作**，禁止調派 sub-agent（Agent tool）執行任務。

## 輸入

使用者會提供：
- 一個實作計劃（可能是文字、plan 檔案路徑、或上下文中的計劃內容）
- 可選：worktree 名稱（預設從計劃推導）

$ARGUMENTS 的格式為：`<worktree名稱>` 或留空自動推導。

## 流程

### 1. 進入 Worktree

```
EnterWorktree(branch: "worktree-<名稱>")
```

如果已在 worktree 中（git branch 含 `worktree-` 前綴），跳過此步。

### 2. 閱讀計劃

- 如果使用者提供了 plan 檔案路徑 → 讀取
- 如果計劃在對話上下文中 → 直接使用
- 理解所有要改的檔案和邏輯

### 3. 讀取 → 修改 → 驗證

對每個要修改/新建的檔案：

1. **先讀再改**：用 Read 讀取目標檔案，理解現有結構
2. **修改**：用 Edit/Write 工具直接修改
3. **不用 Agent**：所有搜尋用 Glob/Grep，所有修改自己做

### 4. 驗證

依照專案慣例跑驗證：

- Backend：`python -m pytest backend/tests/ -x -q`
- iOS：`./ops/ios_build.sh`
- 有錯就修，修完重跑

### 5. 提交 + PR

驗證通過後：

1. `git status` + `git diff --stat` 確認變更範圍
2. `git add <具體檔案>` — 不用 `-A`
3. `git commit` — commit message 遵循專案前綴慣例（`ios:` / `api:` / `ops:` / `docs:`），末尾加 `Co-Authored-By`
4. `git push -u origin <branch>`
5. `gh pr create` — 標題簡明，body 含 Summary + Test plan

### 6. 清理退出

```
ExitWorktree(action: "remove", discard_changes: true)
```

commit 已推上 remote，本地 worktree 可安全刪除。

## 硬性規則

- **禁止** Agent tool（不管 subagent_type 是什麼）
- **禁止** 跳過驗證步驟
- **禁止** `git add -A` 或 `git add .`
- 驗證失敗 → 讀錯誤 → 修正 → 重跑，最多 3 輪
- 每個步驟完成後簡短回報，不囉嗦
