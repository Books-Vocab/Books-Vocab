<!-- doc-meta
tier: reference
authority: SoT
update_trigger: delivery-model-changed
scope:
  - CLAUDE.md
  - .github/
  - .claude/agents/
  - .claude/skills/
  - docs/reference/agent_context.md
  - docs/runbook/system.md
  - docs/sop/review_discipline.md
  - docs/sop/doc_sync.md
  - docs/sop/release.md
  - ops/context_plane.json
  - ops/context_route.py
  - ops/task_registry.py
  - ops/lib/streaming_command.py
  - ops/worktree_registry.py
  - ops/worktree_orchestrate.py
verified_against: 0244387e5c096d75a0a67804503c030d9ffc9404
-->
# GitHub-native Delivery Model

這是 KG 交付模型的唯一權威文件。它定義工作如何進入系統、如何收斂到 PR，以及本機工具不能承擔什麼；它不記錄某一張 Issue、某一個 PR 或某一輪工作的即時狀態。

## 第一性原理

GitHub 是整套交付控制面：

| 交付問題 | 唯一 owner |
|---|---|
| 要不要做、為什麼做、完成判準 | GitHub Issue（可選） |
| 優先順序、視圖、里程碑 | GitHub Project |
| 一次實作的隔離空間 | branch + local worktree |
| 變更、討論、review、驗證、合併請求 | Pull Request |
| 自動測試與 required checks | GitHub Actions |
| 合併後的產品真相 | GitHub `main` |
| 合併後的正式發布與生產安全 | Release／Deploy SOP |

最重要的規則是：

> Issue 是規劃與派工工具，不是程式碼交付工具；PR 是所有程式碼變更的共同交付入口。

所有 code change 都要走：

```text
branch → commit → PR → Actions + CR + DS → CM merge → main → release/deploy（若有明確意圖）
```

`main` 不接受直接寫入。merge 不是 production approval；release、deploy、health gate、rollback 仍由各自安全邊界控制。

## 角色

角色是責任邊界，不是本機組織階層，也不是第二套權限系統。GitHub repository rules、branch protection、Actions environment approval、production wrapper 與帳號權限才是真正的授權來源。

| 角色 | 責任 | 不負責 |
|---|---|---|
| **CM — Codebase Manager** | 管理 `main` 與 codebase 狀態；依優先順序協調、審核並合併合格 PR；確認 Actions、CR、DS、文件與安全檢查；管理版本、release、deploy 與必要 rollback | 親自實作每個工作；維護本地 backlog |
| **IM — Issues Manager** | 了解 codebase 現況；管理 GitHub Issues；判斷哪些問題值得進 Issue 流程；安排優先順序與派工；可直接指派 Worker 或交給 Issue Solver | 合併 code；維護本地 Issue／Project 狀態 |
| **Worker** | 接受 User／IM 的直接指派；在 branch/worktree 修改程式碼與測試；提交 PR | 不必建立、認領或關閉 Issue；不直接寫 `main` |
| **Issue Solver** | 執行已進入 GitHub Issues 的工作；從 Issue 取得目標與 acceptance，在 branch/worktree 修改程式碼與測試，提交 PR | 不在本機複製 Issue lifecycle；不直接合併 code |
| **CR — Code Reviewer** | 對所有 PR 做獨立的正確性、測試、回歸、架構與安全審查；把結論留在 PR | 管理 Issue；擁有 merge 權限；建立本地 review cycle |
| **DS — Docs Steward** | 對所有 PR 判斷文件 impact；維護 registry、metadata、SoT domain SOP／reference，執行 docs lint | 建立本地工作項目資料庫；複製 PR lifecycle |

Release operator 是 CM 所管理的執行能力，不是另一套產品管理層：它只能依 release SOP 與明確批准執行發布、部署或 rollback。

現有 `ops/context_route.py` 的 machine identity 保持穩定，以免破壞既有入口：`manager` 承載 CM／IM 的 bounded context、`contributor` 承載 Worker／Issue Solver 的執行 context、`reviewer` 對應 CR、`docs-steward` 對應 DS、`release-operator` 對應 release execution。這是相容性映射，不是新增一套角色模型。

