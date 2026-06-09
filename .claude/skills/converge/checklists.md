# Converge Checklists

---

## Before Any Round

- 已選 mode：`cleanup` 或 `promote`
- 已跑 `git fetch --all --prune`
- 已看 `git status` / `stash list` / `branch -vv` / `worktree list`
- 已看 `gh pr list` / `branch_audit`
- 已標出本輪會被觸及的 branch / worktree
- 已定義 `T0`
- 已為所有 hot branch 建立 snapshot 邊界

## Before Offline Integration

- 已分清 absorbed vs survivor
- 若有黑名單工作掛在 `main`，已先抽 branch/worktree
- 若是 `promote`，已明確列出本輪只 promote 哪些已提交 commits
- 已承諾 `T0` 之後的新 dirty / new commit 不進本輪

## Before Cutover

- integration/final worktree 已完成驗證
- docs gate 已完成
- cutover 步驟已排成單一序列
- 不需要再回頭盤 live branch 狀態

## During Cutover

- 先 push `main`
- 再 fetch/prune
- 再 rebase survivors
- 再 push survivors remote
- 最後才清容器 / 白名單殘影

## Before Final Report

- T0 snapshot 清單已列清楚
- 吸收進 `main` 的內容已列清楚
- surviving branch 的新 base 已列清楚
- next-round delta 已明確標示
- `git status` / `worktree list` / `branch_audit` 是最新結果
