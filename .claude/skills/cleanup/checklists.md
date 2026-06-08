# Cleanup Checklists

---

## Before Any Round

- 已先列出黑名單清單
- 已跑 `git fetch --all --prune`
- 已看 `git status` / `stash list` / `branch -vv` / `worktree list`
- 已看 `gh pr list` / `branch_audit`
- 已確認這輪是：
  - `Blacklist-Driven Convergence`
  - 或 `Promote Active Branch`

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
- 是否已改用 integration worktree？
- 是否明確承諾「不碰 branch 本體」？

---

## Before Rebasing Blacklist

- branch / worktree 是否乾淨？
- 若不乾淨，是否已先 commit？
- `main` 是否已是最新 shared baseline？
- 若有 remote / PR，是否準備好 `push --force-with-lease`？

---

## Before Final Report

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
