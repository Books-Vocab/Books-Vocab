# Cleanup / Promote Casebook

---

## Case 1 — 黑名單工作掛在 `main`

### 症狀

- 某 agent 直接在 `main` 上 commit
- 但這批工作現在是黑名單
- 你又需要把 `main` 同步回最新 shared baseline

### 正確做法

1. 從 `main` 抽出黑名單 branch
2. 必要時建立 worktree
3. 回報 preserved mapping
4. 再同步 `main`

### 為什麼

不這樣做，雖然 commit 可能還在 reflog，但對原 agent 來說工作身份已經消失。

---

## Case 2 — Promote 活 branch 的已提交子集

### 症狀

- `catalog/scope-campaign` 還在修改
- 你想先把其中 5 個已提交 commits 拉進 `main`
- 不想影響 branch 本體

### 正確做法

1. 用 integration worktree 從 `main` 出發
2. `cherry-pick` 那 5 個 commits
3. push 到 `main`
4. 其他黑名單 rebase 到新 `main`
5. 活 branch 本體保持不動
6. 最多只刪 integration 容器，不刪原 branch / worktree

### 意義

把成熟成果升格成 shared baseline，同時不打斷活工作。

---

## Case 3 — 已投影進 `main` 的 branch 再 rebase

### 症狀

- 某 branch 的 commits 先被投影進 `main`
- 之後對 branch 做 `rebase main`
- 出現 `skipped previously applied commit`

### 正確解讀

這通常是成功，不是失敗。  
代表那些 commits 已經等價存在於 `main`，branch 之後只剩真正未吸收的增量。

---

## Case 4 — 黑名單 PR 不是不動，而是要同步

### 症狀

- 使用者說某 PR 是黑名單
- 它不應該這輪 merge

### 正確做法

- 不吸收進 `main`
- 但 `main` 一旦前進，它就必須 rebase 到新 `main`
- 有 remote / PR 時 force-push 回去

### 為什麼

黑名單代表暫時保留，不代表允許 stale。

---

## Case 5 — Ready / Draft 只是 GitHub workflow state

### 症狀

- `gh pr merge` 回 `Pull Request is still a draft`

### 正確做法

```bash
gh pr ready <N>
gh pr merge <N> --squash --delete-branch
```

### 為什麼

這不是 code conflict，只是 PR 狀態未切換。

---

## Case 6 — 已 merge 但 remote branch 殘留

### 症狀

- PR 已 merge
- `branch_audit` 還看到 merged branch ahead

### 正確做法

```bash
git push origin --delete <branch>
git branch -D <branch>
git fetch --prune
```

### 為什麼

真正的收斂不是「PR merged」，而是「殘影也消失」。

---

## Case 7 — 黑名單 branch 持續有人提交

### 症狀

- 黑名單 worktree 還在被另一個 agent 持續修改
- 你在 cleanup 期間看到新的 dirty work 或新 commit
- 你不想打斷它，但也不能讓它脫離最新 `main`

### 正確做法

1. 先把當下 dirty work commit 到原 branch
2. 把這個 commit 視為本輪 snapshot
3. promote / rebase 只處理到這個 snapshot
4. 若之後又出現新 commit，不回頭重做本輪
5. 在 final report 明講：本輪處理到哪個 snapshot，之後新增量留待下一輪

### 為什麼

cleanup 維護的是「本輪已知快照」，不是一條會持續變動的 moving HEAD。

---

## Case 8 — promote 一條、另一條繼續活著再 rebase

### 症狀

- 兩條黑名單都還在活
- 其中一條改動小、成熟、衝突面低
- 另一條仍在快速長

### 正確做法

1. 先 promote 較小且成熟的那條前綴進 `main`
2. push / sync `main`
3. 把另一條活黑名單 rebase 到新 `main`
4. 兩條 branch / worktree 都保留
5. promote 那條若也要繼續活著，同樣保留；只回收 integration 容器

### 為什麼

這樣做的目的不只是避衝突，而是讓 shared baseline 儘快吸收成熟成果，同時不追逐仍在變動的分支本體。
