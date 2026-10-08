<!-- doc-meta
tier: reference
authority: SoT
update_trigger: issue-management-changed
scope:
  - .github/
  - .claude/skills/github-coordination/
  - docs/reference/delivery_model.md
  - ops/delivery.py
  - ops/delivery_control/
  - ops/worktree_registry.py
  - ops/worktree_registry_core/
  - ops/doctor_issue.py
verified_against: 68f469063195b730c09fa5623722c021c9bbb435
-->
# Issue Management

GitHub Issue 的 label 分類、狀態機、優先級、公開認領協議、工作看板與 PR 連結規則的唯一權威文件。交付角色與 PR 收斂見 [`delivery_model.md`](delivery_model.md)；本文件只定義 Issue 層。它不記錄任何一張 Issue 的即時狀態。

## 目標

任何環境（本機、雲端 session、CI）的任何代理，只靠 GitHub 讀取，就能在兩次工具呼叫內回答：

1. 下一個該做什麼？（優先級＋可派工狀態）
2. 這個 Issue 有沒有人在做？誰？做到哪？預計何時回報？
3. 哪些檔案範圍（Scope）現在被占用？

主要讀者是代理，不是人；因此事實以機讀標記為準，人讀文字只是同一事實的呈現。沒有 GitHub Project，也不需要。

## 決策（D1–D8）

| # | 決策 | 理由 |
|---|---|---|
| D1 | 日常派工語言維持 `ready-for-solver`；`delivery:candidate` 保留為「經 `admit-candidate` 驗證契約的嚴格子集」，不是第二條路 | 現有工具與流程已用兩者；改名會破壞既有流程 |
| D2 | 狀態 label 不加前綴（沿用 `ready-for-solver`、`blocked` 等），每個 Issue 恰有一個狀態 | 與現況一致，零遷移成本 |
| D3 | 優先級以 `P0`–`P3` label 為準；`admit-candidate` 驗證 candidate body 的 `severity` 與 label 相同 | 單一來源，避免兩處漂移 |
| D4 | 認領 = Issue 上一則帶機讀標記的留言 ＋ 狀態 label；**不使用 assignee** | 所有代理共用同一個 GitHub 帳號，assignee 無法區分 lane |
| D5 | 認領 TTL 預設 6 小時；到期只標 `claim-stale`，**不自動釋放** | 實測 lane 約 1–4 小時；釋放是 IM 的決定 |
| D6 | PR 完全解決某 Issue → PR 內文寫 `Closes #N`，合併即由 GitHub 自動關閉；只解決一部分 → `Refs #N`，Issue 回到 `ready-for-solver` | 整合 PR 一次吃多個 Issue，逐一明確列出 |
| D7 | 既有 `close-terminal-issues` 保留為安全網（定期 dry-run 報告），不是主要關閉手段 | 它已存在且有證據檢查 |
| D8 | 公開看板用「一個自我更新的 Issue」，仿 `ops/doctor_issue.py` 的 health-report 前例 | 代理一次讀取即可得全貌 |

另有兩個前提：**認領權限只屬於 IM，但認領事實必須公開、任何人可讀**；**不建立 GitHub Project 與 assignee 這類第二套真相**。

## Label 分類

| 類別 | 值 | 規則 |
|---|---|---|
| 狀態（open Issue 恰好一個） | `needs-triage` → `needs-info`／`blocked` → `ready-for-solver` → `in-progress` → `in-review` → 關閉 | 見「狀態機」 |
| 優先級（恰好一個） | `P0` `P1` `P2` `P3` | 見「優先級」 |
| 領域（一至二） | `area/ios` `area/backend` `area/lab-podcast` `area/ops-ci` `area/docs` `area/tests` | |
| 類型（一個） | `bug` `enhancement` `tech-debt` `epic` | 安全問題另加 `security` |
| 旗標（可選） | `claim-stale` `claim-conflict` `delivery:candidate` `delivery-hold:p0`／`delivery-hold:p1`／`delivery-hold:security` | `delivery:candidate` 與 `delivery-hold:*` 沿用現有語義，不在此改動 |
| 系統 | `work-board` `health-report` | 自動維護的 Issue 專用；一般排序與盤點排除 |

每個 label 都必須有非空的 description（`gh label list` 可讀回）；新增 label 時同步補說明。

## 狀態機

