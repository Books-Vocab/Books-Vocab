---
name: worktree-flow
description: "使用 GitHub Issue（需要規劃時）、branch、PR 與 Actions 交付，並用很薄的本機 coordinator 管理多個 worktree 的 ownership、Scope、驗證與交接。"
---

# Worktree coordination

## Mental model

先讀 `docs/reference/delivery_model.md`。工作有兩條入口：User／IM 直接指派給 Worker，或 IM 將需要排序／追蹤的工作放進 GitHub Issue 後交給 Issue Solver。Issue 是可選的規劃工具；branch 是變更邊界；PR 是所有 code change 的 diff、討論、CR／DS、checks 與 merge request 紀錄；merge 後的 `main` 是產品真相；release 依獨立 SOP。local worktree 只是隔離實作環境。

## Local boundary

`ops/worktree_registry.py` 只保存本機 ledger：

- branch、worktree path、base／HEAD
- structured Scope（`add`／`modify` file paths）與 collision
- Codex thread identity 與 GitHub external IDs
- hand-back seal、驗證命令、log／artifact 路徑

`ops/worktree_orchestrate.py` 只做本機可驗證動作：`preflight`、`open`、`adopt`、`gate`、`hand-back`、`resolve`、`freeze`。它不建立、更新、排序或關閉 GitHub Issue／Project／PR，也不執行 merge。

## Standard flow

1. 先確認 repo、branch、HEAD、工作樹 clean state 與 active ownership。
2. 判斷入口：Issue Solver 從 GitHub Issue 取得目標；Worker 從 User／IM assignment 取得目標。建立最小 structured Scope，檢查 overlap。
3. `open` 或 `adopt` worktree；所有修改只在該 path 內進行。
4. 先寫 failing test，再做最小修復；長測試保留 heartbeat 與完整輸出。
5. `gate` 只驗證當前 worktree；pass 不等於 merge permission。
6. commit，執行 `hand-back`，開／更新 PR；PR 必須標明 direct assignment 或關聯 Issue。
7. 等 GitHub Actions、CR、DS 與 repository rules；CM merge。release、deploy 由各自 SOP 控制。

## Gate routing

Coordinator 依 changed paths 選最小充分檢查：

- shell：interpreter syntax；
- Python：compile／backend pytest；
- iOS：既有 `ios_ops.sh test --unit`，UI／release 依 domain SOP；
- docs：`docs_lint.sh`；
- ops／workflow：對應 ops test 與 YAML／shell contract。

Gate output 綁定 exact HEAD，保留 command、exit status、duration、log path 與 failure summary。沒有當下 output 就不能宣稱通過。

## Scope, rebase preflight and hand-back

Scope 只解決檔案 ownership，不代替 Issue acceptance 或 direct assignment。多 worktree 同時碰同一檔案時先停下並報告 collision；未知 Scope 不推測。hand-back 至少包含 branch、path、exact HEAD、Scope、Issue／PR external ID（若已有）、direct assignment 摘要（若無 Issue）、驗證命令與 blocker。

需要 rebase 前判定 incoming main 是否碰到已宣告 Scope 時，使用 `preflight --worktree <path> --base <base-commit> --incoming-main <main-ref> --json`。它只以 active registry record 的 structured Scope 比對 `base..incoming-main`，並把 `base..HEAD` 的 own-branch diff 另列；缺 ref、unknown Scope 或找不到唯一 active record 時 fail closed，且不執行 rebase。

## Safe stopping

以下情況停止本機動作並回報：Scope 與 diff 不一致、active owner 不明、HEAD 已變、gate block、工作樹不乾淨、需要修改另一個 worktree、需要 GitHub／production 權限，或需要不可逆操作。不要用本機檔案新增另一套狀態來掩蓋缺口。