## 兩條正式工作路徑

### A. 直接指派

適用於 User 或 IM 已經清楚知道要改什麼的明確工作，例如小型修復、界定清楚的重構或直接交辦。它不需要 Issue，也不進入 Issue 排序。

```text
User / IM
    ↓ direct assignment
Worker
    ↓
branch + worktree → code + tests → PR
    ↓
Actions + CR + DS → CM merge → main → release/deploy（若需要）
```

PR 仍必須寫清楚指派內容、修改範圍、驗收方式、測試證據、文件影響與 production／rollback 風險。

### B. Issue 流程

適用於需要討論、排序、拆解、Project／milestone 視圖或未來追蹤的工作。

```text
IM
    ↓
GitHub Issue → Project priority / triage
    ↓
Issue Solver claim
    ↓
branch + worktree → code + tests → PR
    ↓
Actions + CR + DS → CM merge → main → release/deploy（若需要）
```

Issue 的 acceptance 是需求真相；PR 的 diff、conversation、checks、review 與驗證證據是實作真相。Issue 關聯可由 PR 自動 close，但不把 Issue 狀態再寫入 repo。

## PR 收斂規則

Worker 與 Issue Solver 的實作能力、測試要求與 PR 標準相同，差別只有工作的進入方式。每個 PR 應讓人能回答：

- 這是 direct assignment 還是 Issue work；若有 Issue，關聯哪一張。
- 改了什麼、為什麼改、範圍與非目標是什麼。
- 哪些測試／Actions 實際通過，命令、exit status 與 exact HEAD 是什麼。
- 是否影響文件、資料、CloudKit、migration、release、deploy 或 rollback。
- CR 與 DS 是否完成各自檢查；未完成時不得宣稱 ready。

CM 只在 PR 的 required checks、review、文件影響與安全條件滿足後合併。PR merge 後才進入 release／deploy SOP；任何外部帳號批准、production 寫入或 rollback 仍是獨立的明確動作。

## 本機 coordinator 的窄責任

本機 coordinator 是多 worktree 的執行環境安全工具，不是產品管理系統：

- 保留 worktree owner、branch/path、structured Scope、檔案 overlap、thread identity。
- 保留本地測試、exact HEAD、log／artifact 與 typed hand-back evidence。
- 幫助建立、接管、驗證、交回或安全清理工作樹。

它不負責：

- 建立、排序、認領或關閉 GitHub Issue／Project。
- 管理 PR lifecycle、review cycle、merge queue 或 merge permission。
- 建立本地 backlog、Ticket Factory、Issue lifecycle、Project／board 或批次整合狀態。
- 把 worktree 或 agent 當成產品工作項目。
- 取代 GitHub Actions、CM merge、release、deploy、production approval 或 rollback。

Scope 只回答「本機哪個工作樹可改哪些檔案」；Issue acceptance、PR review 與 production approval 各自留在 GitHub 或 domain SOP。local hand-back 是執行證據，不是第二個交付狀態機。

長任務的本機安全帳本另由 `ops/task_registry.py` 與 `ops/lib/streaming_command.py` 負責。它只記錄 process identity、process group、heartbeat、log path 與 terminal outcome，用來避免誤殺或靜默等待本機程序；它不是 Issue、Project、PR、backlog 或任何產品工作項目的狀態。

## 遷移後的判斷準則

保留真正產品程式碼與測試、backend／iOS 測試入口、GitHub Actions、PR template／required checks、deployment safety wrapper、生產批准／health gate／rollback、CloudKit／資料庫／域名／App Store／TestFlight SOP、docs registry／impact／lint、薄型本地 coordinator，以及長任務 process-safety ledger。凡是只為模擬 GitHub Issue、Project、PR、review、merge 或狀態追蹤而存在的本地描述、資料庫、看板與流程，都不屬於這個模型。
