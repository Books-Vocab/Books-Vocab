# Cleanup Checklists

這份文件給**真正動手前的最後 30 秒核對**。

---

## Before Any Cleanup

- `git fetch --all --prune` 已跑
- `git status` / `stash list` / `branch -vv` / `worktree list` 已看
- `gh pr list` / `branch_audit` / `docs_lint --audit` 已看
- 已明確列出：
  - 吸收進 `main` 的 scope
  - 黑名單 scope
  - 驗證策略：`verify-first` / `execution-first`

---

## Before Resetting `main`

- `main` 上是否有黑名單工作？
- 若有，是否已抽出顯式 branch？
- 若有活 agent，是否已補對應 worktree？
- 是否已回報 mapping：
  - old location
  - new branch
  - new worktree
  - preserved commits

**只要以上任一沒有，不能 reset `main`。**

---

## Before Promoting Commits from an Active Branch

- 那條 branch 是否仍在持續修改？
- 你要 promote 的是否都是**已提交** commits？
- 是否改用 integration worktree，而不是直接 merge / rebase branch 本體？
- promote 後是否已規劃其他 blacklist 的 rebase 順序？

---

## Before Rebasing Blacklist

- branch / worktree 是否乾淨？
- 若有 dirty work，是否已先 commit？
- 該 branch 是否已有部分 commits 被投影進 `main`？
- 若有 remote / PR，是否準備好 `push --force-with-lease`？

---

## Before Deleting Any Branch / Worktree

- 內容是否已進 `main`，或被明確保存在其他 branch/worktree？
- 這是一次性 integration/final worktree，還是活 branch 本體？
- 是否有背景測試 / xcodebuild / generator 還在持有它？

---

## Before Final Report

- 已收斂進 `main` 的內容列清楚
- surviving blacklist 列清楚
- preserved work mapping 列清楚
- 已跑與後置的驗證分開寫
- `git status` / `worktree list` / `branch_audit` 結果已更新到當下

---

## Report Template

```text
## Cleanup 完成
scope: <mode + 白/黑名單>

### 收斂到 main
- <branch/commit/PR> → main

### blacklisted work preserved
- old location: <main|branch|worktree>
- new branch: <branch>
- new worktree: <path>
- preserved commits: <sha...>

### surviving blacklist
- <branch>：rebase 到 <base-sha>，<push status>

### 驗證
- strategy: verify-first / execution-first
- 已跑：<commands>
- 後置：<commands or known failures>

### 最終狀態
- git status: <clean|dirty>
- worktrees: <list>
- branch_audit: <summary>
```
