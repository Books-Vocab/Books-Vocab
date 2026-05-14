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

1. **Deep Scan（inline dispatch）** — 立即 inline dispatch 5-7 個 opus general-purpose agent 平行掃描全專案（無對應 skill）。不等結果，繼續下一步。
2. **掃描 skill 觸發條件** — 對照使用者的第一句話，凡符合已註冊 skill 的觸發描述，立即載入。「不確定是否符合」= 符合。
3. **確認 scope** — 本任務是否 project-scoped。若涉及跨專案，切回 repo root 遵循根 `CLAUDE.md`。
4. **匯總 Deep Scan 結果** — agent 完成後呈現問題清單，供使用者參考或挑選處理。

## Skill 系統（7 個 skill）

| Skill | 觸發 | 用途 |
|-------|------|------|
| `design` | 做 feature / 加功能 / 改行為 | 想法 → spec → plan |
| `execute` | 有 plan 要執行 | plan → worktree → opus agents → review → PR |
| `app-debug` | bug / test failure / 異常行為 | 根因調查 + 平行假說驗證 |
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
| `data-analysis` | 分析用戶 / 圖譜 / 連結 / 額度 / 嵌入 / 閾值調優 | 深度資料分析 |
| `cleanup` | `/cleanup` 或「收尾」 | merge PRs → update docs → git cleanup → test → deploy |
| `podcast` | EPUB → podcast pipeline | 深度分析 → 規劃 → 腳本 → TTS → 字幕 |

### Skill 規則

- 觸發條件符合就**立即** `Skill()` 調用，不問使用者。
- 多個同時符合則全部載入。
- **所有 agent 一律 `model: "opus"`。無例外。**

## 鐵律（全域規則，不可繞過）

1. **TDD** — 先寫 failing test，確認紅，寫最小實作，確認綠。不可跳過。
2. **驗證先於宣稱** — 說「完成」「通過」「修好」之前，必須有當下的驗證輸出作為證據。「should work」= 謊言。
3. **根因先於修復** — 遇到 bug 必須確認根因才動手改。不可看到錯就補 patch。
4. **逐項 review，不批次** — 每完成一個 fix/feature 立即 dispatch review agent 審核，發現問題當場修，確認 PASS 後才進下一個。禁止「全部寫完再一起 review」。此規則適用所有程式碼修改，無論是否走 execute skill。
5. **不主動跑 iOS test** — 除非使用者明確說「跑測試」，否則禁止主動執行 `ios_test.sh`。**無例外，包含 worktree 中的 subagent。** `ios_build.sh` 和 backend `pytest` 不受此限。
6. **不寫 memory** — 禁止寫入 `.claude/projects/*/memory/`。所有持久化規則寫在 `CLAUDE.md` 或 `docs/`。
7. **長時操作一律背景執行** — 任何 Agent 調用必須帶 `run_in_background: true`；任何耗時 Bash 也必須帶 `run_in_background: true`（含 `ios_build.sh`、`ios_test.sh`、backend `pytest`、deploy/rsync、長下載、長 install）。**主線不阻塞**，完成由 notification 觸發。**無例外**。

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

