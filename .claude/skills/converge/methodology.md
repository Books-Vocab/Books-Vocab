# Converge Methodology

這份文件同時服務：

- `cleanup`
- `promote`

兩者不是兩套系統，只是**同一套 convergence methodology 的兩種 mode**。

---

## 核心模型

### 1. T0 Snapshot Barrier

先定一個本輪世界的切點 `T0`。

在 `T0` 當下，你要為每條會被本輪觸及的 branch / worktree 記錄：

- branch
- worktree
- current head
- dirty or clean
- snapshot commit
- 是否有 remote / PR
- 本輪角色：absorbed / survivor

如果 dirty：

```bash
git add <files...>
git commit -m "<prefix>: preserve snapshot"
```

本輪只處理到這個 snapshot。  
`T0` 之後新長出的 dirty / new commits，不回頭追，直接列為 next-round delta。

### 2. Offline Final-State Assembly

不要在活 branch 上做主流程整合。

建立單一 integration / final worktree：

```bash
git worktree add -b <integration-branch> <path> origin/main
```

在這個 worktree：

- 吸收本輪要進 `main` 的內容
- 跑驗證
- 跑 docs gate
- 確認 cutover 計畫

直到這裡，都不要回頭重新盤 hot branch 的 working tree。

### 3. Short Cutover

cutover 階段只做已經決定好的序列化操作：

1. push `main`
2. fetch / prune
3. rebase survivors 到新 `origin/main`
4. push survivors（必要時 `--force-with-lease`）
5. 清掉白名單殘影或 integration 容器

cutover 不是分析期，也不是驗證期。  
它只是把離線準備好的 final state 發布出去。

### 4. Post-Cutover Reconcile

最後回報：

- 哪些內容進了 `main`
- 哪些存活分支已跟上新 `main`
- 哪些容器被清掉
- 哪些 `T0` 之後的新變動被留到下一輪

---

## Phase 0 — Live Inventory

永遠先跑：

```bash
git fetch --all --prune
git status --short --branch
git stash list
git branch -vv
git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
```

必要時再看：

```bash
git log --oneline --left-right --cherry-pick origin/main...<branch>
git diff --stat origin/main..<branch>
```

---

## Phase 1 — Establish T0

### Cleanup Mode

先分清：

- 黑名單：本輪不吸收進 `main` 的工作
- 白名單：本輪要吸收進 `main` 的工作

所有黑名單與白名單，只要還是 hot branch，都先落成本輪 snapshot。

### Promote Mode

先分清：

- 活 branch 的本輪 snapshot commit
- 哪些**已提交 commits**要 promote
- 哪些 commits / dirty work 明確不在本輪

dirty work 若要納入：

1. 先在原 branch commit
2. 把該 commit 視為本輪 snapshot 邊界
3. promote 只處理這個邊界以內的已提交內容

---

## Phase 2 — Assemble Final State Offline

### Cleanup Mode

在 integration/final worktree：

- merge / cherry-pick / gh merge 白名單內容
- 檢查 docs impact
- 跑必要驗證

若黑名單工作掛在 `main`，先抽 branch/worktree，再進這一步。

### Promote Mode

在 integration worktree：

```bash
git cherry-pick <commit...>
```

重點：

- 只投影要 promote 的 commits
- 不動原 branch 本體
- 原 branch 的新 dirty / new commits 不納入本輪

---

## Phase 3 — Validate Before Cutover

在 integration/final worktree 完成：

- 目標測試 / lint / build
- `./ops/docs_lint.sh`
- 必要時再跑 `./ops/branch_audit.sh --json` 做 cutover 前預檢

這裡若拖長，不代表要回頭重盤 live branch。  
因為本輪真相已經固定在 `T0` snapshot。

---

## Phase 4 — Execute Short Cutover

必須**序列化**執行：

```bash
git push origin main
git fetch --all --prune
git -C <survivor-worktree> rebase origin/main
git -C <survivor-worktree> push --force-with-lease   # 若有 remote
git worktree remove <integration-path>
git branch -D <integration-branch>
```

Cleanup mode 另外清白名單殘影：

```bash
git worktree remove <white-worktree>
git branch -D <white-branch>
git push origin --delete <white-branch>
```

Promote mode 只清 integration 容器；原 branch/worktree 預設保留。

---

## Phase 5 — Post-Cutover Report

至少回報：

- mode
- T0 snapshot 清單
- `main` 吸收了什麼
- surviving branch 新 base 是哪個 commit
- remote sync 狀態
- 白名單殘影 / integration 容器是否已清除
- `T0` 之後被排除的 next-round delta

---

## 選 Mode 的準則

### 選 `cleanup`

當你要的是：

- 使用者先定黑名單
- 其餘都進 `main`
- 本輪結束後白名單殘影也應收掉

### 選 `promote`

當你要的是：

- 活 branch 還要繼續
- 你只想升格其中一部分已提交內容
- promote 完不代表 branch 生命周期結束

---

## 方法論底線

- 不在 cleanup / promote 主流程中追 moving HEAD
- 不把 cutover 當分析期
- 不把 PR merged 當 commit 已進 `main`
- 不在未保存 work identity 前 reset / sync `main`
