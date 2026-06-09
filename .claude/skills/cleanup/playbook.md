# Cleanup Playbook

這份文件服務兩個命名入口：

1. `cleanup`
2. `promote`

---

## `cleanup` — Blacklist-Driven Convergence

### Step 0 — 盤 live state

```bash
git fetch --all --prune
git status
git stash list
git branch -vv
git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
```

對每條 branch / worktree 進一步看：

```bash
git log --oneline --left-right --cherry-pick origin/main...<branch>
git diff --stat origin/main..<branch>
```

目的是先回答兩件事：

- 哪些是黑名單
- 哪些是非黑名單白名單

### Step 0.5 — 為活分支建立本輪 snapshot

若某條 branch / worktree 還在持續修改，不要直接把當下狀態當成收斂對象。

每輪先記錄：

- branch
- worktree
- current head
- dirty or clean
- 本輪 snapshot commit
- last promoted commit
- last rebased base

這輪只處理這個 snapshot。  
之後新長出的 commit 或 dirty work，不回頭追，留給下一輪。

### Step 1 — 保存所有工作

#### 1.1 預設：先 commit

```bash
git add <files...>
git commit -m "<prefix>: <message>"
```

活 branch 的 dirty work 也一樣。

- 不直接拿 dirty worktree 做 rebase
- 不直接拿 dirty worktree 做 promote
- 先 commit，讓 work identity 與 snapshot 都落地

#### 1.2 黑名單工作掛在 `main`

```bash
git branch <blacklist-branch> main
git worktree add <path> <blacklist-branch>   # 若要繼續工作
```

然後回報：

- old location
- new branch
- new worktree
- preserved commits

只有完成這一步，才允許同步 `main`。

### Step 2 — 收白名單進 `main`

白名單來源可能是：

- ready PR
- local-only branch
- main 上的非黑名單 local commits

常見方式：

```bash
gh pr ready <N>               # 若仍是 draft
gh pr merge <N> --squash --delete-branch
```

或在隔離 worktree：

```bash
git cherry-pick <commit...>
git merge --squash <branch>
```

如果白名單 branch 仍在持續長：

- 只收它本輪 snapshot 之前、已明確成熟的前綴
- 不追逐這輪之後新長出的 commit
- 必要時改走 `Workflow 2`

若主 checkout 的 `main` 需要對齊 remote，再做：

```bash
git reset --hard origin/main
```

但前提是所有黑名單工作都已先抽離。

### Step 3 — push / sync remote

目標不是只有本地 `main` 收斂，而是 remote 也同步。

```bash
git push origin main
git fetch --prune
```

### Step 4 — rebase 黑名單

對每條 surviving blacklist：

```bash
git -C <worktree> rebase origin/main
```

若該黑名單是活 branch：

- 只 rebase 到它本輪 snapshot
- 本輪 rebase 完後又新增的 commit，不算這輪範圍
- 若 promote 過它的一部分前綴，看到 `skipped previously applied commit` 通常是正確結果

若有 remote / PR：

```bash
git -C <worktree> push --force-with-lease
```

### Step 5 — 清掉白名單殘影

對已吸收進 `main` 的白名單 branch/worktree：

```bash
git worktree remove <path>
git branch -D <branch>
git push origin --delete <branch>   # remote 殘影時
git worktree prune
git fetch --prune
```

### Step 6 — 收尾狀態

完成時應該看到：

- `main` 是當前 shared baseline
- 黑名單全部站在最新 `main` 上
- `branch_audit` 只剩黑名單 PR
- 白名單殘影清乾淨

---

## `promote` — Promote Active Branch

### 使用時機

當某條 branch：

- 仍在持續修改
- 但其中有一部分**已提交**內容你想先收入 `main`
- 且你不想打斷該 branch 的活工作

### Step 0 — 確認只 promote 已提交內容

```bash
git log --reverse --oneline main..<branch>
git -C <branch-worktree> status --short --branch
```

dirty work 不是這輪 promote 的對象。  
它可以留在活 branch 上，後續再保存。

若 dirty work 其實也想納入本輪：

- 先在原 branch commit
- 把這個 commit 視為新的 snapshot 邊界
- 再從這個 snapshot 判斷哪些 commits 要 promote

### Step 1 — 建 integration worktree

```bash
git worktree add -b <integration-branch> <path> main
```

### Step 2 — 投影指定 commits

```bash
git -C <path> cherry-pick <commit...>
```

這裡的重點是：

- promote commits
- 不動活 branch 本體

### Step 3 — 推進 `main`

```bash
git -C <path> push origin HEAD:main
git fetch origin
git reset --hard origin/main
```

### Step 4 — rebase 其他黑名單

```bash
git -C <other-blacklist-worktree> rebase origin/main
git -C <other-blacklist-worktree> push --force-with-lease
```

### Step 5 — 最後再看原 branch 本體

如果你現在要讓原 branch 跟上 `main`：

```bash
git -C <active-branch-worktree> rebase main
```

若那些 commits 已經投影進 `main`，你通常會看到：

- `skipped previously applied commit ...`

這通常代表：

- 這些 commits 已被主線吸收
- branch 只剩未吸收增量

若 branch 在你 promote 期間又有人繼續提交：

- 不把這些新 commit 拉進本輪 promote
- 只把 branch rebase 到新 `main`
- 讓這些新 commit 自動成為下一輪輸入

### Step 6 — 只刪 integration 容器

```bash
git worktree remove <path>
git branch -D <integration-branch>
```

這一步只處理 promote 過程中臨時建立的 integration branch / worktree。

- 不刪原 branch
- 不刪原 worktree
- 除非使用者明確要求，promote 完不做 cleanup-style 容器回收

---

## Working Heuristics

### 什麼時候選 `cleanup`

- 你已經知道黑名單是誰
- 目標是把其餘全部收斂
- 這是預設模式

### 什麼時候選 `promote`

- 活 branch 仍在修改
- 但其中一些已提交成果已值得成為 shared baseline

### 什麼時候不要直接動 branch 本體

- worktree 有活修改
- 該 branch 是另一個 agent 的主戰場
- 你只想 promote 其中一部分 commits

### 持續維護時怎麼想

- 你維護的是「已收斂前綴 + 剩餘增量」
- 不是「把一條一直在動的 branch 一次追到乾淨」
- 每輪只要讓：
  - `main` 吃進成熟前綴
  - 黑名單站回最新 `main`
  - 新增量保留到下一輪

這輪就算成功