| 從 → 到 | 觸發 | 執行者 |
|---|---|---|
| (新) → `needs-triage` | 建立 Issue | 任何人 |
| `needs-triage` → `ready-for-solver` | 補齊 Solver Packet（Scope、acceptance、驗證指令），且 claims 已對照 `main` 驗證 | 任何寫作者 |
| `needs-triage`／`ready-for-solver` → `needs-info` | 有只有 owner 能決定的問題 | 任何寫作者 |
| `ready-for-solver` → `blocked` | 依賴未完成的 Issue（內文寫 `Blocked by: #N`） | 任何寫作者 |
| `blocked` → `ready-for-solver` | 前置 Issue 關閉 | 任何寫作者／自動化 |
| `ready-for-solver` → `in-progress` | **IM 認領**（見「認領協議」） | **僅 IM** |
| `in-progress` → `ready-for-solver` | IM 釋放（`release`）或 PR 只 `Refs` 合併 | 僅 IM／自動化 |
| `in-progress` → `in-review` | PR 開啟並關聯該 Issue | 自動化 |
| `in-review` → 關閉 | PR 合併且 `Closes #N` | GitHub 原生 |
| `in-review` → `in-progress` | PR 關閉未合併，lane 仍在 | 自動化 |

「任何寫作者」只能做**非權威**轉換（補資訊、標阻擋、轉 ready）。**認領、釋放、准入 `delivery:candidate`、合併、上線**維持 IM／CM。狀態轉換是單向有限集合；任一寫入者在改 label 前先讀取、寫後讀回。表外的轉換（例如 `in-review` 直接回 `needs-triage`）不是合法自動轉換，只能由 IM 手動處理並在 Issue 留言說明。

## 優先級

| 級 | 含義 | 例 |
|---|---|---|
| P0 | 正式環境資料損毀／遺失、服務中斷，或正在被利用的漏洞 | 同步刪除使用者卡片 |
| P1 | 有現實觸發路徑的安全、隱私、版權、資料完整性風險，或核心流程壞掉 | 儲存型 XSS、可 OOM 的未驗證請求 |
| P2 | 使用者可見錯誤或可靠性問題，有 workaround | 離線訊息錯誤 |
| P3 | 清理、測試、文件、無使用者可見影響的強化 | 移除死碼 |

**派工順序**：先高優先級；同級時依 ① 能解除其他 Issue 阻擋者 ② 範圍小者 ③ 較舊者；一律跳過 Scope 與現有認領重疊者。只有 `ready-for-solver` 可被派工。

優先級是排序，不是 hold：P0／P1／security 的 merge hold 仍只由 `delivery-hold:*` 與 typed body 表達（見 `delivery_model.md`）。

## 認領協議（公開、機讀、IM 專屬寫入）

認領是在 Issue 發一則留言，內含人讀一行＋機讀標記（沿用本 repo 的 `<!-- kg.* -->` 慣例）：

```text
🔒 Claimed by lane <lane_id> until <expires_at>. Scope: <N files>.
<!-- kg.issue.claim.v1
{"schema":"kg.issue.claim.v1","action":"claim","issue":2101,
 "lane_id":"ISSUE-2101-...","owner_thread":"deliver-cli","branch":"lane-...",
 "scope":{"files":["ios/.../KGService+Sync.swift"]},
 "claimed_at":"2026-10-08T03:00:00Z","expires_at":"2026-10-08T09:00:00Z","generation":1}
-->
```

- `schema` 固定 `kg.issue.claim.v1`；`action` 為 `claim`｜`renew`｜`release`。
- `release` 必須帶 `reason`：`pr-published`｜`abandoned`｜`reassigned`｜`stale-cleared`。`claim`／`renew` 不帶 `reason`。
- `lane_id` 是本機 registry 的 lane 識別；`owner_thread` 區分共用同一 GitHub 帳號的不同執行緒；`scope.files` 與 registry 的 structured Scope 相同；`generation` 隨每次 `renew` 遞增，`claim` 為 1。
- 時間一律 UTC ISO-8601；`expires_at` 預設為 `claimed_at` + 6 小時（D5）。
- **有效認領** = 該 Issue 上最新一則由授權作者發出、`action != release` 且未過期的標記。授權作者清單放 `ops/issue_claim_authors.json`（目前只有一個帳號，所以另以 `owner_thread` 區分 lane）。
- **衝突**：兩則認領並存時，**留言 id 較小者有效**；後者由自動化標 `claim-conflict`。
- **偽造防護**：標記只認授權作者；未授權帳號的標記一律忽略，並由看板列出。
- **到期**：到期只加 `claim-stale`，認領仍保留可見；是否釋放由 IM 決定（D5）。IM 清除過期認領時發 `release`，`reason=stale-cleared`。
- **讀取**（任何環境）：`issue_read get_comments` 取最新標記，或直接讀看板。
- **寫入**（僅 IM）：認領留言與 `ready-for-solver` → `in-progress` 是同一次操作；先讀 Issue 現況與既有認領，再寫，最後讀回，失敗則不留半成品。Worker／Issue Solver 沒有 GitHub 寫入權，不得發認領標記。

