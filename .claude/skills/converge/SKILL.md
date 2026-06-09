---
name: converge
description: "Branch/worktree convergence：A=cleanup 全收斂，B=promote 單分支升格。核心=白名單進 main → 黑名單 rebase → sync remote → 清殘影。"
user-invocable: true
version: 1.0.0
---

# Converge

兩種模式，同一個目標：**讓 main 是最新 shared baseline，所有活分支都基於它。**

---

## Mode A — Cleanup（全收斂）

白名單全部進 main，黑名單保留但 rebase 到新 main，已完成分支全清。

### 步驟

```bash
# 1. 盤現狀
git fetch --all --prune
git branch -vv
git worktree list
git status

# 2. 白名單合併（逐條）
git checkout main
git merge <white-branch>      # 或 gh pr merge <pr-number> --squash / --rebase / --merge
git push origin main

# 3. 黑名單 rebase
git checkout <black-branch>
git rebase origin/main
git push --force-with-lease   # 若有 remote

# 4. 清已完成分支殘影
git push origin --delete <white-branch>    # remote
git branch -D <white-branch>               # local
git worktree remove <white-worktree>       # 若有 worktree

# 5. 驗收
git branch -vv
git worktree list
git status
```

---

## Mode B — Promote（單分支升格）

在 A 已清完的狀態下，選一條活分支，把它的 commits 拉進 main（不刪分支）。

### 步驟

```bash
# 1. 確認基線
git fetch --all --prune
git checkout main

# 2. 拉進目標分支的 commits
git merge <target-branch>     # 或 cherry-pick 指定 commits
git push origin main

# 3. 所有其他活分支 rebase
git checkout <other-branch>
git rebase origin/main
git push --force-with-lease

# 4. 目標分支保留（不刪），但可選 rebase 讓它也追上
git checkout <target-branch>
git rebase origin/main
git push --force-with-lease

# 5. 驗收
git branch -vv
git worktree list
```

---

## 輸出要求

每次 converge 結束必須報告：

1. Mode（A cleanup / B promote）
2. 進了 main 的內容（branch / commits / PR #）
3. 黑名單/其他分支的新 base（`git rev-parse origin/main`）
4. 刪了哪些 remote branch / local branch / worktree
5. 還活著的 branch 列表
6. `git status` 是否乾淨

---

## 實戰踩坑

### 1. 清殘影順序不能錯

**錯誤：**先 `git branch -D` 再 `git worktree remove` → branch 刪不掉（還綁著 worktree）

**正確：**`git worktree remove <path>` → `git branch -D <branch>` → `git push origin --delete <branch>`

### 2. 沒有 upstream 的 branch

很多 worktree branch 沒設 upstream，`git push` 會噴 fatal。

**預設命令：**`git push origin HEAD --force-with-lease`

### 3. 孤兒 worktree（.git 連結壞掉）

worktree 的 `.git` 檔案可能因外部操作消失，`git worktree remove` 會報 fatal。

**修復：**`git worktree prune --verbose` 自動清孤兒，再 `rm -rf <path>`。

### 4. 不能跨 worktree checkout branch

在 worktree A 裡面不能 `git checkout main`，因為 main 已被另一個 worktree 使用。

**修復：**一律 `cd` 到目標 worktree 的目錄再操作，或 `git -C <path>`。

### 5. remote branch 可能根本不存在

`git push origin --delete <branch>` 可能報 `remote ref does not exist`（branch 從未推過 remote）。

**修復：**remote 刪除失敗就跳過，繼續清 local + worktree。

### 6. 同一個檔案在多個 worktree 漂移

`ICloudDownloadManager.swift` 之類的熱檔案會在多個 worktree 同時被改但沒 commit，導致每輪 converge 都要 snapshot。

**修復：**無法自動化，只能靠紀律 — 改完就 commit，不要留 dirty work 過夜。

---

## 鐵律

- **先 fetch**，永遠先看 origin/main 的真實狀態
- **merge / rebase 前確認 working tree 乾淨**（`git status`）— rebase 不允許 dirty tree
- dirty 時：**立即 commit snapshot**，不 stash（stash 會丟身份資訊）
- **force-push 只用 `--force-with-lease`**，不用 `-f`
- **刪 remote branch 前先確認它存在**，不存在就跳過
- **merge 後若測試失敗，revert 或 hotfix，不讓 main 壞著**