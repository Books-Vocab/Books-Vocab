# Cleanup Playbook

這份文件只服務兩種工作流：

1. `Blacklist-Driven Convergence`
2. `Promote Active Branch`

---

## Workflow 1 — Blacklist-Driven Convergence

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

### Step 1 — 保存所有工作

#### 1.1 預設：先 commit

```bash
git add <files...>
git commit -m "<prefix>: <message>"
```

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

## Workflow 2 — Promote Active Branch

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

### Step 6 — 刪掉 integration 容器

```bash
git worktree remove <path>
git branch -D <integration-branch>
```

---

## Working Heuristics

### 什麼時候選 Workflow 1

- 你已經知道黑名單是誰
- 目標是把其餘全部收斂
- 這是預設模式

### 什麼時候選 Workflow 2

- 活 branch 仍在修改
- 但其中一些已提交成果已值得成為 shared baseline

### 什麼時候不要直接動 branch 本體

- worktree 有活修改
- 該 branch 是另一個 agent 的主戰場
- 你只想 promote 其中一部分 commits