- **iOS**（`ios/BooksBrowser`）：auth flows（Apple/Google SSO）、bookshelf + reader（EPUB/TXT/MD/PDF multi-format import + batch select + classified error diagnosis + import progress callback）、translation/explanation（context sentence extraction）、vocabulary capture/list/detail/sync/graph views、hide/unhide links + bilateral optimistic sync、toast notification system（capsule toast + sheet overlay）、graph thumbnail + health blob、today review（4-state phase matrix + PostExampleMetrics）、stats overview（StatsPresenter full state matrix）、settings + account deletion（paywall Free/Pro 對照 + 安全確認 + Pro badge + CSV export via VocabularyExporter）、onboarding empty-state login entry points + Welcome 3-step walkthrough（sticky login CTA）、AppStartupRecoveryView 三層 recovery、app-intent/background sync、preview matrix、**macOS multiplatform (macOS 15.0+)**（Cmd+N / Cmd+F shortcuts）、notebook robustness（`resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense）、**notebook bookshelf**（LazyVGrid card grid + NotebookCard + cover system: 12-color palette + 6 SwiftUI Canvas patterns + PhotosPicker custom image + ProgressCapsule + VocabReviewBanner separated due/unlearned + pending tab → SyncView integration + export dual-entry + sort menu + empty-state CTA + NotebookCardActions reusable context menu）、podcast player（audio + sentence-level SRT highlight + reader-parity 翻譯 via `VocabularyContextProtocol` + phrase 長按整句 + auto-pause-on-lookup + subtitle size S/M/L/XL/XXL + series 追蹤 toggle + 已追蹤浮上書庫頂端 + per-user progress sync to backend）、auto-sync（60s cooldown + toggle onChange 觸發）、notebook cover photo 編輯（photoError + originalCoverImagePath 延遲刪 + 取消還原）、graph empty state（區分「無單字」vs「有單字無連結」）、vocab list 效能 + 空態 CTA、reader error retry（publication / PDF / translation / explain）、word detail share button（plain text via ShareLink）、design system v2（AppCompactActionButtonStyle + AppOfflineBanner + AppSkeleton primitives；AppSpacing/Radius/Elevation z0-z4/Layout/Motion emphasizedDecelerate-Accelerate-subtleBreath + TapFeedback token；brand hero indigo + state bgs + display1/2 serif；paper-tone shadow 0.18；raw transitions 已全數消除）、state matrix error states（notebook list / podcast list / bookshelf / translation settings / today review failure feedback）、Sentry crash reporting（opt-in via Info.plist SentryDSN + auth scrubbing + frame locals dropped + breadcrumb across services + KGService iOS HTTP breadcrumb）
- **Backend**（`backend/src/kg`）：auth/user identity（Apple/Google + web auth + cookie admin session + provider switch / session invalidation matrix + google_auth case-insensitive bool normalize）、user config/account lifecycle、vocabulary/graph-link APIs（hide/unhide/blocked pairs）、translate/explain/pipeline、card/graph/embedding/difficulty/enrichment、multi-format import parsing、query path perf（incremental sync/zipf cache/filter-before-sort）、write path perf（batch ops/N+1 elimination）、static pages、system observability（`/api/system/info` + VERSION tracking + deploy.log + site-wide observability panel + observability_alerts wired to /system/info）、pipeline telemetry（`pipeline_log.db` — per-run/step timing + status + items，admin UI summary stats + stacked bar chart）、pipeline lock-queue（concurrent triggers queue via `async with lock` + catch-all defense for user-deleted-mid-queue KeyError）、pipeline degree_cap audit metric fix（UPDATE not INSERT，4 caller queries exclude degree_cap）、one-shot judge（pending_judge + selective prompt + degree cap + batch judge 86% token savings + update_to_rejected helper）、judge_log（complete decision tracking + acceptance rate）、translate_log（structured LLM call logging + cross-user cache + precise hit counter + admin search/timeline）、translate singleflight dedup（120s follower timeout + N>2 loop semantics）、translate cache（env-tunable TTL `TRANSLATE_CACHE_TTL_DAYS` + model-key column migration）、log_retention env vars（`JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS` + pruners + CLI + admin trigger endpoint + flat aliases）、podcast API（`/api/podcasts*` 認證端點 + `/api/podcast-media/` StaticFiles 無條件掛載 + Range/206 支援 + `ep_num` Path 驗證 + per-user podcast progress LWW SQLite store）、EmbeddingStore env wiring（`EMBEDDING_MODEL` / `EMBEDDING_DIM` 透過 factory 傳入 + dim mismatch guard + cache key 含 model+dim + `_load` shape verification 防 silent corruption）、`cards.batch_touch(notebook_id=...)` scope filter、orphan_scan cross-DB consistency scanner + admin endpoint、backend hardening（podcast ACL / rate-limit / embedding / sqlite WAL）、cryptography 48 + starlette 1.0 + fastapi 0.136 升級、Sentry SDK 整合（`sentry_init.py` opt-in via SENTRY_DSN env + auth header/cookie scrubbing + request_id tag in scope + release tag + per-path traces sampler + uid scope + `/api/system/info` 暴露狀態 + admin smoke ping endpoint `POST /api/admin/sentry/ping`）
- **Chrome Extension**（`chrome-extension/`）：side panel vocab lookup、閱讀選詞翻譯、auth token 整合、woff2 字型、side panel error state taxonomy + settings entry + AbortError safety
- **Admin**：dashboard (`/admin` — judge acceptance rate + 30-day error/token/DAU trend sparklines + Sentry Ping button + site-wide observability panel)、user detail page (`/admin/user/<uid>` — two-column：帳戶/訂閱/grant/額度/token + AI cost summary（judge/translate/pipeline/other）+ graph density chart + graph playback + pipeline waterfall + translate_log viewer + 24h activity timeline)、`/api/admin/users/search`（uid / email / displayName）、admin grant/revoke audit log、password login (`/admin/login`)、logs/stats APIs (`/api/admin/*`)、test-matrix (`/admin/tests`)、in-memory log capture
- **Tests**（`backend/tests`）：API contract、robustness、admin/test-matrix、auth provider（Apple/Google + provider switch + malformed claims + expired + clock skew + takeover）、web_auth security（state mismatch + cookie tampering）、text_utils/enrich（malformed/atomicity/token accounting）、log_retention（env + empty + admin trigger）、token_tracker concurrent write isolation、cards incremental sync（since/tombstone/pagination edge）、embedding（store dim mismatch + cache key + factory env + load shape）、judge edges（batch partial failure + degree cap + token savings）、rate_limit（GC + size cap + concurrent）、difficulty（zipf common/rare/unknown）、graph bilateral hide/unhide + blocked pair persistence、billing edges（refund/duplicate/grace/reconcile）、pipeline（concurrency saturation + user-deleted-mid-queue + cascading failure + quota exhaustion + step rollback + log lifecycle）、retry（jitter + cancellation + nested edge）、multi-format parser（malformed/encoding/large-file）、translate cache（TTL + cross-user + model-key + cooldown + dedup）、quota tier transition + grant revoke、sync_merge three-end concurrent + tombstone-vs-restore、migration scripts（idempotent + rollback safety）、observability_alerts isolation + boundary、admin user_activity（empty/mixed/pagination）、admin cost summary、admin trends、Sentry init scrubbing
- **Tests**（`ios/BooksBrowserTests`）：vocabulary entry lifecycle、bilateral link mutation、reader bridge planner、session persistence、notebook orphan defense（resolveNotebookId + sanitizeOutbox + triggerPipelinesIsolated）、PodcastVocabContext + ReaderTranslationHandler + ReaderVocabularyCapture、QuotaStore + KGError/RetryPolicy + TodayReview PostExampleMetrics、state matrix error states（notebook / podcast / bookshelf / translation settings / today review）
- **Claude Code Gateway**（`lab/claude-code-gateway/`，.gitignore，third-party）：Claude Code CLI → OpenAI-compatible `/v1/chat/completions`，公網 `https://wordnexus.lol/claude/v1`（Caddy `/claude/*` → port 8090），Bearer `CCG_API_TOKEN`，模型別名 `sonnet`/`opus`/`haiku`，現行呼叫點 `lab/podcast/pipeline.py`（PoC `lab/archive/podcast_architect_poc.py`），詳見 `docs/ops/claude-code-gateway.md`
- **Ops**：safe wrapper、smart deploy（auto fast/full path + rsync --delete stale files）、ops-cli（container 內查詢工具，db-query 不需引號）、container-script（本地腳本上傳執行）、ops_analyze.py（one-command deep graph analysis levels 1-6）、preflight/backup/restart/status/logs（`KG_LOG_TZ` 時區轉換）/migration workflows、system observability（version tracking + deploy log）、ios_test.sh（`-g` pattern grep + clean output）、podcast_upload.sh（series_id regex + createdAt idempotent + rsync `--partial-dir --delay-updates` 原子 + 遠端 index.json flock）、post-deploy smoke verify（system/info + health + sentry test event）、backup_verify.sh（restore drill + integrity check）、chrome extension release bundle script + tests、pytest pinned in `pyproject.toml [dependency-groups].dev`（修 backend venv 無 pytest）

## Reference Docs（按需讀取）

| 主題 | 路徑 |
|------|------|
| backend dev | `docs/dev/backend-dev.md` |
| deploy / env / migration | `docs/dev/deploy.md` |
| Claude Code Gateway | `docs/ops/claude-code-gateway.md` |
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
