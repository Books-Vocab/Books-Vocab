---
name: cleanup
description: "把 repo 收斂到單一真相，同時先保存所有 agent 的工作與 work identity。主文只放核心契約；完整流程、案例與 checklist 分流到 playbook / casebook / checklists。"
user-invocable: true
version: 3.5.0
---

# Cleanup

**唯一目標 = 用最短時間把 repo 收斂到清楚、可交接、可繼續工作的狀態。**

cleanup 的第一責任不是清乾淨，而是**保存所有 agent 已經做出的工作**。  
收斂只在保存完成後才成立。

> 一句話契約：cleanup = 先盤 live state → 先把所有 dirty work 變 durable 並保住 work identity → 收斂非黑名單內容到 `main` → surviving blacklist rebase 到新 `main` → 再做驗證 / forward-fix / doc 收尾。

---

## Read Order

1. 先讀本檔：核心契約、mode、硬規則
2. 再讀 [playbook.md](./playbook.md)：完整 phase / 指令 / promote / rebase 流程
3. 遇到相似事故時讀 [casebook.md](./casebook.md)：實戰案例與決策模式
4. 動手前跑 [checklists.md](./checklists.md)：收斂前最後核對

---

## Core Philosophy

### 1. 先保存工作，再收斂

- dirty work 預設先 `commit`
- 不能只保存內容，還要保存 **work identity**
- work identity = 這份工作現在屬於哪個 branch / worktree / agent

### 2. 只保存 hash 不算保存

以下都算失敗：

- 先 reset `main`，再說 commit 還在 reflog
- 把工作偷偷搬到別的 branch，但沒回報 mapping
- 讓原 agent 從自己的視角感知成「工作不見了」

### 3. 黑名單不是不碰，是不吸收

- 黑名單 work 不吸收進 `main`
- 黑名單 work 允許 rebase / 解衝突 / force-push
- 黑名單若掛在 `main`，必須先抽 branch/worktree，再同步 `main`

### 4. `main` 只能承載 shared baseline

- `main` 應是當前共同真相
- 若某批工作已被接受，可先 promote 進 `main`
- 其他黑名單再 rebase 到新的 shared baseline

---

## Mode Matrix

| 輸入 | 模式 | 終態 |
|---|---|---|
| `/cleanup` | PR mode | 收斂指定 PR；其餘本地工作可保留 |
| `/cleanup except A,B` | PR mode + 黑名單 | 收斂除 A/B 外的 PR；黑名單保留 |
| `/cleanup all` | Full convergence | repo 完全收斂：零本地改動、零殘留 branch/worktree、零 open PR |
| `/cleanup all except A,B` | Scoped full convergence | 除 A/B 外全部收斂；僅保留 `main + surviving blacklist branches/worktrees` |

---

## Hard Rules

### Rule 1 — 先建真相，再做任何刪除

永遠先跑：

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

### Rule 2 — 黑名單掛在 `main` 時，先抽 branch/worktree

若黑名單工作目前在 `main`：

```bash
git branch <blacklist-branch> main
git worktree add <path> <blacklist-branch>   # 需要持續工作時
```

然後回報：

- 原位置：`main`
- 新 branch：`<name>`
- 新 worktree：`<path>`（若有）
- preserved commits：`<sha list>`

只有完成這一步，才允許 reset / rebase `main`。

### Rule 3 — dirty work 預設先 commit

只要 scope 清楚、邏輯單一，就先 commit。  
patch / copy 是例外，不是預設。

### Rule 4 — 活 branch 可 promote commits，但不直接動 branch 本體

若某條 branch 還在持續修改，但你想先把部分已成熟 commits 收入 `main`：

- 不直接 merge / rebase 那條活 branch
- 從隔離 integration worktree 用 `cherry-pick` 投影已提交 commits 到 `main`
- 活 branch 本體保持不動

### Rule 5 — surviving blacklist 必須同步新 `main`

`main` 一旦前進，剩下的 blacklist 要 rebase 到新 `main`。  
已投影進 `main` 的 commits 在 rebase 時被 skip，通常是正確結果，不是資料丟失。

### Rule 6 — `final-cleanup` / integration worktree 都是一次性容器

- 用完就刪
- 不允許留下第二真相

### Rule 7 — 長時背景任務要能取消

若策略切換成「先收斂再驗證」，要主動取消：

- `ios_ops.sh build`
- `ios_test.sh --all-targets`
- 長時 pytest / node / generator

不能讓舊 session 綁住已完成任務的 worktree。

---

## Minimal Flow

1. 盤四層真相：`origin/main` / local committed / local uncommitted / docs debt
2. 保存所有 dirty work，必要時從 `main` 抽 branch/worktree
3. 決定 mode / scope / 黑名單 / 驗證策略
4. 把非黑名單內容收斂進 `main`
5. surviving blacklist rebase 到新 `main`
6. 視策略補驗證、doc-sync、forward-fix
7. 清掉一次性 integration/final worktree

完整版本見 [playbook.md](./playbook.md)。

---

## When To Read Companion Docs

- 想把活 branch 的已提交內容先拉進 `main`：看 `playbook.md` 的 `promote committed subset`
- 黑名單工作掛在 `main`：看 `casebook.md` 的 `blacklist-on-main`
- 已投影進 `main` 的 branch 再 rebase：看 `casebook.md` 的 `projected-then-rebase`
- reset `main` 前不確定會不會把 agent 工作弄丟：先跑 `checklists.md` 的 `before reset main`

---

## Report Contract

回報至少要有：

- 收斂進 `main` 的內容
- surviving blacklist 與其新 base
- preserved work mapping（特別是從 `main` 抽出的工作）
- 已跑 / 後置的驗證
- 最終 `git status` / `worktree list` / `branch_audit` 狀態

詳細模板見 [checklists.md](./checklists.md)。

---

## Top Hazards

1. 只保存 commit、不保存 work identity，agent 仍會感知成「工作被清掉」。
2. 若黑名單工作掛在 `main`，先抽 branch/worktree，再 reset `main`；反過來做是流程失敗。
3. `all except` 不是「完全不碰黑名單」，而是「不吸收，但要同步」。
4. 活 branch 若仍在修改，應 promote commits，不應直接 merge / rebase branch 本體。
5. `gh pr merge` 不要在 PR branch 上跑，避免 gh 切回 `main` 撞工作樹。
6. 驗證可以後置，但已知失敗必須明講。
7. docs debt 在 `all` / `all except` 是正式收斂項，不是附帶 housekeeping。
