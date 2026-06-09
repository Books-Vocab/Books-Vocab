# Cleanup Checklists

---

## Before Any Round

- 已先列出黑名單清單
- 已跑 `git fetch --all --prune`
- 已看 `git status` / `stash list` / `branch -vv` / `worktree list`
- 已看 `gh pr list` / `branch_audit`
- 已確認哪些 branch 是活分支、哪些只是靜態殘影
- 已決定這輪每條活分支的 snapshot 邊界
- 已確認這輪入口是：
  - `cleanup`
  - 或 `promote`

---

## Before Syncing `main`

- `main` 上是否有黑名單工作？
- 若有，是否已抽 branch/worktree？
- 是否已回報 preserved mapping？
- 白名單與黑名單是否已分清楚？

只要以上任一沒有，不能 reset / sync `main`。

---

## Before Promoting Commits from Active Branch

- branch 本體是不是還在活躍修改？
- 你要 promote 的是否都是已提交 commits？
- 若 branch 有 dirty work，是否已先 commit 成 snapshot？
- 是否已改用 integration worktree？
- 是否明確承諾「不碰 branch 本體」？
- 是否明確承諾「只清 integration 容器，不清原 branch / worktree」？

---

## Before Rebasing Blacklist

- branch / worktree 是否乾淨？
- 若不乾淨，是否已先 commit？
- `main` 是否已是最新 shared baseline？
- 若有 remote / PR，是否準備好 `push --force-with-lease`？
- 是否已明確知道這輪 rebase 到哪個 snapshot 為止？

---

## Before Final Report

- 每條活分支的 snapshot commit 已列清楚
- 已收進 `main` 的白名單內容列清楚
- 黑名單與其新 base 列清楚
- preserved work mapping 列清楚
- remote 同步狀態列清楚
- `git status` / `worktree list` / `branch_audit` 是當下最新結果

---

## Report Template

```text
## Convergence Round Complete
blacklist:
- <branch/PR/worktree>

### snapshots
- <branch> @ <snapshot-sha>

### absorbed into main
- <branch/commit/PR> → main

### blacklisted work preserved
- old location: <main|branch|worktree>
- new branch: <branch>
- new worktree: <path>
- preserved commits: <sha...>

### blacklist rebased
- <branch> → base <main-sha>, <push status>

### remote sync
- main: pushed / unchanged
- blacklist remotes: pushed / unchanged

### final state
- git status: <clean|dirty>
- worktrees: <list>
- branch_audit: <summary>
```
