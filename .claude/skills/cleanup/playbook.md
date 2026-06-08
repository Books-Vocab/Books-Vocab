# Cleanup Playbook

這份文件是 `cleanup` 的**完整操作手冊**。  
`SKILL.md` 只保留契約；真正動手時的 phase、指令與分支策略放這裡。

---

## Phase 0 — 盤點真相

```bash
git fetch --all --prune
git status
git stash list
git branch -vv
git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
./ops/docs_lint.sh --audit
```

盤四層：

1. `origin/main`
2. local committed
3. local uncommitted
4. docs debt

對每條 branch / worktree 再跑：

```bash
git log --oneline --left-right --cherry-pick origin/main...<branch>
git diff --stat origin/main..<branch>
```

判斷：

- 真正 ahead
- tree 等價但 hash 不同
- 已被 squash 吞掉的歷史殘影

---

## Phase 1 — 保存所有 dirty work

### 1.1 預設路徑：先 commit

只要 scope 清楚、邏輯單一：

```bash
git add <files...>
git commit -m "<prefix>: <message>"
```

### 1.2 黑名單工作掛在 `main`

若這批工作不能進 `main`，但目前掛在 `main` 上：

```bash
git branch <blacklist-branch> main
git worktree add <path> <blacklist-branch>   # 需要繼續工作的話
```

然後回報 mapping：

- old location: `main`
- new branch: `<blacklist-branch>`
- new worktree: `<path>`
- preserved commits: `<sha list>`

最後才允許：

```bash
git reset --hard origin/main
```

### 1.3 例外路徑：patch / copy

只有內容很碎、不適合直接留在原 branch 時才用：

```bash
git diff --binary > /tmp/<name>.patch
git ls-files --others --exclude-standard
```

---

## Phase 2 — 決定收斂策略

### 2.1 普通 merge / absorb

適用：

- branch 已靜止
- PR 已 ready
- 目標就是收入 `main`

### 2.2 Surviving blacklist

適用：

- 這批工作暫時不收
- 但要保留並同步新 `main`

操作：

```bash
git rebase origin/main
git push --force-with-lease   # 有 remote / PR 時
```

### 2.3 Promote committed subset from active branch

適用：

- branch 還在活躍修改
- 你只想先把其中一部分**已提交**內容收入 `main`
- 不想打斷原 branch 的活工作

做法：

```bash
git worktree add -b <integration-branch> <path> main
git -C <path> cherry-pick <commit...>
git -C <path> push origin HEAD:main
```

之後：

- 活 branch 本體不動
- 其他 blacklist rebase 到新 `main`
- 最後才看要不要讓原 branch 自己 rebase

---

## Phase 3 — 收斂進 `main`

### 3.1 PR mode

```bash
gh pr view <N> --json mergeable,mergeStateStatus,headRefName,files
gh pr merge <N> --squash --delete-branch
```

注意：

- 不要在 PR branch 上跑 `gh pr merge`
- draft PR 先 `gh pr ready <N>`

### 3.2 `all` / `all except`

建立一次性整合 worktree：

```bash
git worktree add -b final-cleanup /Users/chenliangyu/kg-worktrees/final-cleanup-<tag> origin/main
```

把非黑名單內容吸進去：

```bash
git cherry-pick <commit...>
# 或
git merge --squash <branch>
# 或
git apply --3way /tmp/<patch>
```

再決定：

- `verify-first`：先驗證再推 `main`
- `execution-first`：先推 `main` 再補驗證

---

## Phase 4 — Rebase surviving blacklist

`main` 一旦前進，剩下黑名單都要同步：

```bash
git -C <blacklist-worktree> rebase origin/main
git -C <blacklist-worktree> push --force-with-lease   # 有 remote 時
```

### 已投影進 `main` 的 branch

若該 branch 的部分 commits 已經先被 promote 進 `main`：

- rebase 時那些 commits 通常會被 skip
- 這通常是正確結果
- branch 之後只剩真正還沒被主線吸收的增量

---

## Phase 5 — 驗證 / doc-sync / forward-fix

優先順序：

```bash
./ops/docs_lint.sh --audit
./ops/i18n_lint.sh --baseline-check
uv run pytest -q <targets>
node --test <targets>
./ops/ios_build.sh
./ops/ios_test.sh <minimal-scope>
```

cleanup 收尾或 infra 變更才跑：

```bash
./ops/ios_test.sh --all-targets --timeout 1200
```

若測試或 review 發現問題：

- 不回退整批 cleanup
- 最小修補
- 新 commit / PR / squash merge

---

## Phase 6 — 清理一次性 worktree

integration / final worktree 用完即刪：

```bash
git worktree remove <path>
git branch -D <integration-branch>
git worktree prune
```

不允許留成第二真相。

---

## Phase 7 — 最終狀態

### `all`

- `git status` 乾淨
- `git worktree list` 只剩主 repo
- `gh pr list --state open` 為空
- `./ops/branch_audit.sh --json` `total=0`
- `./ops/docs_lint.sh --audit` `WARN=0 ERROR=0`

### `all except`

- `main` 已是最新單一真相
- 非黑名單內容全部收斂
- 僅保留 surviving blacklist branches/worktrees
- blacklist 全部 rebase 到新 `main`

