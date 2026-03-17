---
name: parallel-dev
description: Parallel feature development — plan creation, agent dispatch, PR review/merge, build verification, cleanup
allowed-tools: Agent, Bash, Read, Edit, Write, Glob, Grep
user-invocable: true
---

# Parallel Development Skill

多任務平行開發閉環：拆 plan → 派 agent → review/merge → build → 清理。

## 觸發方式

使用者提供需求後說「執行」或「開始」，即進入完整流程。
或在 plan 檔案已存在時直接說「按 plan 執行」。

## 完整流程

### Phase 1: Plan（需使用者確認）

1. 閱讀相關代碼，理解現狀
2. 將需求拆分為可平行執行的任務，每個任務一個 `plan/{name}.md`
3. 每個 plan 包含：
   - `Branch: worktree-{name}`
   - `Depends on:` 依賴關係
   - 具體 Tasks + Acceptance Criteria
   - Files Modified 清單
   - Commit Prefix
4. 向使用者展示 plan 摘要表格，等待確認

### Phase 2: Execute（自動）

使用 `plan-executor` 自訂 agent（定義於 `.claude/agents/plan-executor.md`）。
該 agent 已內建完整的執行流程、commit 規範、禁止事項。

對每個 plan，spawn 一個 agent：

```
Agent(
  subagent_type: "plan-executor",
  model: "opus" 或 "sonnet",  // 依任務複雜度判斷，見下表
  prompt: "執行 plan/{name}.md"
)
```

Model 選擇：

| 複雜度 | Model | 適用場景 |
|--------|-------|---------|
| 高 | opus | 架構重構、多檔案交互改動、新增手勢/動畫系統、需理解跨檔案依賴 |
| 中 | sonnet | 功能新增、UI 調整、新增元件、排序/篩選邏輯 |
| 低 | sonnet | Token 替換、標籤移除、硬編碼清理、accessibility labels 補充 |

若 plan 中明確指定 `## Model: opus/sonnet`，以 plan 指定為準。

agent 定義已設 `background: true` + `isolation: worktree`，自動在背景 worktree 中執行。
等待所有 agent 完成通知。

### Phase 3: Review & Merge（自動）

1. `gh pr list --state open` 確認所有 PR
2. 分析檔案重疊度，決定合併順序（依賴少 → 基礎設施 → 功能 → 橫切）
3. 對每個 PR 依序執行：

```bash
# a. Review
gh pr diff $PR_NUM

# b. 若需要 rebase
git worktree add .claude/worktrees/merge-$BRANCH $BRANCH
cd .claude/worktrees/merge-$BRANCH
git rebase origin/main

# c. 若有衝突 → 讀取衝突檔案，理解雙方意圖，合併兩者改動
# 原則：兩邊都保留，不丟任何一方的改動

# d. Push 後等 5 秒讓 GitHub 重算 mergeability
git push --force-with-lease
sleep 5

# e. Merge
gh pr merge $PR_NUM --merge
```

4. 每個 merge 後更新 main：`git pull origin main`

### Phase 4: Build Verification（自動）

```bash
git pull origin main
./ops/ios_build.sh
```

- Exit code 0 → 成功
- Exit code 非 0 → 讀取錯誤行上下 20 行，修復，重新 commit + push，再 build

### Phase 5: Cleanup（自動）

```bash
# 刪除殘留 local branches
git branch | grep worktree | xargs git branch -D

# 清理 worktree 記錄
git worktree prune

# 確認乾淨
git worktree list   # 應只剩主 worktree
gh pr list --state open   # 應為空
git status   # 應為 clean
```

向使用者報告最終結果：PR 數量、檔案數、行數統計。

## 關鍵原則

- **衝突解決**：兩邊都保留，不丟改動。Token cleanup 先合併可減少衝突。
- **Agent 數量**：單批不超過 7 個。若超過，分批執行。
- **合併順序**：基礎設施 → 功能 → 橫切。共用檔案碰得少的先合併。
- **SourceKit 假陽性**：iOS Xcode 專案的 swift-lsp 已停用。即使殘留 LSP 報錯，一律忽略，僅以 xcodebuild 結果為準。
- **GitHub API 延遲**：force-push 後等 5 秒再 merge，避免 "not mergeable" race condition。
