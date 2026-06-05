<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/
  - backend/
  - chrome-extension/
  - ops/
  - lab/
verified_against: 25cedfb8
-->
# Implemented Product Surface

動手前對照,確認不重複建造。功能上線後在此追加 bullet,而非寫在 `CLAUDE.md`。

---

## iOS (`ios/BooksBrowser`)

- **Auth flows**: Apple/Google SSO
- **Bookshelf + reader**: EPUB/TXT/MD/PDF multi-format import + batch select + classified error diagnosis + import progress callback
- **Translation/explanation**: context sentence extraction
- **Vocabulary**: capture / list / detail / sync / graph views
- **Graph links**: hide/unhide + bilateral optimistic sync
- **Toast notification system**: capsule toast + sheet overlay
- **Graph thumbnail** + health blob
- **Today review**: 4-state phase matrix + `PostExampleMetrics`
- **Stats overview**: `StatsPresenter` full state matrix
- **Settings + account deletion**: paywall Free/Pro 對照 + 安全確認 + Pro badge + CSV export via `VocabularyExporter`
- **Onboarding**: empty-state login entry points + Welcome 3-step walkthrough (sticky login CTA)
- **AppStartupRecoveryView** 三層 recovery
- **App-intent / background sync** + preview matrix
- **Mac Catalyst** (macOS 15.0+): iOS app runs natively on Mac via Catalyst (`SUPPORTS_MACCATALYST`, App Sandbox); 原生視窗尺寸(最小 900×640 / 首發 1100×760 置中)+ Reader 沉浸閱讀(EPUB/PDF 隱藏 title bar,`MacWindowChrome`); 頂部選單列 + ⌘ 快捷鍵(設定 ⌘,、同步 ⌘R、新增單字本 ⌘N、匯入 ⌘I、搜尋單字 ⌘F、複習 ⌘⏎、複習快捷鍵說明;`MacMenuCommands` 走 app-global `AppCommandCoordinator` intent + 畫面動作 via `FocusedCommandValues`/focusedSceneValue,全 menu code gated Catalyst-only); 指標 hover 回饋(卡片浮起 `appHoverLift` / 可點列染色 `appHoverRowTint`) + 可拖曳分隔線欄寬游標(`MacColumnResizeCursor`,`UIPointerInteraction`); podcast series 右鍵/長按追蹤切換
- **Notebook robustness**: `resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense
- **Notebook bookshelf**: LazyVStack book-row list + `NotebookCard` HStack layout (cover 40% left + metadata right, fixed-height 72pt rows) + serif italic name (`AppFonts.serif(17, bold).italic`) + active small dot (5pt, darken 0.5) + 1pt darken rule overlay + cover system (12-color Morandi palette + 6 SwiftUI Canvas patterns + unified noise pattern 0.04 + PhotosPicker custom image) + `N 詞` monoLabel + ProgressCapsule (cover-tinted fill, 4pt) + 條件 due dot (warning) + 空 notebook placeholder + page section header `今日複習` + inline pill cluster (`VocabReviewCTAPill` + filter + 新增, replaces VocabReviewBanner + toolbar buttons) + pending sync via TipView → SyncView integration + export dual-entry + sort menu + empty-state CTA + `NotebookCardActions` reusable context menu + dark mode cover auto-darken via `NotebookPalette.darken`
- **Podcast player**: audio + sentence-level SRT highlight + reader-parity 翻譯 via `VocabularyContextProtocol` + phrase 長按整句 + auto-pause-on-lookup + subtitle size S/M/L/XL/XXL + series 追蹤 toggle + 已追蹤浮上書庫頂端 + per-user progress sync to backend + YouTube-style buffered seek-bar overlay + tap-to-warm AVFoundation connection (DNS/TLS/Range pre-fired during navigation push) + bookshelf-appear predictive prefetch of followed-series first episode + inline subtitle in metadata.json (zero subtitle RTT) + background episode download (URLSession.background, file:// local-first playback, context-menu Download/Cancel/Remove, compact progress ring in row) + 睡眠定時 (5/15/30/60min + end-of-episode, wall-clock DispatchSourceTimer) + 字幕 follow-mode（iPhone/iPad 拖曳隱式脫離；Mac Catalyst 常駐明確 toggle「停止跟隨 ⇄ 追隨當前」，因 indirect scroll 不觸發 DragGesture；捲動提前約 0.5s lead，下一句被講到前先滑到中央，seek 時 pin 回當前句）+ Mac/iPad regular series 集數列表 overlay master pane（疊加在恒定書架 root，點 series 卡片開啟、不 push；episode → player 改單欄 push，所有 layout 一致；iPhone series 層亦 push）
- **Auto-sync**: 60s cooldown + toggle onChange 觸發
- **Notebook cover photo 編輯**: `photoError` + `originalCoverImagePath` 延遲刪 + 取消還原
- **Graph empty state**: 區分「無單字」vs「有單字無連結」
- **Vocab list 效能** + 空態 CTA
- **Reader error retry**: publication / PDF / translation / explain
- **Word detail share button**: plain text via ShareLink
- **Design system v2**: `AppCompactActionButtonStyle` + `AppOfflineBanner` + `AppSkeleton` primitives;`AppSpacing`/`Radius`/`Elevation` z0-z4 / `Layout`/`Motion` (emphasizedDecelerate / Accelerate / subtleBreath) + `TapFeedback` token;brand hero indigo + state bgs + display1/2 serif;paper-tone shadow 0.18;raw transitions 已全數消除
- **State matrix error states**: notebook list / podcast list / bookshelf / translation settings / today review failure feedback
- **Sentry crash reporting**: opt-in via Info.plist `SentryDSN` + auth scrubbing + frame locals dropped + breadcrumb across services + `KGService` iOS HTTP breadcrumb

## Backend (`backend/src/kg`)

- **Auth/user identity**: Apple/Google + web auth + cookie admin session + provider switch / session invalidation matrix + `google_auth` case-insensitive bool normalize
- **User config / account lifecycle**
- **Vocabulary / graph-link APIs**: hide/unhide/blocked pairs
- **Translate / explain / pipeline**
- **Card / graph / embedding / difficulty / enrichment**
- **Multi-format import parsing**
- **Query path perf**: incremental sync / zipf cache / filter-before-sort
- **Write path perf**: batch ops / N+1 elimination
- **公開頁(官網)**: landing 首頁(`/`)+ privacy / terms / support / guide 已重構成消費 iOS 設計系統的官網 — Cormorant 襯線標題 + 暖色盤 + z1 卡片 + divider、暗色 no-FOUC toggle、響應式、a11y(skip-link / focus-visible / aria-current / 單一 h1+h2、FAQ 原生 `<details>`);landing 含 App Store CTA pill(自繪 Apple glyph、非 Apple licensed badge)+ token 渲染 iPhone device mock(illustrative、內嵌詞卡 popover 自證選詞流程)+ honest trust strip(formats/platform only、never a metric);全站注入 PWA/SEO 資產(og-image / favicon / apple-touch)+ `site-motion.js` progressive-enhancement scroll-reveal(reduced-motion / no-JS 全降級);吃 `/static/{kg-tokens,kg-components,site}.css` + 自帶 Cormorant Garamond / ElmsSans woff2,由 `app.mount("/static", StaticFiles)` 服務(`backend/static/`,Dockerfile `COPY static/`)
- **System observability**: `/api/system/info` + VERSION tracking + `deploy.log` + site-wide observability panel + `observability_alerts` wired to `/system/info`
- **Pipeline telemetry** (`pipeline_log.db`): per-run/step timing + status + items;admin UI summary stats + stacked bar chart
- **Pipeline lock-queue**: concurrent triggers queue via `async with lock` + catch-all defense for user-deleted-mid-queue KeyError
- **Pipeline `degree_cap` audit metric fix**: UPDATE not INSERT;4 caller queries exclude `degree_cap`
- **One-shot judge**: `pending_judge` + selective prompt + degree cap + batch judge 86% token savings + `update_to_rejected` helper
- **`judge_log`**: complete decision tracking + acceptance rate
- **`translate_log`**: structured LLM call logging + cross-user cache + precise hit counter + admin search/timeline
- **Translate singleflight dedup**: 120s follower timeout + N>2 loop semantics
- **Translate cache**: env-tunable TTL `TRANSLATE_CACHE_TTL_DAYS` + model-key column migration
- **Log retention env vars**: `JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS` + pruners + CLI + admin trigger endpoint + flat aliases
- **Podcast API**: `/api/podcasts*` 認證端點（手刻 Range/206 音訊串流 + `ep_num` Path 驗證；S3 模式 audio 副檔名由 metadata `audioFormat` 決定，相容 legacy mp3）+ series 封面 proxy `GET /api/podcasts/{sid}/cover`（image/png，pipeline `cover` stage 產出 + metadata `coverImageURL`，缺則 404 → client 退程序化封面）+ per-user podcast progress LWW SQLite store（legacy 無認證 `/api/podcast-media/` StaticFiles 掛載已於 2026-05 移除，零生產流量後關閉公開讀取繞道）。生成 pipeline 工程文檔:`docs/sop/podcast_pipeline.md`
- **Podcast 上傳閉環 + drift 安全網**: pipeline 終端 `publish` stage 合成完成即自動上傳 S3 + verify（無手動步驟）;`ops/podcast_backfill_disk.py` served-disk→S3 回填 + `--check` reconcile;monitor `GET /api/remote/reconcile` 報 workspace↔S3「合成了但沒上傳」drift
- **EmbeddingStore env wiring**: `EMBEDDING_MODEL` / `EMBEDDING_DIM` 透過 factory 傳入 + dim mismatch guard + cache key 含 model+dim + `_load` shape verification 防 silent corruption
- **`cards.batch_touch(notebook_id=...)`** scope filter
- **`orphan_scan`** cross-DB consistency scanner + admin endpoint
- **Backend hardening**: podcast ACL / rate-limit / embedding / sqlite WAL
- **依賴升級**: cryptography 48 + starlette 1.0 + fastapi 0.136
- **Sentry SDK 整合**: `sentry_init.py` opt-in via `SENTRY_DSN` env + auth header/cookie scrubbing + `request_id` tag in scope + release tag + per-path traces sampler + uid scope + `/api/system/info` 暴露狀態 + admin smoke ping endpoint `POST /api/admin/sentry/ping`
- **Pluggable LLM provider registry** (`kg/llm/providers.py`):
  - Gemini/DeepSeek/未來 Qwen·GLM 皆 OpenAI-compatible;加 provider = 加一列 `REGISTRY`
  - Per-call-type env 路由 `LLM_PROVIDER_*`(precedence: call_type > group > DEFAULT > gemini)
  - `embed` 永遠獨立留 Gemini,不繼承 DEFAULT
  - `TrackedLLM` 自動注入 provider `extra_body`(DeepSeek thinking-disabled)/`max_tokens`
  - `quota_service` provider-aware 計價
  - A/B 工具 `kg/llm/ab.py`;env 清單見 `docs/sop/deploy.md`

## Chrome Extension (`chrome-extension/`)

- Side panel vocab lookup
- 單字本 filter chip 多選過濾複習狀態（空=全部）+ sort pill dropdown 切換 4 種排序（複習優先 / 字母序 / 最近新增 / 難度），對標 iOS `KGVocabView` 管線（state filter → search → sort）；無匹配顯示空狀態
- 閱讀選詞翻譯
- 選字翻譯全域開關(options 頁「選字翻譯」master switch,storage key `kg_enabled` 預設開;content.js mouseup gate,跨分頁 onChanged live-sync 免重整)
- 介面多語基礎(`chrome.i18n` + `_locales/zh_TW/messages.json`,現 zh_TW;`shared/i18n.js` DOM helper 套用 `[data-i18n]`,manifest `default_locale`)
- Auth token 整合
- woff2 字型(`shared/fonts.css` surface-local @font-face)
- Side panel error state taxonomy + settings entry + `AbortError` safety
- 消費生成的設計 token(`shared/tokens.css` 由 `ops/gen_web_tokens.py` 產出,`:host` selector 修掉注入 closed Shadow DOM 卻 token degraded 的 bug)

## Admin

- **Dashboard** (`/admin`): judge acceptance rate + 30-day error/token/DAU trend sparklines + Sentry Ping button + site-wide observability panel
- **User detail page** (`/admin/user/<uid>`): two-column 帳戶/訂閱/grant/額度/token + AI cost summary (judge/translate/pipeline/other) + graph density chart + graph playback + pipeline waterfall + `translate_log` viewer + 24h activity timeline
- **`/api/admin/users/search`**: uid / email / displayName
- Admin grant/revoke audit log
- Password login (`/admin/login`)
- Logs/stats APIs (`/api/admin/*`)
- Test-matrix (`/admin/tests`)
- In-memory log capture

## Tests (`backend/tests`)

- API contract、robustness、admin/test-matrix
- Auth provider: Apple/Google + provider switch + malformed claims + expired + clock skew + takeover
- `web_auth` security: state mismatch + cookie tampering
- `text_utils`/enrich: malformed / atomicity / token accounting
- `log_retention`: env + empty + admin trigger
- `token_tracker` concurrent write isolation
- Cards incremental sync: since / tombstone / pagination edge
- Embedding: store dim mismatch + cache key + factory env + load shape
- Judge edges: batch partial failure + degree cap + token savings
- Rate limit: GC + size cap + concurrent
- Difficulty: zipf common / rare / unknown
- Graph: bilateral hide/unhide + blocked pair persistence
- Billing edges: refund / duplicate / grace / reconcile
- Pipeline: concurrency saturation + user-deleted-mid-queue + cascading failure + quota exhaustion + step rollback + log lifecycle
- Retry: jitter + cancellation + nested edge
- Multi-format parser: malformed / encoding / large-file
- Translate cache: TTL + cross-user + model-key + cooldown + dedup
- Quota tier transition + grant revoke
- `sync_merge` three-end concurrent + tombstone-vs-restore
- Migration scripts: idempotent + rollback safety
- `observability_alerts` isolation + boundary
- Admin `user_activity` (empty / mixed / pagination)
- Admin cost summary + trends (errors + llm-fail 雙訊號)
- Sentry init scrubbing
- LLM provider registry: routing precedence + 空 env fallthrough + case-insensitive call_type + embed 獨立性 + unknown-provider raise
- Provider-aware pricing: `token_cost_usd` 分 provider
- `TrackedLLM` `extra_body` / `max_tokens` 注入
- Translate/pipeline/vocab 接線路由
- A/B harness smoke

## Tests (`ios/BooksBrowserTests`)

- Vocabulary entry lifecycle
- Bilateral link mutation
- Reader bridge planner
- Session persistence
- Notebook orphan defense: `resolveNotebookId` + `sanitizeOutbox` + `triggerPipelinesIsolated`
- `PodcastVocabContext` + `ReaderTranslationHandler` + `ReaderVocabularyCapture`
- `QuotaStore` + `KGError`/`RetryPolicy` + TodayReview `PostExampleMetrics`
- State matrix error states: notebook / podcast / bookshelf / translation settings / today review

## Ops

- Safe wrapper
- Smart deploy: auto fast/full path + rsync `--delete` stale files
- ops-cli (container 內查詢工具,`db-query` 不需引號)
- container-script (本地腳本上傳執行)
- `ops_analyze.py` one-command deep graph analysis levels 1-6
- Preflight / backup / restart / status / logs (`KG_LOG_TZ` 時區轉換) / migration workflows
- System observability: version tracking + deploy log
- `ios_test.sh`: `-g` pattern grep + clean output
- `podcast_upload.sh`: `series_id` regex + `createdAt` idempotent + rsync `--partial-dir --delay-updates` 原子 + 遠端 `index.json` flock
- **Podcast producer dashboard**(`lab/podcast/monitor/`,localhost:8765):workspace 列表 sidebar(search / 狀態 chip / sort recent⇄A→Z / mobile drawer,localStorage 持久)+ 每 workspace 富 summary(status `running|done|failed|awaiting|idle|fresh`、`milestones[]` 四產物關卡 + `gates[]` 兩道人工核准 gate 三態(passed/awaiting/pending)、progress、cost LLM/TTS split、episodes、last_updated、active_job 透過 `<ws>/.pipeline_job_id` sidecar 反查)+ 側欄進度改**三相雙閘軌**(PLAN/SCRIPT/AUDIO 三相條 + 兩 gate glyph,awaiting 琥珀脈動;subtitle 折進 audio 相細底線)+ 內嵌試聽(SRT chat-bubble 渲染:解析 `[Speaker]` 前綴將連續同講者 cue 合併成氣泡,兩位講者分左右兩色;每字 click-to-seek + 高亮同步保留)+ episode chip 顯示完整 TTS 模型 id(從 `ep_N_<variant>.meta.json` sidecar 讀;舊集數無 sidecar 時 fallback 為 `pro (?)` / `flash (?)` 表世代未知)+ LIVE ACTIVITY feed 把 `[...]` 方括號內容(TTS 情緒 tag / 集數清單)行內高亮成 badge + nav SETTINGS(⚙)面板(localStorage 持久,套用於下一條 pipeline,每旋鈕單一來源:PARALLEL workers(原 nav input 已收斂於此)、TTS MODEL 下拉(建立時凍結進 `.tts_model` sidecar、選非-3.1 family 顯示跨 family 風險紅字);spoiler 仍只在 NEW PODCAST modal)+ NEW PODCAST upload modal(可選 `tts_model`)+ UPLOAD / DELETE / RERUN-STAGE 動作 + **情境式推進鈕**(一顆鈕依狀態變身:awaiting→▶ APPROVE PLAN/SCRIPTS 寫 gate 標記續跑、idle/failed 有未完工→▶ RESUME 純 auto-resume、running→禁用、READY→隱藏)+ RECENT JOBS panel + PUBLISHED ON SERVER 遠端 series 管理(rm + index.json rebuild)。main 欄按 scope 分兩區:**THIS PODCAST**(選中 workspace:KPIs → stage 縱向 timeline → cost → episodes → live activity,band 顯示書名)與 **SERVER · all podcasts**(全域:recent jobs + published,recessed surface);stage 進度改縱向 timeline(spine dot + 連接線進度,running/failed 才顯 pill)。`./start.sh` 預設前景跑(`--bg` 給 pipeline.py auto-launch)
- Post-deploy smoke verify: `system/info` + health + sentry test event
- `backup_verify.sh`: restore drill + integrity check
- Chrome extension release bundle script + tests
- pytest pinned in `pyproject.toml [dependency-groups].dev`(修 backend venv 無 pytest)
- **跨平台設計系統地基**: `design-system/tokens.json`(**W3C DTCG 格式**,跨平台 token SoT)經兩條生成鏈出貨 — **Style Dictionary**(`npm run build`,`sd.config.mjs`)→ iOS `DesignTokens.swift`(scalar bridge,禁手改)+ **`ops/gen_web_tokens.py`** → web CSS(`design-system/dist/` + chrome-extension + `backend/static/`)。手寫 primitives 源 `design-system/dist/kg-components.css`,複製進三 web surface(extension + 官網);chrome-extension 三 surface(sidepanel/popup/options)已消費此 primitives,視覺鏡像 iOS。已接線 scalar 群組(radius/spacing/type-scale/tracking/elevation,47 值)為 Figma→iOS 真注入,設計師 SOP 見 `docs/sop/figma-token-workflow.md`
- **設計系統三層 guard + CI 強制**: `token_drift_check.py`(**值**:SoT-inversion-aware,已接線解析 `DesignTokens.*` 引用、未接線比 `$swift` literal,含 `AppTag` chip padding/fill)+ `component_fidelity_check.py`(**組裝**:contract-based 守每個 primitive 選用哪個 token 對齊 iOS 元件,如 `.kg-btn` radius md/700、`.kg-chip`↔`AppTag`、`.kg-input` body+hairline)+ `gen_web_tokens.py --check`(**生成**:無 stale 副本)+ `npm run build:check`(Style Dictionary:`DesignTokens.swift` ↔ tokens.json),聚合入口 `ops/verify_design_system.sh`,由 **repo 首支 GitHub Actions CI**(`.github/workflows/design-system.yml`,路徑觸發 + `npm ci`)+ `.githooks/pre-commit` 雙重強制
