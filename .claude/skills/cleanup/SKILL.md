---
name: cleanup
description: "Workflow 1. 黑名單驅動的收斂維護者：把非黑名單工作收進 main、push/sync remote，並讓黑名單永遠 rebase 在最新 main 上。"
user-invocable: true
version: 5.0.0
---

# Cleanup

`cleanup` 現在不是一次性大掃除。  
它是**持續性的收斂維護者**。

## 核心身份

使用者先定義**黑名單**。

- 黑名單 = 暫時不吸收進 `main` 的工作
- 非黑名單 = 這一輪應該全部收斂進 `main` 的白名單工作

agent 唯一目標：

1. 保存所有工作
2. 把**非黑名單**全部收斂到 `main`
3. 同步 remote
4. 把**黑名單**全部 rebase 到最新 `main`

下一輪重來時：

- 舊黑名單可能變白名單
- 新黑名單可能出現
- agent 再做同一輪收斂

也就是說，這是一個**可反覆執行的 convergence loop**，不是一次性 cleanup。

> 一句話契約：先定黑名單 → 保存所有工作與 work identity → 收白名單進 `main` → push/sync remote → rebase 黑名單。

> 活黑名單補充契約：每輪只收斂到各分支的**已保存快照**；本輪之後新長出的 commits 或 dirty work，自動進下一輪。

---

## 命名約定

從現在開始：

- `cleanup` = 工作流 1 = `Blacklist-Driven Convergence`
- `promote` = 工作流 2 = `Promote Active Branch`

也就是說：

- 使用者說 `cleanup`
  = 你預設進入「黑名單驅動收斂」
- 使用者說 `promote`
  = 你預設進入「活 branch 已提交子集升格」

這份 skill 只負責 `cleanup` 本身。  
`promote` 有獨立 skill 入口，但兩者共享同一套哲學、playbook 與 casebook。

---

## `cleanup` 是什麼

`cleanup` = `Blacklist-Driven Convergence`

輸入：

- 哪些 branch / PR / worktree / local commits 是黑名單

輸出：

- 白名單全部進 `main`
- remote 已同步
- 黑名單全部 rebase 到新 `main`
- 白名單殘影清乾淨
- 黑名單保留為下一輪起點

## `promote` 是什麼

`promote` = `Promote Active Branch`

當某條 branch 還在持續修改，但其中一部分**已提交內容**你想先拉進 `main` 時使用。

輸入：

- 活 branch 本體保持不動
- 指定哪些**已提交 commits**要 promote

輸出：

- 這些 commits 先進 `main`
- 原 branch 再 rebase 到新 `main`
- branch 本體繼續活著

---

## 核心哲學

### 1. 保存工作先於收斂

- dirty work 預設先 `commit`
- 不能只保存內容，還要保存 **work identity**
- work identity = 這份工作屬於哪個 branch / worktree / agent

### 2. 黑名單不是不碰，而是不吸收

- 黑名單不進 `main`
- 黑名單要跟著最新 `main` 前進
- 黑名單若掛在 `main`，先抽 branch/worktree，再同步 `main`

### 3. `main` 是當前已接受的共同真相

- `main` 不承載暫時保留的分歧
- 已成熟的內容應盡快升格為 shared baseline
- 剩下的工作都站在這個 baseline 上繼續長

### 4. 活分支維護的是 snapshot，不是 moving HEAD

- 不直接追逐正在持續變動的 branch HEAD
- 每輪先把 dirty work 保存成 commit，形成 branch 的本輪 snapshot
- promote / rebase 都只針對這個 snapshot
- 這一步之後新長出的 commits，留給下一輪

---

## Read Order

1. 先讀本檔：理解角色與兩種工作流
2. 再讀 [playbook.md](./playbook.md)：完整執行手冊
3. 遇到相似情境時讀 [casebook.md](./casebook.md)：實戰案例
4. 動手前跑 [checklists.md](./checklists.md)：最後核對

---

## Hard Rules

### Rule 1 — 先盤 live state

永遠先跑：

```bash
git fetch --all --prune
git status
git stash list
git branch -vv
git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
```

### Rule 2 — 黑名單掛在 `main` 時，先抽 branch/worktree

若黑名單工作目前在 `main`：

```bash
git branch <blacklist-branch> main
git worktree add <path> <blacklist-branch>
```

然後回報 mapping：

- old location
- new branch
- new worktree
- preserved commits

只有完成這一步，才允許 reset / rebase `main`。

### Rule 3 — 活 branch 不直接硬拉本體

若 branch 還在持續修改，但要先收入其中一部分：

- 不直接 merge / rebase branch 本體
- 只 promote **已提交 commits**
- 用 integration worktree 從 `main` 投影這些 commits

### Rule 4 — 黑名單每輪都要 rebase

這不是 optional housekeeping。  
只要 `main` 前進，黑名單就要同步到新 `main`。

### Rule 5 — 不追逐本輪之後的新變動

若 branch / worktree 在你操作期間又出現新 commit 或新 dirty work：

- 不回頭重做本輪
- 只回報「本輪快照已處理到哪裡」
- 把新變動留給下一輪

### Rule 6 — 一次性容器用完即刪

integration worktree / temporary branch / final branch 都是一次性容器。  
用完就刪，不允許留下第二真相。

---

## What This Skill No Longer Is

它不再以以下內容作為主敘事：

- 一次性 `all cleanup` 大掃除
- 以 docs debt 為每次必做主線
- 複雜 phase taxonomy 本身
- 為 cleanup 而 cleanup 的 branch/worktree 清理

這些可以是附屬操作，但不是核心身份。

---

## Minimal Output Contract

每輪回報至少要有：

- 黑名單清單
- 每條活分支的 snapshot commit
- 收進 `main` 的白名單內容
- 黑名單的新 base
- preserved work mapping
- remote 同步狀態
- 最終 `git status` / `worktree list` / `branch_audit`

詳細模板看 [checklists.md](./checklists.md)。
