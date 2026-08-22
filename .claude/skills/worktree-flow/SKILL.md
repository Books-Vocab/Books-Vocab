---
name: worktree-flow
description: "使用 GitHub Issue（需要規劃時）、branch、PR 與 Actions 交付，並用很薄的本機 coordinator 管理多個 worktree 的 ownership、Scope、驗證與交接。"
---

# Worktree coordination

## Mental model

先讀 `docs/reference/delivery_model.md`。工作有兩條入口：User／IM 直接指派給 Worker，或 IM 將 Issue assignment packet 交給 Issue Solver。Worker direct assignment 必須帶 `dispatch_channel=im|user`；Worker／Issue Solver 只負責 local code/test、local commit 與 hand-back；IM 才把 exact commit push 成 PR；CM 才負責 Ready admission 與 merge。Issue 是規劃工具；branch 是變更邊界；PR 是所有 code change 的 GitHub diff、討論、CR／DS、checks 與 merge request 紀錄；merge 後的 `main` 是產品真相。

## Local boundary

`ops/worktree_registry.py` 只保存本機 ledger：

- branch、worktree path、base／HEAD
- structured Scope（`add`／`modify` file paths）與 collision
- Codex thread identity 與 GitHub external IDs
- hand-back seal、驗證命令、log／artifact 路徑

`ops/worktree_orchestrate.py` 只做本機可驗證動作：`preflight`、`open`、`adopt`、`gate`、`hand-back`、`reanchor`、`resume-published`、`resolve`、`freeze`。IM／PI 使用它控制 local worktree lifecycle；它不建立、更新、排序或關閉 GitHub Issue／Project／PR，也不執行 push 或 merge。`reanchor` 只重建同 owner 的 merge-front 並對齊 live main；`resume-published` 只從 exact remote PR HEAD 重建同 owner code-fix lane。兩者都不代替 owner 測試、hand-back、push 或 force-push。

## Standard flow

1. 先確認 repo、branch、HEAD、工作樹 clean state 與 active ownership。
2. 判斷入口：Issue Solver 從 IM 的 Issue assignment packet 取得目標；Worker 從帶 `dispatch_channel` 的 User／IM assignment 取得目標。建立最小 structured Scope，檢查 overlap。
3. `open` 或 `adopt` worktree；所有修改只在該 path 內進行。
4. 先寫 focused failing proof，再做最小修復；只跑能證明這個 Scope 的 focused validation。大型 backend／iOS／UI／ops confidence 留給 GitHub，不可成為 publication 前置條件。
5. `gate` 是可選的 focused evidence capture；pass 不等於 publication、Ready 或 merge permission，未執行大型 local gate 也不阻止 clean committed hand-back。
6. Worker／Issue Solver 在 local branch commit，執行 typed hand-back；PI 驗證 exact HEAD 後立即 push 並開／更新 PR，readback 成功即釋放 local worktree／local branch。PR 必須標明 direct assignment 或關聯 Issue。只有 exact PR／registry／remote proof 完整且 local assets 已不存在時，PI 才能用 `delivery.py abandon-pr` 做可重試的終止；dirty、unknown 或 remote-drift worktree 不得刪除。
7. PI 交付 durable 非 draft PR，不把它誤報為 Ready；CM 重新驗證 GitHub required、live tuple、hold 與 repository rules，再送 native merge queue。routine CR／DS／confidence 平行收斂，只有 P0／P1／security durable hold 阻擋。release、deploy 由各自 SOP 控制。

## Dispatch and hand-back

- `dispatch_channel=im`：Worker 和 `dispatch_owner` 討論，hand-back recipient 固定為同一個 IM；不接受改 hand-back 給其他人。
- `dispatch_channel=user`：Worker 和 User 討論；若 assignment 指定 `handback_target` 就交給該 IM，否則 Worker 必須在 hand-back 前選定一個 IM。
- `Issue Solver` 不走 Worker 的 User channel；它只消除 IM 傳入的 Issue assignment packet，並 hand-back 給派遣 IM。

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

以下情況停止本機動作並回報：Scope 與 diff 不一致、active owner 不明、HEAD 已變、gate block、工作樹不乾淨、dispatch channel／recipient 不明、需要修改另一個 worktree、需要 GitHub／production 權限，或需要不可逆操作。Worker／Issue Solver 遇到任何 GitHub／push／PR 需求，一律 hand-back 給已解析的 IM，不自行繞路。不要用本機檔案新增另一套狀態來掩蓋缺口。
