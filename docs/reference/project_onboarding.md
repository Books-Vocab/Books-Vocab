<!-- doc-meta
tier: reference
authority: SoT
update_trigger: agent-routing-changed
scope:
  - CLAUDE.md
  - docs/reference/delivery_model.md
  - docs/reference/agent_context.md
  - docs/registry.yml
  - ops/context_plane.json
  - ops/context_route.py
  - ops/skill_route.py
  - ops/agent_onboard.py
  - .claude/agents/
  - .claude/skills/
verified_against: 8ec4780950c73b6006649c5c08e69c05962abfc1
-->

# KG Agent Project Onboarding

這是所有代理的共同入場文件。它只回答「KG 是什麼、誰負責什麼、接下來怎麼載入上下文」；不記錄 Issue、PR、branch 或本地工作項目的狀態。

## 專案概覽

KG 是 Knowledge Graph 英語學習產品：

- `ios/`：SwiftUI BooksAndVocab app、iOS unit/UI/device 驗證。
- `backend/`：FastAPI、資料與服務 API、backend 測試與品質檢查。
- `lab/`：podcast、LLM evaluation 與研究工具。
- `ops/`：測試入口、GitHub Actions 對應的 gate、worktree 協調、release/deploy safety wrapper。
- `docs/`：產品技術細節、domain SOP、政策與文件路由；不是工作項目資料庫。

GitHub 是交付控制面：Issue／Project 管規劃與排序，branch／worktree 隔離實作，PR 承載變更、review 與驗證，Actions 執行 required checks，`main` 是合併後真相，release/deploy 依安全 SOP 執行。本地 coordinator 只處理多 worktree 的 ownership、Scope、本地驗證與交接，不複製 GitHub 的工作狀態。

## Skill 與 docs 的分工

技能不是技術百科，而是「何時載入、先做什麼、什麼不能做、交付什麼證據」的短流程。技術命令、schema、參數、host、API 與故障細節放在 `docs/registry.yml` 指向的 SoT。

目前 skill catalog 分成四類：

- `kg-router`：唯一 bootstrap kernel，負責 onboarding 與 route，不做產品操作。
- control-plane workflow：GitHub 協調、worktree delivery、CR review、DS docs、release command。
- domain specialist：只在明確 intent 觸發時載入，例如 app debug、billing、data analysis、iOS Simulator、production ops、podcast。
- closure：`kg-receipt` 只在需要 hand-back／PR 收尾時載入。

每次只選一個 primary skill；required dependency 必須由 catalog 明確聲明，forbidden skill 不得同時載入。沒有 assignment evidence 時連 specialist 與 domain docs 都不讀。若指定 `specialist-intent`，它必須經 identity／intent／entry 白名單驗證，並取代 generic high-level route，不能由 agent 自行拼接多條 specialist。若 skill 只有長篇命令清單、沒有獨立觸發條件／邊界／輸出證據，應把內容移到 docs、合併或刪除；若同一 skill 同時涵蓋唯讀監控與外部副作用，則拆成不同 route（podcast 即採 pipeline、monitor、publish 三路）。

## 標準身份與邊界

| canonical identity | 主要責任 | 明確不負責 |
|---|---|---|
| CM | codebase、PR 收斂、merge 順序、release/deploy 邊界 | 親自實作所有工作、本地 backlog、未批准 production 寫入 |
| IM | GitHub Issue 收件、排序、拆解與派工 | merge code、本地 Issue lifecycle、PR review 結論 |
| Worker | 接受 User／IM 直接指派，完成 branch/worktree、程式碼、測試與 PR | Issue lifecycle、Project priority、merge、release/deploy |
| Issue Solver | 執行已進入 GitHub Issue 的工作並提交 PR | 建立第二套 backlog、Issue lifecycle、merge、release/deploy |
| CR | 審查 PR diff 的正確性、測試、回歸、架構與安全 | 修改 caller worktree、merge、release |
| DS | 判斷文件影響、維護 registry／SoT、執行 docs lint | 建立文件狀態庫、PR lifecycle、merge |
| Release operator | 依批准與 SOP 執行 release、deploy、health gate、rollback | 自行批准 production、繞過 safety wrapper |

完整角色邊界以 [`delivery_model.md`](delivery_model.md) 為準。Onboarding、assignment
與報告一律使用 canonical identity；route manifest 的內部 key 只屬執行層實作，
不是角色、權限或工作狀態，代理不需要記住它們。

## 強制載入順序

每個代理都必須按以下順序啟動，不能跳到 specialist skill 或 domain 文件：

1. **Project**：讀本文件，建立整個 KG 的共同概覽。
2. **Identity**：確認 canonical identity、工作入口與不負責的事情。
3. **Assignment**：確認 GitHub Issue／PR 或 direct assignment、acceptance、branch/worktree Scope。
4. **Skill**：由 onboarding kernel 選出唯一 primary skill，再讀 primary 與合法 dependencies；domain specialist 不預載，依 task intent 精準選取。
5. **Domain**：只讀這次工作需要的技術文件，完成驗證並以 PR／必要 SOP 收斂。

標準入口：

```bash
./ops/agent_onboard.py \
  --identity '<CM|IM|Worker|Issue Solver|CR|DS|Release operator>' \
  --intent '<delivery|review|docs|release|backend|ios>' \
  --entry '<coordination|merge|direct-assignment|issue|pr-review|release>' \
  --specialist-intent '<optional identity-scoped specialist intent>' \
  --evidence '<JSON object containing the required assignment evidence>' \
  --json
```

`--evidence` 必須逐項提供該 identity／entry 要求的外部證據；缺少時回傳 `status=awaiting-assignment` 並停在 assignment，不會載入 skill 或 domain 文件。只有 `status=ready` 才能繼續；不可自行猜測身份、Scope 或授權。

`--specialist-intent` 是可選但受限的精準路由，例如 bug、docs-impact、production-status 或某個 domain pipeline；可用值由 `ops/context_plane.json` 綁定到 identity／intent／entry，並由 skill catalog 驗證。Simulator 只是其中一個 `ios` specialist 範例，不是 onboarding 的特殊中心。

同一個高階 intent 可能因身份與 entry 選到不同 primary skill：CM／IM 的協調入口走 `github-coordination`，Worker／Issue Solver 的實作入口走 `worktree-flow`，iOS 驗證路徑則是 `ios-simulator-verification` 加上 required `worktree-flow` dependency，CR／DS／Release operator 走各自的 review、docs 或 release route。這個 identity-specific mapping 由 `ops/context_plane.json` 驗證，不能靠代理自行把 `delivery` 解讀成某個角色。

## 不可違反的共同規則

- 不直接寫入 `main`；程式碼變更必須經 branch、PR、Actions 與 review 收斂。
- 不在 repo 內建立本地 backlog、Issue／Project／PR lifecycle 或 merge queue。
- route 是上下文與 skill 載入決策，不是 merge、production 或帳號授權。
- 不把 stale seal、WARN、timeout、baseline failure 或缺少 evidence 報成 PASS。
- production 只走 `ops/release.sh`、`ops/devops_kg_safe.sh` 與對應批准／rollback SOP。
- docs 記錄技術細節與操作真相；skill 規範代理如何載入、協調與交接；兩者不互相複製。
