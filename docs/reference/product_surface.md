<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/
  - backend/
  - ops/
  - lab/
verified_against: 525fc0a4
-->
# Implemented Product Surface

動手前對照,確認不重複建造。功能上線後在此追加 bullet,而非寫在 `CLAUDE.md`。

---

## iOS (`ios/BooksAndVocab`)

- **Auth flows**: Apple/Google SSO
- **Bookshelf + reader**: EPUB/TXT/MD/PDF multi-format import + batch select + classified error diagnosis + import progress callback + 書庫下拉刷新（iOS/iPadOS pull-to-refresh）／Mac toolbar 同步鈕觸發帳號背景同步（詞庫/複習/KG，非書本清單；成功彈確認 toast、失敗 warning，經 `ExplicitSync` 與 ⌘R 共用同一回饋政策）+ **書架空狀態 CloudKit 還原透明化**（本地 0 列 ≠ 沒有書：`CloudKitMirroringMonitor` 監聽 mirroring 事件，雲端還原中顯示 ProgressView「正在從 iCloud 取回書庫…」、同步失敗顯示 `exclamationmark.icloud` 警示，只有首次 import 成功收尾後才把 0 本書講成「尚無書籍」）
- **Reader vocabulary highlight controls**: Reader settings「生字標記」可調 highlight 顏色（paper/blue/sage/rose）與濃度；偏好存於 `ReaderSettings.vocabHighlightPreferences`，Reader Readium CSS 與 Podcast 字幕詞庫 highlight 共用同一組設定。
- **每本書/每個 podcast 系列強制綁定恰好一本真實單字本**（`NotebookBindable`，Book/PodcastSeries 共用）：開啟時以最近使用的真實單字本 seed 固化綁定（seed gate `canSeedBinding` 須指向 live 清單內已 settle 的本，擋未同步 `"default"` sentinel），之後選詞 / highlight / cache scope 一律認綁定本，**不再隨全域 active 漂移、無 magic 預設本概念**；`ReaderNotebookPicker` 移除「跟隨全域設定」、`NotebookBindingList` 不再標示「預設」，所有單字本平權。綁定為本機偏好（server 不下發 `preferredNotebookId`，reconcile upsert 不覆寫）；綁定的本被刪除時自動清除、下次開啟 re-seed。
- **Translation/explanation**: context sentence extraction
- **Vocabulary**: capture / list / detail / sync / graph views
- **Graph links**: hide/unhide + bilateral optimistic sync
- **Toast notification system**: capsule toast + sheet overlay
- **Graph thumbnail** + health blob
- **Today review**: 4-state phase matrix + `PostExampleMetrics` + 跨裝置保存完整複習事件，月曆與每日明細顯示真實 `ReviewRecord` + Settings「凍結複習時鐘」(due/reviewed 計算、notebook CTA、stats forecast、graph ratio/row progress 使用 paused reference date;已到期卡仍可手動複習;**跨裝置同步** UserDefaults + iCloud KV(updatedAt LWW 整組原子)+ 登入經 `GET/PUT /api/user/config` 的 `review_clock` push/fetch、push 失敗 rollback、server cold-start wins,對標翻譯語言) + autoplay 聲音開關（首次預設開啟、記住上次選擇、答案揭露後才朗讀單字）+ **複習模式 + 自訂 SRS 參數跨裝置同步**（mode/relaxed-intensive-custom 與 5 個自訂間隔參數三層 UserDefaults + iCloud KV(updatedAt LWW 整組原子) + 登入經 `review_mode` push/fetch、push 失敗 rollback、server cold-start wins，對標 pause clock，確保跨裝置 SRS 間隔一致） + 洗牌順序持久化（per-user + queue fingerprint，KG card id 優先、local UUID fallback，新卡附加尾端）
- **Stats overview**: `StatsPresenter` full state matrix
- **Settings + account deletion**: paywall Free/Pro 對照 + 安全確認 + Pro badge + CSV export via `VocabularyExporter` + review progress pause/freeze toggle；設定首頁「複習節奏」列在 progress paused 時顯示 `已凍結 · <模式>`，detail 仍由既有「暫停進度」toggle 控制；**「自動連結」toggle**（登入顯示）控制 backend judge pipeline 是否自動建立知識圖譜連結——關閉時新單字仍 enrich+embed 並排入待判集合、重開續判不丟失；本地 UserDefaults 快取 + 後端 `auto_link` group（`updated_at` 真 LWW，push 失敗 rollback 含原時戳）；**iCloud 書庫同步狀態列**（CloudKitMirroringMonitor.phase 投影：確認中／還原中／同步異常帶錯誤描述／已同步；書庫綁 Apple ID 故不掛登入 gate，localOnly 整列隱藏）
- **Onboarding**: empty-state login entry points + Welcome 3-step walkthrough (sticky login CTA)
- **AppStartupRecoveryView** 三層 recovery
- **App-intent / background sync** + preview matrix
- **Mac Catalyst** (macOS 15.0+): iOS app runs natively on Mac via Catalyst (`SUPPORTS_MACCATALYST`, App Sandbox); 原生視窗尺寸(最小 900×640 / 首發 1100×760 置中)+ Reader 沉浸閱讀(EPUB/PDF 隱藏 title bar,`MacWindowChrome`); 頂部選單列 + ⌘ 快捷鍵(設定 ⌘,、同步 ⌘R、新增單字本 ⌘N、匯入 ⌘I、搜尋單字 ⌘F、複習 ⌘⏎、複習快捷鍵說明;`MacMenuCommands` 走 app-global `AppCommandCoordinator` intent + 畫面動作 via `FocusedCommandValues`/focusedSceneValue,全 menu code gated Catalyst-only); 指標 hover 回饋(卡片浮起 `appHoverLift` / 可點列染色 `appHoverRowTint`) + 可拖曳分隔線欄寬游標(`MacColumnResizeCursor`,`UIPointerInteraction`); podcast series 右鍵/長按追蹤切換
- **Notebook robustness**: `resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense
- **Notebook bookshelf**: LazyVStack book-row list + `NotebookCard` HStack layout (cover 40% left + metadata right, fixed-height 72pt rows) + serif italic name (`AppFonts.serif(17, bold).italic`) + active small dot (5pt, darken 0.5) + 1pt darken rule overlay + cover system (12-color Morandi palette + 6 SwiftUI Canvas patterns + unified noise pattern 0.04 + PhotosPicker custom image) + `N 詞` monoLabel + ProgressCapsule (cover-tinted fill, 4pt) + 條件 due dot (warning) + 空 notebook placeholder + page section header `今日複習` + inline pill cluster (`VocabReviewCTAPill` + filter + 新增, replaces VocabReviewBanner + toolbar buttons) + pending sync via TipView → SyncView integration + export dual-entry + sort menu + empty-state CTA + `NotebookCardActions` reusable context menu + dark mode cover auto-darken via `NotebookPalette.darken`
- **Podcast player**: audio + sentence-level SRT highlight + reader-parity 翻譯 via `VocabularyContextProtocol`（字幕選取 edit menu：「翻譯」依字數分流——單字→word path（加入詞庫 + 去重）、片語→phrase path；「解釋」對單字 + 片語皆出現，對齊 reader gate-free edit menu）+ **詞庫螢光筆**（已加入詞庫的詞在字幕自動上 reader-shared 半透明字底色帶；顏色/濃度由 Reader settings 與 Podcast settings 共用；含 inflections + 彎/直撇號折疊；`PodcastVocabHighlightResolver` 純函式 + cell 常駐 background layer 複用逐詞 TextKit rect，所有句子常駐、選取時仍顯示；播放逐字底線另走 overlay top layer，避免 highlight 蓋掉 follow underline）+ phrase 長按整句 + auto-pause-on-lookup + subtitle size S/M/L/XL/XXL + series 追蹤 toggle + 已追蹤浮上書庫頂端 + per-user progress sync to backend + YouTube-style buffered seek-bar overlay + tap-to-warm AVFoundation connection (DNS/TLS/Range pre-fired during navigation push) + bookshelf-appear predictive prefetch of followed-series first episode + inline subtitle in metadata.json (zero subtitle RTT) + background episode download (URLSession.background, file:// local-first playback, context-menu Download/Cancel/Remove, compact progress ring in row) + 睡眠定時 (5/15/30/60min + end-of-episode, wall-clock DispatchSourceTimer) + 字幕 follow-mode（iPhone/iPad 拖曳隱式脫離；Mac Catalyst 常駐明確 toggle「停止跟隨 ⇄ 追隨當前」，因 indirect scroll 不觸發 DragGesture；捲動提前約 0.8s lead，下一句被講到前先滑到中央，seek 時 pin 回當前句）+ **獨立頂層「播客」section**（`PodcastHomeView`，iOS TabView 第 2 / Catalyst sidebar；軸 B Phase 3，podcast 不再經書架進入）：串流首頁 = 繼續收聽橫排 shelf（跨 series 最近未完成，`PodcastShelf`+`PodcastContinueRailCard`）+ 所有節目 grid（followed 排前+star）；series→episode→player 全 value-based push 在自有 `NavigationStack` + **連續播放 auto-advance**（本集播畢自動續播同 series 下一可播集，`PodcastQueue` entitlement gate：free 播完 ep1 不跨集、guest 不續）+ **分層授權 UX（guest/free/pro）**：客戶端 tier policy `PodcastAccess`（鏡射後端 `podcast_access.py`，由 `subscriptionManager.hasProAccess` + token 存在推導）；訪客可瀏覽 catalog（`optionallyAuthedData` 無 token 亦放行），但 episode row／hero CTA 鎖定（`lock.fill` badge）、tap 彈 `LoginSheet`；free 只開 ep1（hero「免費試聽 3 分鐘」→ player 播放獨立 `preview.*` 並顯示 brand 試聽條 + 升級 CTA），ep2+ 鎖定 tap 彈 `SubscriptionPaywallSheet`（`PaywallSource.podcast`）；player 自帶防禦式 gate（deep-link/continue-playing 直達非可播集 → `lockedGateView`，不載入音訊）。pro 全開。`PodcastEpisode` 新增 `previewAvailable`/`previewDurationSec` + **系列綁定單字本**（toolbar `books.vertical` 入口 → `PodcastNotebookPicker` 切換；選詞 / 底線 / cache scope 認系列 `resolvedNotebookId` 綁定本，取代全域 active；開啟時 `seedSeriesBindingIfNeeded` 以 live notebook seed 固化）
- **Auto-sync**: 60s cooldown + toggle onChange + 離線→連線恢復時重新評估 pending queue + 背景同步失敗 toast 使用分類文案（離線/逾時/登入/伺服器/格式/本機儲存/未知），log/Sentry 保留內部 phase label
- **Notebook cover photo 編輯**: `photoError` + `originalCoverImagePath` 延遲刪 + 取消還原
- **Graph empty state**: 區分「無單字」vs「有單字無連結」
- **Vocab list 效能** + 空態 CTA
- **Reader error retry**: publication / PDF / translation / explain
- **Word detail share button**: plain text via ShareLink
- **Design system v2**: `AppCompactActionButtonStyle` + `AppOfflineBanner` + `AppSkeleton` primitives;`AppSpacing`/`Radius`/`Elevation` z0-z4 / `Layout`/`Motion` (emphasizedDecelerate / Accelerate / subtleBreath) + `TapFeedback` token;brand hero indigo + state bgs + display1/2 serif;paper-tone shadow 0.18;raw transitions 已全數消除
- **State matrix error states**: notebook list / podcast list / bookshelf / translation settings / today review failure feedback
- **Sentry crash reporting**: opt-in via Info.plist `SentryDSN` + auth scrubbing + frame locals dropped + breadcrumb across services + `KGService` iOS HTTP breadcrumb

## Backend (`backend/src/kg`)

- **Auth/user identity**: Apple/Google + web auth + cookie admin session + provider switch / session invalidation matrix + `google_auth` case-insensitive bool normalize + 唯讀 profile face (`GET /api/user/profile` → `displayName`/`email`/`provider`，由登入 record 衍生，與可變 config bundle 分離)
- **User config / account lifecycle**
- **Vocabulary / graph-link APIs**: hide/unhide/blocked pairs + 單字內容編修 (`PATCH /api/vocab/{word}` 改 meaning/note，`explanation` 為 `note` write-through alias) + `/api/vocab/review-events` 完整複習事件同步（client UUID 冪等、刪卡後事件仍保留） + `GET /api/vocab` cursor 分頁（`limit`/`cursor` query + `X-Next-Cursor` header，與 `since` 增量正交）
- **Library APIs**: server 端書庫鏡像；list(`?since=` 增量含 tombstone)/create(`client_book_id` 冪等)/patch(metadata+notebook 綁定)/position(LWW 閱讀進度)/`DELETE /api/library/books/{id}` 軟刪（set `is_deleted`，冪等）；書檔資產跨裝置（Arch PR #7）：`POST /api/library/books/{id}/asset-upload`（`LIBRARY_BUCKET` 未設或 `local_only`→宣告 local-only；已設→presigned PUT + 配額上限）、`GET /api/library/books/{id}/asset`（object-stored→307 redirect presigned GET；local-only→409）
- **Translate / explain / pipeline**
- **Card / graph / embedding / difficulty / enrichment**
- **Multi-format import parsing**
- **Query path perf**: incremental sync / zipf cache / filter-before-sort / cursor-bounded page fetch (`CardStore.page_cards`，不物化全表) / batched embedding similarity (`EmbeddingStore.find_similar_batch`，單次 matmul + argpartition top-k)
- **Write path perf**: batch ops / N+1 elimination
- **公開頁(官網)**: landing 首頁(`/`)+ privacy / terms / support / guide 已重構成消費 iOS 設計系統的官網 — Cormorant 襯線標題 + 暖色盤 + z1 卡片 + divider、暗色 no-FOUC toggle、響應式、a11y(skip-link / focus-visible / aria-current / 單一 h1+h2、FAQ 原生 `<details>`);landing 含 App Store CTA pill(自繪 Apple glyph、非 Apple licensed badge)+ token 渲染 iPhone device mock(illustrative、內嵌詞卡 popover 自證選詞流程)+ honest trust strip(formats/platform only、never a metric);全站注入 PWA/SEO 資產(og-image / favicon / apple-touch)+ `site-motion.js` progressive-enhancement scroll-reveal(reduced-motion / no-JS 全降級);吃 `/static/{kg-tokens,kg-components,site}.css` + 自帶 Cormorant Garamond / ElmsSans woff2,由 `app.mount("/static", StaticFiles)` 服務(`backend/static/`,Dockerfile `COPY static/`)
- **System observability**: `/api/system/info` + VERSION tracking + `deploy.log` + site-wide observability panel + `observability_alerts` wired to `/system/info`（pipeline-failure / judge-rejection / translate-latency-p95 / **LLM error-rate** 四 check，threshold+cooldown）
- **Pipeline telemetry** (`pipeline_log.db`): per-run/step timing + status + items;admin UI summary stats + stacked bar chart
- **Pipeline lock-queue**: concurrent triggers queue via `async with lock` + catch-all defense for user-deleted-mid-queue KeyError
- **Pipeline `degree_cap` audit metric fix**: UPDATE not INSERT;4 caller queries exclude `degree_cap`
- **One-shot judge**: `pending_judge` + selective prompt + degree cap + batch judge 86% token savings + `update_to_rejected` helper
- **`judge_log`**: complete decision tracking + acceptance rate
- **`translate_log`**: structured LLM call logging + cross-user cache + precise hit counter + admin search/timeline
- **Translate singleflight dedup**: 120s follower timeout + N>2 loop semantics
- **Translate cache**: env-tunable TTL `TRANSLATE_CACHE_TTL_DAYS` + model-key column migration
- **Log retention env vars**: `JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS` + pruners + CLI + admin trigger endpoint + flat aliases
- **Podcast API（分層授權 guest/free/pro）**: `/api/podcasts*`（手刻 Range/206 音訊串流 + `ep_num` Path 驗證；S3 模式 audio 副檔名由 metadata `audioFormat` 決定，相容 legacy mp3）。**訪客可瀏覽** list/detail/cover（`get_current_user_optional`）；`audio`/`subtitle` 同一 tier gate — guest→`401 {code:auth_required}`（須登入才能播）、free→只能聽每 series **ep1 的 `preview.*` 試聽片**＋讀 ep1 逐字稿（其餘 `403 {code:upgrade_required}`，付費集逐字稿不外洩）、pro→full；policy 在 `podcast_access.py`（牆統一、無 per-series 旗標）。free 試聽走**獨立預生成 `preview.*` 物件**（progressive MP4 單 moov 無法乾淨 byte 截斷）。+ series 封面 proxy `GET /api/podcasts/{sid}/cover`（image/png，缺則 404 → client 退程序化封面）+ per-user podcast progress LWW SQLite store（legacy 無認證 `/api/podcast-media/` 掛載已於 2026-05 移除）。生成 pipeline 工程文檔:`docs/sop/podcast_pipeline.md`
- **Podcast 上傳閉環 + workflow provenance + drift 安全網**: pipeline 終端 `publish` stage 合成完成即自動上傳 S3 + verify（無手動步驟）;`pipeline.py --workflow-version v1|v2` 寫 workspace `workflow_manifest.json` / `stage_provenance/*.json` / `scripts/ep_N_lineage.json`（dashboard start 目前仍走預設 v1，v2 實驗入口先用 CLI）;`ops/podcast_backfill_disk.py` served-disk→S3 回填 + `--check` reconcile;monitor `GET /api/remote/reconcile` 報 workspace↔S3「合成了但沒上傳」drift
- **Podcast headless 觀測 CLI**（`ops/podcast_ops.py`）: 把過去鎖在 FastAPI dashboard 後的 podcast 觀測能力搬上終端/SSH/cron。`status`（狀態瀑布 + 集數 + 進度 + 花費,exit code 給 cron 訊號:2=failed/1=awaiting/0=ok）、`episodes`（逐集四關卡矩陣）、`cost`（TTS+LLM 花費聚合 + by-model）、`covers`（缺封面）純磁碟免 boto3;`reconcile`/`series` 走 S3。`--json` 可直接 `| jq`。共用 dashboard 的 `monitor/workspace_status.py` 推導邏輯（單一實作,不漂移）
- **EmbeddingStore env wiring**: `EMBEDDING_MODEL` / `EMBEDDING_DIM` 透過 factory 傳入 + dim mismatch guard + cache key 含 model+dim + `_load` shape verification 防 silent corruption
- **`cards.batch_touch(notebook_id=...)`** scope filter
- **`orphan_scan`** cross-DB consistency scanner + admin endpoint
- **Backend hardening**: podcast ACL / optional-auth malformed header 401 / validation 422 JSON-safe encoding / LLM failure secret redaction / rate-limit / embedding / sqlite WAL
- **依賴升級**: cryptography 48 + starlette 1.0 + fastapi 0.136
- **Sentry SDK 整合**: `sentry_init.py` opt-in via `SENTRY_DSN` env + auth header/cookie scrubbing + `request_id` tag in scope + release tag + per-path traces sampler + uid scope + `/api/system/info` 暴露狀態 + admin smoke ping endpoint `POST /api/admin/sentry/ping`
- **Pluggable LLM provider registry** (`kg/llm/providers.py`):
  - Gemini/DeepSeek/未來 Qwen·GLM 皆 OpenAI-compatible;加 provider = 加一列 `REGISTRY`
  - Per-call-type env 路由 `LLM_PROVIDER_*`(precedence: call_type > group > DEFAULT > gemini)
  - `embed` 永遠獨立留 Gemini,不繼承 DEFAULT
  - `TrackedLLM` 自動注入 provider `extra_body`(DeepSeek thinking-disabled)/`max_tokens`
  - `quota_service` provider-aware 計價
  - A/B 工具 `kg/llm/ab.py`;env 清單見 `docs/sop/deploy.md`

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

## Tests (`ios/BooksAndVocabTests`)

- Vocabulary entry lifecycle
- Bilateral link mutation
- Reader bridge planner
- Session persistence
- Notebook orphan defense: `resolveNotebookId` + `sanitizeOutbox` + `triggerPipelinesIsolated`
- `PodcastVocabContext` + `ReaderTranslationHandler` + `ReaderVocabularyCapture`
- `QuotaStore` + `KGError`/`RetryPolicy` + TodayReview `PostExampleMetrics`
- State matrix error states: notebook / podcast / bookshelf / translation settings / today review

## Ops

- **Safe wrapper**(`ops/devops_kg_safe.sh`): 生產維護統一入口。除 `deploy/status/health/logs/ops-cli/ops-edit` 外，現在把高頻 host/container 唯讀診斷也 typed 化成 `caddy-status` / `caddyfile` / `docker-ps` / `docker-logs [n]` / `disk-usage` / `memory-usage` / `docker-stats`，降低 agent 直接使用 `run "<cmd>"` 的需求；對這些已 typed 的常見查詢，raw `run` 會回覆「use typed command」。`run/container-run/migrate-run` 保留為例外逃生口，不是預設查詢面。
- Smart deploy: auto fast/full path + rsync `--delete` stale files
- ops-cli / ops-edit（container 內查詢與寫入工具；`db-query` 不需引號；`user-config <uid>` 唯讀檢視 user config；`world-state <uid>` 以穩定 schema `kg.ops_world_state.v1` 投影 `users.json config + notebooks/cards + disk graph`；`world-diff <uid> <spec.json>` 以 expectation schema `kg.ops_world_expectation.v1` 比對 actual world-state，輸出穩定 mismatch path，供 scenario diff/verify；`user-config-set`（含 `--auto-link on|off` 自動連結開關）+ `notebook-update --sort-order` 可做 Settings / active notebook / surface ordering 行銷造景；`world-snapshot` / `world-restore` 提供整個 data_dir world 級快照與回滾）
- capture profile 編排層（`ops/capture_profile.py`；marketing screenshot 主入口 orchestrator。把 `ops_edit` 真資料造景、`ios_ops.sh catalog snapshots --dataset-file ...`、`frame_catalog_screenshots.py` 的外框橋接、以及 `render_screenshots.py` 最終宣傳圖渲染收進同一個 recipe。profile 內以 `shots[]` 同時描述 `sourceScenario + appearance + copy.title/subtitle + outputName`，因此改資料、改文案、改 shot mapping 都不必動 iOS code 或 renderer 常數；`materialize.expectationFile` 可選掛 `world-diff` 驗證，`run --commit` 會在 snapshot 前 fail loud。`run` 預設 dry-run materialize、不寫 demo 帳號；若 `--reuse-build` 遇 stale cache，會自動 `catalog prepare` 再重試 snapshot。`derive-expectation` 可從 `seedFile + steps` 自動再生 expectation spec(取代手寫、`--check` 做 drift guard)，消除 scenario expectation 的手維護漂移）
- container-script (本地腳本上傳執行)
- `ops_analyze.py` one-command deep graph analysis levels 1-6
- Preflight / backup / restart / status / logs (`KG_LOG_TZ` 時區轉換) / migration workflows
- System observability: version tracking + deploy log
- `ios_test.sh`: scoped iOS verification (`unit` default / `--ui` / `--all-targets` / `--file` / `-g` / `--list` / `--launch-benchmark` / `--coverage` / `--coverage-fail-under <percent>` / UI-scope `--dataset <name>`・`--dataset-file <path>` UI World v2 注入（staged `*.scoped.xctestrun` upsert `TestingEnvironmentVariables.KG_FIXTURE_DATASET_B64`；`kg.fixture.dataset.v2` 同時帶 data/auth/entitlements、UserDefaults/iCloud KVS preferences、SwiftData row state 與 file-backed asset manifest，preferences seed 前寫入，Notebook / VocabularyEntry 的 sync/action/archive/reader-exclusion 狀態由 manifest 明示，asset 依 `installAs` materialize 到 app Documents；Bookshelf `bookAssetRef` 指向 `assets.books.*` 並物化到 `Documents/Books/<fileName>`；Podcast episode `download` 明示 audio/subtitle 是否已下載並控制 `localAudioPath` / `localSubtitlePath`；E2E 證明測試 `FixtureDatasetUITests`，repo contract `RepoFixtureDatasetsContractTests`）) with shared build lock, heartbeat, preserved failure logs, false-green detection, Xcode build DB lock retry, simulator preboot, dedicated `BooksAndVocabUnitTests` unit scheme + dedicated `BooksAndVocabUITests` UI scheme, cache-first `build-for-testing` / `test-without-building` reuse, explicit `--cache-status|--prepare-cache|--clean-cache` lifecycle controls, UI app launch-profile injection (`--ui-launch-profile standard|ui-smoke` via `KG_UI_TEST_APP_ARGS_JSON`), `prepare-cache` build-log/result-bundle artifacts in `kg.ios.test-cache.v1`, xcresult-derived timing/perf breakdown (`testBodyMs` / `xcresultSessionMs` / `appLaunchAverageMs` / `appLaunchSamples` / `invocationOverheadMs`), and `kg.ios.coverage.v1` line-coverage verdict with lowest-covered production files; downstream `ios_ops.sh runs/snapshot` 會把這些 timing/cache/coverage 欄位提升成第一屏判讀資料
- `uitest_flow_matrix.py`: 同一個 UITest flow 的 state/data variant runner；用 `--profile` × `--dataset`/`--dataset-file` 展開多次 `ios_ops.sh test --ui`，輸出 `kg.ios.uitest-flow-matrix.v1`，並讓 UIreview workspace 在同一 flow 下保留多個組合 variant（例如 `dataset:marketing_demo+profile:standard`）。
- **iOS ops 統一控制面**(`ops/ios_ops.sh`): agent/human 優先入口,組合 Xcode 官方 CLI 與既有 primitives；`build`/`test`/`archive` 委派底層腳本,其中一般 `build --json` / `test --json` 會由 façade 回傳 `kg.ios.run.v1` 並內嵌 `kg.ios.diagnostics.v1`，`test --coverage --json` 另內嵌 `coverage: kg.ios.coverage.v1`（target line coverage、fail-under verdict、`lowestFiles[]` 低覆蓋檔案），`archive --json` 會回 `kg.ios.archive.v1`（拆成 `archive/export/upload` 三段，含 `lockWaitMs/archiveMs/exportMs/uploadMs/totalMs`，也內嵌 diagnostics），而 `test --cache-status|--prepare-cache|--clean-cache --json` 維持 `kg.ios.test-cache.v1`；`archives` 查 Organizer,`issues` 解析 xcresult/log,`logs` 拉 runtime log（`--since` 回溯快照 / `--follow` 即時串流；`logs --json` 回 `kg.ios.logs.v1`，`logs --follow --json` 逐行輸出 `kg.ios.log-stream.v1`），`sentry` 回 iOS crash-report wiring 摘要（`sentry --json` 回 `kg.ios.sentry.v1`，固定表達 source/existence、Sentry import guard、DSN/debug test arg wiring、release name/dist contract，並以 `issues[]` 作為 wiring failure 單一真相，doctor verdict / snapshot nextActions / sentryWarnings 全衍生自此），`doctor` 做 release readiness，且 `doctor --json` 直接內嵌同一份 `sentry: kg.ios.sentry.v1`，`workflow release` 產出發版下一步,`gate release` 給 release hard-stop verdict,`xcode`/`environment` 讀 Xcode/project/destination/simulator inventory,`simulator`/`sim` 讀 booted simulator/app container/app process、可 `ensure-booted`/launch/terminate 已安裝 app、並可產生本機 screenshot artifact,`catalog prepare|snapshots|clean` 負責 Playbook catalog 截圖控制面,支援 `--group`/`--scenario` 範圍化輸出、`--reuse-build` 重用 warm build；`snapshots` 必須明示 `--dataset <name>` / `--dataset-file <path>` 將 UI World 注入 snapshot test process，讓截圖資料切換不需要改 iOS 畫面層程式碼（catalog observability:長 xcodebuild 階段發 stderr phase heartbeat、stdout 維持純 JSON；`--reuse-build` cache-miss 回 `status:"cache-miss"`(非 error)+ 可行動 hint；失敗時 salvage container 已生成 PNG 並用 `artifacts.containerPngCount`/`copy.salvaged` 區分「未生成」vs「生成但未複製」），`runs`/`reports` 讀最近 build/test/archive verdict + log/xcresult artifact + warning/error/test diagnostics,`snapshot`/`dashboard` 一次拉 project/Organizer/TestFlight/readiness/workflow/gate/sentry/xcode/simulator/runs，且其 `sentry` 直接重用 `doctor.sentry`。read-only surface 皆有文字輸出,agent 用 `commands --json`(`kg.ios.commands.v1` 自描述 side-effect/delegate/schema catalog，`jsonSchemas[]` 需包含穩定內嵌 child schema，不只 top-level)、`logs --json`(`kg.ios.logs.v1`;`--follow --json` 即時串流逐行輸出 `kg.ios.log-stream.v1`)、`sentry --json`(`kg.ios.sentry.v1`)、`doctor --json`(`kg.ios.doctor.v1`)、`workflow release --json`(`kg.ios.workflow.v1`)、`gate release --json`(`kg.ios.gate.v1`,exit code `0=pass`/`1=warn`/`2=block`)、`xcode --json`(`kg.ios.xcode.v1`)、`simulator status/ensure-booted/launch/terminate/screenshot --json`(`kg.ios.simulator.v1`;status/ensure-booted 管 lifecycle warm-up,不 build/install,並帶 simulator phase timing)、`build --json` / `test --json`(`kg.ios.run.v1`,`timings.lockWaitMs` 與 archive 同義記錄共享 build lock 排隊等待，`summary.timings.*` 以 passthrough 保留新增 timing 欄位；UI scope 的 `test --json` 另含 `uiVisualReview` 區塊回報自動生成的 full contact sheet / quick4 sheet / review manifest / screenshot dir / 歸檔 mp4 全程錄影 + reviewRoot/reviewHtml standalone UIreview + exists bools，非 UI run 為 null，並回頂層 `device`(run 的 sim UDID,取證/錄影皆繫於此)；coverage run 另含 `coverage.summary.lowestFiles[]`，第一屏會印前三個 `[ios][coverage][low]`)、`archive --json`(`kg.ios.archive.v1`)、`runs --json`(`kg.ios.runs.v1`,每個 run 內嵌 `kg.ios.diagnostics.v1`，且 archive 也進統一報表)、`snapshot --json`(`kg.ios.snapshot.v1`,文字模式共用同一 payload formatter 並以 `[ios][summary]` + `[ios][timing]` + `[ios][next]` 開頭;頂層 `summary.verdict/counts/nextActions/timings` 直接給第一屏判讀,其中 `summary.counts` 會直接 surfaced `readinessOk|readinessWarns|readinessBlocks|workflowReady|workflowTodos|workflowWarns|workflowBlocks|workflowManual` 與 `sentryWarnings`，而 `summary.nextActions` 也包含 gate `manual` steps；預設內嵌 `kg.ios.workflow.v1` + `kg.ios.gate.v1` + `kg.ios.sentry.v1` + `kg.ios.xcode.v1` + `kg.ios.simulator.v1` + `kg.ios.runs.v1` + `runs.*.diagnostics`;`--skip-xcode` 可省略 xcode;`--skip-simulator` 可省略 simulator;no booted simulator 會留在 snapshot payload 內而不讓 dashboard 失敗;`--include-logs` 時再內嵌 `kg.ios.logs.v1`)。
- **iOS App Store/TestFlight 發版**(`ops/ios_release.sh`): archive→export→`--upload` 出 `.ipa`;ASC API key 簽章基建(無需手動匯入 distribution 憑證)+ manual signing(Apple Distribution cert + `KG App Store` profile)+ `--upload` 前 build-number guard(擋 TestFlight 重複)+ 共用 iOS build lock。外部識別子以 live Apple 端為準：bundle id 固定 `com.Max0228.BooksBrowser`，profile `KG App Store` / product id `com.wordnexus.pro.monthly` / 正式網域 `wordnexus.lol` 不可只在 repo 單改。
- **App Store Connect 全表面控制台**(`ops/asc.sh`): 主體 codemagic CLI 包裝 + raw 旁路(唯讀 `ops/asc_get.py`、寫入 `ops/asc_write.py` 一般化 PATCH/POST/DELETE)。**唯讀**涵蓋 App 資訊/版本文案/審查狀態+備註/送審佇列(submissions)/截圖/分類/用戶評論/無障礙/訂閱+IAP+定價/訂閱優惠(sub-offers)/發布方式+分階段發布(release-plan)。**寫入**(皆預設 dry-run、`--yes` 才真送,經單一 `emit_write` gate):版本文案(set)/審查資訊(set-review)/App 層本地化 name+subtitle+privacy-url(set-appinfo)/EULA/內容版權/分類/年齡分級/評論回覆(reply-review)/訂閱名+描述+備註+價格(set-sub-*,改價動真實計費有 ⚠+保護既有訂戶)/發布方式(set-release-type)/分階段發布(phased start|pause|resume|complete|cancel)。**刻意不做**:submit-for-review/撤回送審、IAP 寫面(KG 無一次性 IAP)、訂閱優惠建立(走 GUI)、App 隱私權營養標+截圖上傳(無 public API);被拒原因 Resolution Center 文字 API 不可讀(須 GUI)。細節見 `docs/sop/ios.md §發版`
- **版號發布統一 CLI**(`ops/release.sh`): `status`(各 component 待發版 commit + 建議版號)/`changelog`/`bump`/`publish`(commit 版號檔+tag+push,dry-run 預設、`--yes` 才真送);`/release` slash command 為薄路由。委派 primitive `ops/release_bump.sh`/`ops/release_changelog.sh`(前身 `scripts/`)。無 tag-triggered CI,tag 為版本標記
- **iOS UI 死碼/孤兒掃描**(`ops/ui_deadcode.py` + `ops/swiftpm/kgindex`): IndexStore-based UI 健康工具。Swift `kgindex` 對 Xcode IndexStore 做中性符號萃取(def+ref+USR → JSON,零 policy),Python `ui_deadcode.py` 持有 production-orphan 判準(`classify_orphans` 純函式,same-file ref 算 production;default kinds=struct,class 為可信 gate,enum/protocol opt-in 有偽陽性屬人工 triage)。三輸入:`--build`(隔離乾淨 build 避 shared cache 跨 worktree 雙計)/`--store-path`/`--records-json`(測試 seam);`--json` schema `kg.ui.deadcode.v1`,warn-only 預設、`--strict` exit 1。
- **iOS UI 依賴圖**(`ops/ui_graph.py`): type→type 依賴圖,消費同一份 kgindex records(每個 ref 帶 enclosing-type container,extension 已 collapse 到 nominal),並把 `CatalogScene` 輸出的 `catalog_index.json` 接進來。邊 A→B = type A 引用 type B;查 `--type <Name>` 看正向 deps + 反向 users(改它的 impact set)+ external 引用數,查 `--surface <Catalog Surface>` 看該 surface backing view 的 deps + 哪些 catalog surface 依賴它；`--json`(schema `kg.ui.graph.v1`)出 nodes+edges,且每個 node 帶 `surface` list；`--dot` 出 Graphviz。輸入三模式同 ui_deadcode；catalog index 可 `--catalog-index <path>` 顯式指定，`--records-json` 模式會自動抓 sibling `catalog_index.json`。USR-keyed 節點 = surface `backing` 型別名 ↔ 引用網的接點(健康 UI 管理系統的依賴可視層)。
- **Catalog review desk / UITest run review**(`UIreview.html`，2026-06 自 review.html 改名): catalog snapshot 的 `UIreview.html` 是以 surface 為管理單位的離線 control plane，不只看 PNG；每個 surface 卡直接顯示 `backing` production view、`depends`(它依賴的 type 數)、`impacts`(依賴它的 catalog surface 數) 與 graph health，資料源是同 artifact root 的 `catalog_index.json` + `ui_graph.json` + `review_manifest.json`。UITest scope 另有常駐 workspace：`./start.sh` 會刷新並開 `build/snapshots/uitest-runs/UIreview.html`，即使沒有任何 run 也會掃 `ios/BooksAndVocabUITests/*UITests.swift` 顯示 flow / test methods / run command，狀態為 `never-run`；catalog gallery 只能用 `./start.sh --catalog` 明確開啟，禁止 silent fallback。單次 run 專屬 artifact 由 `ios_test.sh --ui` 產生：step screenshots、full/quick4 contact sheet、`review_manifest.json`、測試 log 與全程錄影收斂到 `build/snapshots/uitest-runs/<run>/UIreview.html`，並在 `test --json` / `runs --json` expose `uiVisualReview.reviewHtml`；workspace 依 flow / variant 監控每個 UITest 最新一次結果與 `lastRunAt`，同一 flow/variant 新跑會取代舊 entry。看播放/導覽影片不必先把 `build/snapshots/uitest-videos/` sync 進 catalog artifact。
- **遠端分支收斂審計**(`ops/branch_audit.sh`): 以 `origin/main..<branch>` commit reachability 為真相,GitHub PR 狀態只作輔助 metadata；分類 `safe-delete` / `open-pr` / `merged-pr-but-ahead` / `orphan-ahead` / `stale-ahead`,支援 `--json`(`kg.branch_audit.v1`)與 `--delete-merged --dry-run|--yes`。cleanup all 前用它擋「PR 已 merged 但 branch 還有 main 不可達 commit」的假安全感。
- **Review receipt 審計**(`ops/review_audit.sh`): 把 `docs/sop/review_discipline.md` 的逐項 review 規範機械化。預設審 `origin/main..HEAD`，commit 必須帶 `Reviewed-by:` 或合法 `Review-Exempt:`；支援 `--base` / `--rev-range` / `--json`，JSON schema=`kg.review_audit.v1`。任一 commit 缺 receipt 或 exemption reason 不合法時 exit `2`，用來擋「口頭說有 review、歷史上卻沒有 receipt」。
- **Capability matrix**(`ops/capability_matrix.py`): repo-level agent capability contract。把關鍵 control-plane surfaces 映射成 `minimumTier`（`observer` / `operator` / `editor` / `production-capable`）、`sideEffect`、`scope`、固定 command，支援 `--json` schema=`kg.capability_matrix.v1` 與 `--tier` 過濾。用途不是授權系統本身，而是讓 agent 在碰 production / local-build / raw escape hatch 前，先機械確認自己正在跨哪條能力邊界；目前覆蓋 repo audit、docs control-plane、release、devops、iOS ops、capture profile、podcast ops、llm_eval。
- **KG meta skills**(`.claude/skills/kg-router`,`.claude/skills/kg-docs-control-plane`,`.claude/skills/kg-receipt`): 新對話冷啟動、docs 控制面判讀、任務 receipt 三段閉環。它們只做路由/判讀/收尾，不保存 live state；live state 仍由 typed tools 與 docs registry/SoT 決定。
- `podcast_upload.sh`: `series_id` regex + `createdAt` idempotent + rsync `--partial-dir --delay-updates` 原子 + 遠端 `index.json` flock
- **Podcast producer dashboard**(`lab/podcast/monitor/`,localhost:8765):workspace 列表 sidebar(search / 狀態 chip / sort recent⇄A→Z / mobile drawer,localStorage 持久)+ 每 workspace 富 summary(status `running|done|failed|awaiting|idle|fresh`、`milestones[]` 四產物關卡 + `gates[]` 兩道人工核准 gate 三態(passed/awaiting/pending)、progress、cost LLM/TTS split、episodes、last_updated、active_job 透過 `<ws>/.pipeline_job_id` sidecar 反查)+ 側欄進度改**三相雙閘軌**(PLAN/SCRIPT/AUDIO 三相條 + 兩 gate glyph,awaiting 琥珀脈動;subtitle 折進 audio 相細底線)+ 內嵌試聽(SRT chat-bubble 渲染:解析 `[Speaker]` 前綴將連續同講者 cue 合併成氣泡,兩位講者分左右兩色;每字 click-to-seek + 高亮同步保留)+ episode chip 顯示完整 TTS 模型 id(從 `ep_N_<variant>.meta.json` sidecar 讀;舊集數無 sidecar 時 fallback 為 `pro (?)` / `flash (?)` 表世代未知)+ LIVE ACTIVITY feed 把 `[...]` 方括號內容(TTS 情緒 tag / 集數清單)行內高亮成 badge + nav SETTINGS(⚙)面板(localStorage 持久,套用於下一條 pipeline,每旋鈕單一來源:PARALLEL workers(原 nav input 已收斂於此)、TTS MODEL 下拉(建立時凍結進 `.tts_model` sidecar、選非-3.1 family 顯示跨 family 風險紅字);spoiler 仍只在 NEW PODCAST modal)+ NEW PODCAST upload modal(可選 `tts_model`)+ UPLOAD / DELETE / RERUN-STAGE 動作 + **情境式推進鈕**(一顆鈕依狀態變身:awaiting→▶ APPROVE PLAN/SCRIPTS 寫 gate 標記續跑、idle/failed 有未完工→▶ RESUME 純 auto-resume、running→禁用、READY→隱藏)+ RECENT JOBS panel + PUBLISHED ON SERVER 遠端 series 管理(rm + index.json rebuild)。main 欄按 scope 分兩區:**THIS PODCAST**(選中 workspace:KPIs → stage 縱向 timeline → cost → episodes → live activity,band 顯示書名)與 **SERVER · all podcasts**(全域:recent jobs + published,recessed surface);stage 進度改縱向 timeline(spine dot + 連接線進度,running/failed 才顯 pill)。`./start.sh` 預設前景跑(`--bg` 給 pipeline.py auto-launch)
- Post-deploy smoke verify: `system/info` + health + sentry test event
- `backup_verify.sh`: restore drill + integrity check
- pytest pinned in `pyproject.toml [dependency-groups].dev`(修 backend venv 無 pytest)
- **跨平台設計系統地基**: `design-system/tokens.json`(**W3C DTCG 格式**,跨平台 token SoT)經兩條生成鏈出貨 — **Style Dictionary**(`npm run build`,`sd.config.mjs`)→ iOS `DesignTokens.swift`(scalar bridge,禁手改)+ **`ops/gen_web_tokens.py`** → web CSS(`design-system/dist/` + `backend/static/`)。手寫 primitives 源 `design-system/dist/kg-components.css`,複製進官網；已接線 scalar 群組(radius/spacing/type-scale/tracking/elevation,47 值)為 Figma→iOS 真注入,設計師 SOP 見 `docs/sop/figma-token-workflow.md`
- **設計系統三層 guard + CI 強制**: `token_drift_check.py`(**值**:SoT-inversion-aware,已接線解析 `DesignTokens.*` 引用、未接線比 `$swift` literal,含 `AppTag` chip padding/fill)+ `component_fidelity_check.py`(**組裝**:contract-based 守每個 primitive 選用哪個 token 對齊 iOS 元件,如 `.kg-btn` radius md/700、`.kg-chip`↔`AppTag`、`.kg-input` body+hairline)+ `gen_web_tokens.py --check`/`gen_figma_sets.py --check`(**生成**:web CSS/sidecar 無 stale 副本)+ `npm run build:check`(Style Dictionary:`DesignTokens.swift` ↔ tokens.json),聚合入口 `ops/verify_design_system.sh`,由 GitHub Actions CI(`.github/workflows/design-system.yml`,路徑觸發 + `npm ci`)+ `.githooks/pre-commit` 雙重強制