### 實作入口

協議本身與工具無關：任何時刻 IM 都可以用符合上述格式的手動留言＋label 完成認領。指令表面分批落地：`ops/delivery.py claim-issue`／`renew-claim`／`release-issue`／`claims`（唯讀）負責留言協議，`ops/issue_sync.py` 與 `issue-sync` workflow 負責狀態同步與看板，`worktree_orchestrate.py open`／`resolve` 在帶 `--external-id '#N'` 時串接。工具未落地前的行為以本節協議為準，落地後工具以本節為契約，行為與本文衝突時修工具。

## 公開看板

一個自我更新的 Issue「Work board」（label `work-board`），body 含：

1. 人讀表格：依優先級排序的 `ready-for-solver`、`in-progress`（含 lane、到期時間）、`in-review`（含 PR）、`blocked`／`needs-info`；另列無對應 Issue 的 open PR。
2. 機讀區塊 `kg.issue.board.v1`（JSON）：每個 open Issue 的 `number`、`title`、`status`、`priority`、`areas`、`type`、`claim`（`lane_id`、`branch`、`expires_at`、`scope.files`）、linked PR、`stale`／`conflict` 旗標；另有 `busy_scope`（目前被占用的檔案集合，為所有有效認領的 `scope.files` 聯集）。
3. 更新由 workflow 觸發；內容無變化不寫入（仿 `ops/doctor_issue.py`）；單一 `concurrency` 群組序列化寫入，避免與 IM 同時改 label 來回覆蓋。

看板只是 GitHub 事實的投影，不是第二份真相：與 Issue label／認領留言不一致時，以 Issue 與留言為準，下一個同步週期修正看板。停用 `issue-sync` workflow 即停止所有自動寫入；認領留言與 label 是惰性資料，不影響既有 `delivery.py` 流程。

## 本機 registry 與 GitHub 的關係

- registry（`ops/worktree_registry.py`）是**執行層**真相：worktree 所有權、檔案 overlap、hand-back。
- GitHub 認領是**公開層**真相：誰在做哪張 Issue、何時到期。
- 認領操作在同一指令內先檢查 registry 的 Scope overlap，再寫 GitHub，最後讀回；失敗則不留半成品。
- 兩者分歧由 `inspect`／`issue-inventory` 偵測並輸出：`claim_without_registry`（GitHub 有認領、本機無 lane）與 `registry_without_claim`（本機有 lane、GitHub 沒認領）。每筆分歧都必須有說明或被修復，不可靜默容忍。
- 補認領只在能從 PR receipt 取得 `lane_id`／`branch`／Scope 時進行；其餘不編造，標 `needs-triage`。

## PR 與 Issue 連結

PR 內文有 `## Issues` 區段，列出：

- `Closes #N`：此 PR 完全解決 N；合併即由 GitHub 自動關閉（D6）。
- `Refs #N`：此 PR 只解決一部分；合併後 Issue 回到 `ready-for-solver`，由 IM 視情況釋放認領。

整合 PR 一次吃多個 Issue 時逐一明確列出，不使用範圍簡寫。Issue 清單來源是 lane 的 registry `external_ids`，或 `delivery.py publish` 的明確 `--closes N`／`--refs M`。`validate-pr-body` 與 `pr-readiness` 必須接受這個區段，且不得破壞「PR body 恰好一份 hand-back receipt」的既有驗證。直接指派（沒有 Issue）的 PR 可留空此區段。

`close-terminal-issues` 是安全網（D7）：只關閉有完成級證據（merged PR、merged lane）的「做完仍開著」Issue，且先 dry-run 報告；主要關閉手段是 `Closes #N`。手動關閉任何 Issue 都要留言 `Resolved by <PR/commit>`，沒有 commit 證據不關。

## 非目標

- 不使用 assignee、GitHub Project、milestone 當作狀態或優先級來源（D4）。
- 不把 Issue、Project、PR 狀態複製進 repo 文件或本機 registry；registry 不存工作項目生命週期。
- 不讓 Worker／Issue Solver 寫 GitHub；不讓自動化決定合併、上線或釋放過期認領。
