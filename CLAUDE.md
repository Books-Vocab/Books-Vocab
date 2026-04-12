# KG Workspace Agent Guide

## Identity

| key | value |
|-----|-------|
| project key | `kg` |
| local root | `.` |
| backend | `backend` |
| ios | `ios` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |

## 對話啟動流程（每次對話強制執行）

1. **Deep Scan** — 立即 `Skill("deep-scan")`，dispatch 5-7 個 opus agent 平行掃描全專案。不等結果，繼續下一步。
2. **掃描 skill 觸發條件** — 對照使用者的第一句話，凡符合已註冊 skill 的觸發描述，立即載入。「不確定是否符合」= 符合。
3. **確認 scope** — 本任務是否 project-scoped。若涉及跨專案，切回 repo root 遵循根 `CLAUDE.md`。
4. **匯總 Deep Scan 結果** — agent 完成後呈現問題清單，供使用者參考或挑選處理。

## Skill 系統（6 個 skill）

| Skill | 觸發 | 用途 |
|-------|------|------|
| `deep-scan` | 每次對話自動 + `/deep-scan` | 全專案平行掃描 |
| `design` | 做 feature / 加功能 / 改行為 | 想法 → spec → plan |
| `execute` | 有 plan 要執行 | plan → worktree → opus agents → review → PR |
| `app-debug` | bug / test failure / 異常行為 | 根因調查 + 平行假說驗證 |
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
| `data-analysis` | 分析用戶 / 圖譜 / 連結 / 額度 / 嵌入 / 閾值調優 | 深度資料分析 |
| `cleanup` | `/cleanup` 或「收尾」 | merge PRs → update docs → git cleanup → test → deploy |

### Skill 規則

- 觸發條件符合就**立即** `Skill()` 調用，不問使用者。
- 多個同時符合則全部載入。
- **所有 agent 一律 `model: "opus"`。無例外。**

## 鐵律（全域規則，不可繞過）

1. **TDD** — 先寫 failing test，確認紅，寫最小實作，確認綠。不可跳過。
2. **驗證先於宣稱** — 說「完成」「通過」「修好」之前，必須有當下的驗證輸出作為證據。「should work」= 謊言。
3. **根因先於修復** — 遇到 bug 必須確認根因才動手改。不可看到錯就補 patch。
4. **逐項 review，不批次** — 每完成一個 fix/feature 立即 dispatch review agent 審核，發現問題當場修，確認 PASS 後才進下一個。禁止「全部寫完再一起 review」。此規則適用所有程式碼修改，無論是否走 execute skill。

## Git

- Monorepo：`.git` 涵蓋 iOS app、backend API、ops/docs
- Commit prefix：`ios:` / `api:` / `ops:` / `docs:`
- **Worktree 強制**：程式碼修改一律在隔離 worktree 中進行 → commit → 開 PR。禁止直接在 main 上改，除非使用者明確指示。

## iOS 編譯（強制）

唯一合法方式（從 repo root 或任何 worktree）：

```bash
./ops/ios_build.sh          # build only (Release, ~15s incremental)
./ops/ios_test.sh           # run ALL unit tests
./ops/ios_test.sh -g "foo"  # run tests matching pattern "foo"
./ops/ios_test.sh testName  # run specific test by method name
```

兩者共用 `shlock` 排隊鎖 + DerivedData，多 worktree 可同時呼叫。

- Exit 0 → 成功，停止
- Exit 非 0 → 讀錯誤上下文 ±20 行，修正後重跑
- **禁止**：直接 `xcodebuild`、改機型、拿掉 `-quiet`、加 `2>&1 | grep`、加 `cd ios &&`

## iOS UI Design System（強制）

**觸發**：任何涉及 iOS View / UI 的新增或修改。

### 動手前必做
1. 讀 `docs/references/ui_component_pattern_inventory.md` — 現有元件與 pattern
2. 讀 `docs/references/ui_review_checklist.md` — 自查清單

### Token 禁令（零容忍）

| 禁止 | 替代 |
|------|------|
| raw color（`Color.red`、`Color(red:...)`、`#colorLiteral`）| `AppTheme` / `VocabSkin.Palette` / `AppColors` |
| raw font（`.font(.system(...))`、`Font.custom(...)`）| `AppFonts` / `VocabSkin.Typography` |
| raw spacing magic number | `AppShellMetrics` / `AppMetrics` / `VocabSkin.Spacing` |
| raw animation（`.spring(...)`、`.easeOut(...)`、`.default`）| `AppMotion` token |
| raw transition | `AppTransition` token |

### 元件復用
- 新增前查 inventory，復用優先序：現成 Pattern → Component → 擴充 Token → 新建
- 新建元件放入對應層級（App Shell / VocabSkin / Reader / Settings）

### 狀態覆蓋
- 每個新畫面/元件必須覆蓋：loading、empty、error、success/completed
- 參照 `docs/references/ui_state_matrix.md`

