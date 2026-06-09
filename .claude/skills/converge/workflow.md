# Converge Agent Protocol v1

Agent-in-loop robust workflow。不用自動 `git add -A`，snapshot 人工把關。

---

## 核心模型：Phase Loop

```
PHASE 0: DISCOVER  →  PHASE 1: SNAPSHOT_REVIEW  →  PHASE 2: PREPARE
                                                          ↓
PHASE 6: REPORT  ←  PHASE 5: FINAL_REBASE  ←  PHASE 4: PUSH  ←  PHASE 3: MERGE
```

每個 PHASE 有 **Entry Condition** / **Action** / **Exit Gate** / **Recovery**。
遇到 HARD STOP（人工把關點）暫停 loop，user 決定後 `resume`。

---

## PHASE 0: DISCOVER（自動）

**Entry:** 任何時候可進入

**Action:**
```bash
git fetch --all --prune
git branch -vv
git worktree list
git status --short  # main worktree
```

對每個 worktree 執行 `git -C <wt> status --short`，收集 dirty_map。

**Output:**
```
DISCOVER REPORT
- main: <hash> [ahead/behind N]
- branches: N total
  - <name>: <hash> [worktree: <path> | no worktree] [dirty: Y/N]
  - ...
- dirty worktrees: [<paths>]
- orphan worktrees: [<paths>]
```

**Exit Gate:**
- 無 dirty work → 進 PHASE 2
- 有 dirty work → 進 PHASE 1

---

## PHASE 1: SNAPSHOT_REVIEW（人工把關）

**Entry:** dirty_map 非空

**Action:** 對每個 dirty worktree，依序顯示：

```
=== SNAPSHOT_REVIEW: <worktree_name> ===
Branch: <branch_name>
HEAD: <hash>

Status:
  M <file1>
  M <file2>
  ?? <file3>

Diff summary:
  <file1>: +N -M
  <file2>: +N -M

Full diff (first 50 lines):
  <git diff --stat>

Decision: [snapshot / skip / inspect / abort]
  - snapshot: git add -A && git commit -m "<prefix>: snapshot — <desc> (converge)"
  - skip: 保留 dirty，不 commit（rebase 會被擋，需 user 承擔風險）
  - inspect: 開啟該 worktree，user 手動處理後回到此 phase
  - abort: 停止整個 converge
```

**HARD STOP 規則：**
- 絕對不自動 `git add -A`
- 必須 user 顯式輸入 `snapshot` 才 commit
- untracked 大檔案（>1MB）要特別標註警告
- `.coverage` / `node_modules` / `.venv` 等已知垃圾檔案要標註「建議 gitignore」

**Exit Gate:**
- 所有 dirty worktree 處理完（snapshot 或 skip）→ 進 PHASE 2
- user 輸入 abort → 停止，輸出已完成的決策記錄

---

## PHASE 2: PREPARE（自動，並行）

**Entry:** 所有 worktree 已 snapshot 或 user 確認 skip

**Action:** 對每個要收斂的 branch：

```bash
# 在有 worktree 的 branch 中
git -C <worktree> fetch origin main
git -C <worktree> rebase origin/main
git -C <worktree> push origin HEAD --force-with-lease

# 在無 worktree 的 branch 中
git checkout <branch>
git rebase origin/main
git push origin HEAD --force-with-lease
```

**並行策略：**
- 每個 branch 派一個 background agent（`run_in_background: true`）
- 主 agent 等待所有結果
- 任何 agent 回報失敗 → 進入 Recovery

**Exit Gate:**
- 全部 success → 進 PHASE 3
- 任何 conflict / error → Recovery

**Recovery:**
```
CONFLICT DETECTED: <branch_name>
Worktree: <path>
Files in conflict:
  <file1>
  <file2>

Action: 暫停 converge，開啟該 worktree 讓 user 解 conflict
User 修復後輸入 `resume` 繼續 PHASE 2
```

