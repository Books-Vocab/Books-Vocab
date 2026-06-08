# Cleanup Casebook

這份文件記錄**實戰案例與決策模式**。  
原則是：看到相似症狀時，可以直接比對這裡的案例，不必再從頭推理一次。

---

## Case 1 — Blacklist Work Hung on `main`

### 症狀

- 某 agent 直接在 `main` 上 commit
- 但 cleanup 需要讓 `main` 回到 `origin/main`
- agent 之後抱怨自己的工作「消失了」

### 正確做法

1. 從 `main` 抽出顯式 branch
2. 必要時建立對應 worktree
3. 回報 mapping
4. 再 reset / rebase `main`

### 不要做什麼

- 先 reset `main`
- 事後才說 commit 還在 reflog

### 為什麼

reflog 只保存內容，不保存 work identity。  
對 agent 來說，沒有 branch/worktree 落點就等於工作被清掉。

---

## Case 2 — Promote Committed Subset from Active Branch

### 症狀

- `catalog/scope-campaign` 還在持續修改
- 你想先把其中已成熟的 5 個 commits 拉進 `main`
- 不想打斷活 branch 本體

### 正確做法

1. 建 integration worktree
2. 從 `main` 出發 `cherry-pick` 目標 commits
3. 推進 `main`
4. 其他 blacklist rebase 到新 `main`
5. 活 branch 本體保持不動

### 結果

- `main` 吸收成熟成果
- 活 branch 保持工作節奏
- 之後那條 branch rebase 時，被投影進 `main` 的 commits 會被 skip

### 意義

把成熟內容升格成 shared baseline，但不擾動正在修改的 branch。

---

## Case 3 — Projected Then Rebase

### 症狀

- 某條 branch 的 commits 先被 promote / cherry-pick 進 `main`
- 之後你又對那條 branch 做 `rebase main`

### 會看到什麼

- `warning: skipped previously applied commit ...`

### 正確解讀

這通常代表：

- 這些 commits 的語意已經在 `main`
- branch 現在只剩沒被吸收的增量

不是資料丟失。

---

## Case 4 — Draft PR Blocks Merge

### 症狀

- `gh pr merge` 回 `Pull Request is still a draft`

### 正確做法

```bash
gh pr ready <N>
gh pr merge <N> --squash --delete-branch
```

### 重點

這不是 code conflict，而是 GitHub workflow state。

---

## Case 5 — Merged PR but Local/Remote Branch Still Alive

### 症狀

- PR 已 merge
- `branch_audit` 還看到 `merged-pr-but-ahead`

### 正確做法

先確認 branch 內容是否已在 `main`，再刪：

```bash
git push origin --delete <branch>
git branch -D <branch>
git fetch --prune
```

### 為什麼

cleanup 的終態不是「PR merged」，而是「殘影也清掉」。

---

## Case 6 — Background Verification Blocks Worktree Cleanup

### 症狀

- `ios_test.sh --all-targets` 還在跑
- 但策略已切成「先收斂再驗證」
- worktree remove 被卡住

### 正確做法

```bash
ps -Ao pid,ppid,command | rg 'final-cleanup|ios_test.sh|ios_ops.sh build|xcodebuild'
kill <pid...>
kill -9 <pid...>   # 只在正常 kill 無效時
```

### 重點

長時背景驗證不是 sacred；當策略改變時，應主動取消，不要讓它持有第二真相。