### Motion 契約
- 所有動畫走 `AppMotion` 語意 token（`Models/AppMetrics.swift`）
- 新動畫先在 `AppMotion` 新增 token，再引用
- 同類互動跨 feature 共用同一 token

### 環境注入
- Theme：`@Environment(\.appTheme)`
- VocabSkin：`@Environment(\.vocabSkin)`
- 不可硬建 instance

### 完工自查
- 對照 `docs/references/ui_review_checklist.md` 五大項
- 關鍵畫面須有 `#Preview`，不依賴登入/後端

## Implemented Product Surface

動手前先對照，確認不重複建造。

- **iOS**（`ios/BooksBrowser`）：auth flows（Apple/Google SSO）、bookshelf + reader（EPUB/TXT/MD/PDF multi-format import）、translation/explanation（context sentence extraction）、vocabulary capture/list/detail/sync/graph views、hide/unhide links + bilateral optimistic sync、toast notification system（capsule toast + sheet overlay）、graph thumbnail + health blob、today review、stats overview、settings + account deletion、onboarding empty-state login entry points、app-intent/background sync、preview matrix、**macOS multiplatform (macOS 15.0+)**、notebook robustness（`resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense）、**notebook bookshelf**（LazyVGrid card grid + NotebookCard + cover system: 12-color palette + 6 SwiftUI Canvas patterns + PhotosPicker custom image + ProgressCapsule + VocabReviewBanner separated due/unlearned + pending tab → SyncView integration + export dual-entry）
- **Backend**（`backend/src/kg`）：auth/user identity（Apple/Google + web auth + cookie admin session）、user config/account lifecycle、vocabulary/graph-link APIs（hide/unhide/blocked pairs）、translate/explain/pipeline、card/graph/embedding/difficulty/enrichment/Mochi、multi-format import parsing、query path perf（incremental sync/zipf cache/filter-before-sort）、write path perf（batch ops/N+1 elimination）、static pages、system observability（`/api/system/info` + VERSION tracking + deploy.log）、pipeline telemetry（`pipeline_log.db` — per-run/step timing + status + items，admin UI summary stats + stacked bar chart）、pipeline lock-queue（concurrent triggers queue via `async with lock` instead of silent-skip）、one-shot judge（pending_judge + selective prompt + degree cap + batch judge 86% token savings）、judge_log（complete decision tracking + acceptance rate）、translate_log（structured LLM call logging + cross-user cache）
- **Chrome Extension**（`chrome-extension/`）：side panel vocab lookup、閱讀選詞翻譯、auth token 整合、woff2 字型
- **Admin**：dashboard (`/admin` — judge acceptance rate)、user detail page (`/admin/user/<uid>` — two-column layout：帳戶/訂閱/grant/額度/token + graph density chart + graph playback + pipeline waterfall + translate_log viewer)、password login (`/admin/login`)、logs/stats APIs (`/api/admin/*`)、test-matrix (`/admin/tests`)、in-memory log capture
- **Tests**（`backend/tests`）：API contract、robustness、renderer、admin/test-matrix、auth provider tests（Apple/Google）、text_utils/enrich modules、pipeline lock-queue concurrency tests
- **Tests**（`ios/BooksBrowserTests`）：vocabulary entry lifecycle、bilateral link mutation、reader bridge planner、session persistence、notebook orphan defense（resolveNotebookId 7 + sanitizeOutbox 8 + triggerPipelinesIsolated 3 = 18 tests）
- **Ops**：safe wrapper、smart deploy（auto fast/full path + rsync --delete stale files）、ops-cli（container 內查詢工具，db-query 不需引號）、container-script（本地腳本上傳執行）、ops_analyze.py（one-command deep graph analysis levels 1-6）、preflight/backup/restart/status/logs（`KG_LOG_TZ` 時區轉換）/migration workflows、system observability（version tracking + deploy log）、ios_test.sh（`-g` pattern grep + clean output）

## Reference Docs（按需讀取）

| 主題 | 路徑 |
|------|------|
| backend dev | `docs/dev/backend-dev.md` |
| deploy / env / migration | `docs/dev/deploy.md` |
| incidents / 502 / caddy | `docs/dev/debug.md` |
| iOS build / xcode | `docs/dev/ios-dev.md` |
| UI design | `docs/dev/ui-design.md` |
| architecture / sync | `docs/dev/architecture.md` |
| UI component inventory | `docs/references/ui_component_pattern_inventory.md` |
| UI review checklist | `docs/references/ui_review_checklist.md` |
| UI state matrix | `docs/references/ui_state_matrix.md` |

## Doc Freshness 規則

- 修改任何有 `doc-meta` 的文件時，在同一 commit 前執行 `git rev-parse --short HEAD`，將結果填入 `verified_against`
- 讀到 `tier: snapshot` 的文件時，執行 `ops/gen_ios_baseline.sh` 再生，而非手動編輯
- 任何涉及 iOS 大規模重構的 PR 合併後，執行 `ops/gen_ios_baseline.sh` 更新快照
