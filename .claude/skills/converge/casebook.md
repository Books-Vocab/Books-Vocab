# Converge Casebook

---

## Case 1 — 驗證很久，hot branch 又變髒

### 症狀

- 你在 integration worktree 跑測試或 docs gate
- 其他 hot branch 又長出 dirty work 或新 commit

### 正確做法

1. 不回頭重盤那些 branch
2. 堅持本輪只處理 `T0` snapshot
3. 把新 dirty / new commits 明確標為 next-round delta

### 為什麼

一旦在主流程重新觀察 hot branch，就從 convergence 退化成追逐 moving HEAD。

---

## Case 2 — promote 活 branch 的成熟前綴

### 症狀

- branch 還在快速修改
- 但前幾個 commits 已經成熟

### 正確做法

1. 先把 dirty work 落成本輪 snapshot
2. 在 integration worktree 只 cherry-pick 那些成熟 commits
3. 完成驗證後做極短 cutover
4. 原 branch 再 rebase 到新 `main`
5. 原 branch/worktree 保留

---

## Case 3 — cleanup 只有一條白名單，其餘都還是 hot blacklist

### 症狀

- 白名單很少
- 其餘 branch 都還在活

### 正確做法

1. 先為所有 hot blacklist 立 `T0`
2. 只在離線 worktree 驗證與吸收白名單
3. cutover 時一次 push `main`
4. 黑名單只 rebase 到 `T0` snapshot
5. 不在 cleanup 後段重新盤黑名單 working tree

### 為什麼

重點不是黑名單數量，而是把 live 變動排除在 cutover 之外。
