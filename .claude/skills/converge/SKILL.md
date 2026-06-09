---
name: converge
description: "Branch/worktree convergence skill：先立 T0 snapshot barrier，離線組 final state，再用極短 cutover 推進 main 並重掛存活分支。"
user-invocable: true
version: 1.0.0
---

# Converge

`converge` 是 branch/worktree 收斂的**單一 canonical skill**。

它服務兩種需求：

- `mode=cleanup`：吸收所有非黑名單工作進 `main`
- `mode=promote`：只吸收活 branch 的指定已提交子集進 `main`

`cleanup` / `promote` 只是語意入口。  
真正的方法論只有一套：**T0 snapshot barrier → offline integration → short cutover → post-cutover reconcile**。

## 什麼時候用

- 你要收斂 branch / worktree / PR 到新 `main`
- branch 還在活，但其中一部分已值得成為 shared baseline
- 你要避免在 hot branch 上追逐 moving HEAD
- 你要把最終變動壓縮到極短 cutover，而不是邊驗證邊改 live branch

## Mode 選擇

### `cleanup`

適用於：

- 使用者先定黑名單
- 其餘白名單都應收進 `main`
- 白名單殘影應清掉
- 黑名單應保留並 rebase 到新 `main`

### `promote`

適用於：

- 某條 branch 還在持續修改
- 但其中一部分**已提交 commits**要先成為 shared baseline
- 原 branch / worktree 要繼續活著
- 除非使用者明確要求，不自動清原 branch / worktree

## 核心契約

1. **先立 T0，再做其他事**
   - 先盤 live state
   - 先把本輪要處理的 dirty work 保存成 snapshot
   - T0 之後的新 dirty / new commit 一律進下一輪

2. **不要在主流程追逐 hot branch**
   - 驗證與整合都在離線 integration/final worktree 做
   - cutover 前不回頭重新讀活 branch working tree

3. **cutover 要極短且序列化**
   - push `main`
   - fetch/prune
   - rebase survivors
   - force-push survivors（若有 remote）
   - 清理白名單殘影或 integration 容器

4. **commit reachability 是真相**
   - PR state 只是 metadata
   - `./ops/branch_audit.sh --json` 是 machine-readable authority

## Read Order

1. 先讀本檔：理解 mode 與 methodology
2. 再讀 [methodology.md](./methodology.md)：完整執行手冊
3. 動手前跑 [checklists.md](./checklists.md)
4. 遇到相似情境時讀 [casebook.md](./casebook.md)

## 最小輸出契約

- mode：`cleanup` 或 `promote`
- T0 時間點與各分支 snapshot commit
- 收進 `main` 的內容
- short cutover 做了哪些序列化步驟
- surviving branch 是否已 rebase 到新 `main`
- 哪些 branch/worktree 被保留、哪些被清掉
- 哪些變更因為發生在 T0 之後，被明確留到下一輪