---

## PHASE 3: MERGE（自動）

**Entry:** 所有 branch 已 rebase 到 origin/main

**Action:**

```bash
cd <main_worktree>
git merge <branch1> <branch2> ... --no-edit   # octopus merge
```

**Fallback（octopus 失敗）：**
```bash
for branch in <branches>; do
  git merge "$branch" --no-edit || exit 1
done
```

**Exit Gate:**
- merge success → 進 PHASE 4
- merge conflict → HARD STOP（非常罕見，因為 PHASE 2 已 rebase）

**Recovery:**
```
MERGE CONFLICT: <branch_name>
Files:
  <file1>
  <file2>

Action: 暫停。user 在 main worktree 解 conflict 後 `resume`
```

---

## PHASE 4: PUSH（自動）

**Entry:** merge success

**Action:**
```bash
git push origin main
```

**Exit Gate:**
- push success → 進 PHASE 5
- push rejected（remote 有新 commits）→ Recovery

**Recovery:**
```bash
git fetch origin main
git rebase origin/main  # 或 merge，視情況
# 重試 push
```

---

## PHASE 5: FINAL_REBASE（自動，並行）

**Entry:** main pushed

**Action:** 同 PHASE 2，所有 branch rebase 到新 main + push

**Exit Gate:**
- 全部 success → 進 PHASE 6
- 任何 conflict → Recovery（同 PHASE 2）

---

## PHASE 6: REPORT（自動）

**Entry:** 全部完成

**Output:**
```
CONVERGE COMPLETE

Main: <hash>
Mode: <all-black|all-white|promote|full>

Phases executed:
  - PHASE 0: DISCOVER
  - PHASE 1: SNAPSHOT_REVIEW (X worktrees reviewed, Y snapshotted, Z skipped)
  - PHASE 2: PREPARE (N branches rebased)
  - PHASE 3: MERGE (octopus|sequential)
  - PHASE 4: PUSH
  - PHASE 5: FINAL_REBASE

Branches state:
  | Branch | HEAD | Status |
  |--------|------|--------|
  | ... | ... | ... |

Worktrees:
  | Path | Branch | Status |
  |------|--------|--------|
  | ... | ... | ... |

Next-round deltas (if any):
  - <branch>: <reason>
```

---

## State Persistence

Converge 過程中任何 HARD STOP 時，保存狀態到 `.claude/converge_state.json`：

```json
{
  "phase": "PHASE_2",
  "branches": {
    "main": { "hash": "...", "pushed": true },
    "branch1": { "hash": "...", "rebased": true, "pushed": true },
    "branch2": { "hash": "...", "rebased": false, "error": "conflict" }
  },
  "snapshots": {
    "wt1": { "hash": "...", "decision": "snapshot" },
    "wt2": { "hash": null, "decision": "skip" }
  },
  "merge": { "completed": false }
}
```

Resume 時讀取此狀態，從中斷點繼續。

---

## 與 SKILL.md 的對應

| SKILL.md 模式 | Agent Protocol |
|--------------|----------------|
| A all black | PHASE 0 → PHASE 2 → PHASE 5 → PHASE 6（跳過 MERGE） |
| A all white | 全部 PHASE（最後清殘影） |
| B promote | PHASE 0 → PHASE 2（target）→ PHASE 3 → PHASE 4 → PHASE 5（others）→ PHASE 6 |
| 組合式全量 | 全部 PHASE |

---

## 為什麼比手動 Bash 更 robust

1. **統一 cwd 管理** — 所有命令用 `git -C <絕對路徑>`，不依賴 Bash cwd 持久化
2. **狀態保存** — HARD STOP 時不丟失進度，`resume` 繼續
3. **並行安全** — 每個 branch 獨立 agent，失敗隔離
4. **人工把關** — snapshot 必須 user 確認，不盲 add
5. **強制驗證** — 每個 PHASE 有 exit gate，不通過不往下走