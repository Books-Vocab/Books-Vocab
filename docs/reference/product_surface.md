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
verified_against: c06dadb1
-->
# Implemented Product Surface

動手前對照,確認不重複建造。功能上線後在此追加 bullet,而非寫在 `CLAUDE.md`。

---

## iOS (`ios/BooksBrowser`)

- **Auth flows**: Apple/Google SSO
- **Bookshelf + reader**: EPUB/TXT/MD/PDF multi-format import + batch select + classified error diagnosis + import progress callback + 書庫下拉刷新（iOS/iPadOS pull-to-refresh）／Mac toolbar 同步鈕觸發帳號背景同步（詞庫/複習/KG，非書本清單；成功彈確認 toast、失敗 warning，經 `ExplicitSync` 與 ⌘R 共用同一回饋政策）
- **Translation/explanation**: context sentence extraction
- **Vocabulary**: capture / list / detail / sync / graph views
- **Graph links**: hide/unhide + bilateral optimistic sync
- **Toast notification system**: capsule toast + sheet overlay
- **Graph thumbnail** + health blob
- **Today review**: 4-state phase matrix + `PostExampleMetrics` + 跨裝置保存完整複習事件，月曆與每日明細顯示真實 `ReviewRecord` + Settings「凍結複習時鐘」(due/reviewed 計算、notebook CTA、stats forecast、graph ratio/row progress 使用 paused reference date;已到期卡仍可手動複習)
- **Stats overview**: `StatsPresenter` full state matrix
- **Settings + account deletion**: paywall Free/Pro 對照 + 安全確認 + Pro badge + CSV export via `VocabularyExporter` + review progress pause/freeze toggle
- **Onboarding**: empty-state login entry points + Welcome 3-step walkthrough (sticky login CTA)
- **AppStartupRecoveryView** 三層 recovery
- **App-intent / background sync** + preview matrix
- **Mac Catalyst** (macOS 15.0+): iOS app runs natively on Mac via Catalyst (`SUPPORTS_MACCATALYST`, App Sandbox); 原生視窗尺寸(最小 900×640 / 首發 1100×760 置中)+ Reader 沉浸閱讀(EPUB/PDF 隱藏 title bar,`MacWindowChrome`); 頂部選單列 + ⌘ 快捷鍵(設定 ⌘,、同步 ⌘R、新增單字本 ⌘N、匯入 ⌘I、搜尋單字 ⌘F、複習 ⌘⏎、複習快捷鍵說明;`MacMenuCommands` 走 app-global `AppCommandCoordinator` intent + 畫面動作 via `FocusedCommandValues`/focusedSceneValue,全 menu code gated Catalyst-only); 指標 hover 回饋(卡片浮起 `appHoverLift` / 可點列染色 `appHoverRowTint`) + 可拖曳分隔線欄寬游標(`MacColumnResizeCursor`,`UIPointerInteraction`); podcast series 右鍵/長按追蹤切換
- **Notebook robustness**: `resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense
- **Notebook bookshelf**: LazyVStack book-row list + `NotebookCard` HStack layout (cover 40% left + metadata right, fixed-height 72pt rows) + serif italic name (`AppFonts.serif(17, bold).italic`) + active small dot (5pt, darken 0.5) + 1pt darken rule overlay + cover system (12-color Morandi palette + 6 SwiftUI Canvas patterns + unified noise pattern 0.04 + PhotosPicker custom image) + `N 詞` monoLabel + ProgressCapsule (cover-tinted fill, 4pt) + 條件 due dot (warning) + 空 notebook placeholder + page section header `今日複習` + inline pill cluster (`VocabReviewCTAPill` + filter + 新增, replaces VocabReviewBanner + toolbar buttons) + pending sync via TipView → SyncView integration + export dual-entry + sort menu + empty-state CTA + `NotebookCardActions` reusable context menu + dark mode cover auto-darken via `NotebookPalette.darken`
- **Podcast player**: audio + sentence-level SRT highlight + reader-parity 翻譯 via `VocabularyContextProtocol`（字幕選取 edit menu：「翻譯」依字數分流——單字→word path（加入詞庫 + 去重）、片語→phrase path；「解釋」對單字 + 片語皆出現，對齊 reader gate-free edit menu）+ phrase 長按整句 + auto-pause-on-lookup + subtitle size S/M/L/XL/XXL + series 追蹤 toggle + 已追蹤浮上書庫頂端 + per-user progress sync to backend + YouTube-style buffered seek-bar overlay + tap-to-warm AVFoundation connection (DNS/TLS/Range pre-fired during navigation push) + bookshelf-appear predictive prefetch of followed-series first episode + inline subtitle in metadata.json (zero subtitle RTT) + background episode download (URLSession.background, file:// local-first playback, context-menu Download/Cancel/Remove, compact progress ring in row) + 睡眠定時 (5/15/30/60min + end-of-episode, wall-clock DispatchSourceTimer) + 字幕 follow-mode（iPhone/iPad 拖曳隱式脫離；Mac Catalyst 常駐明確 toggle「停止跟隨 ⇄ 追隨當前」，因 indirect scroll 不觸發 DragGesture；捲動提前約 0.8s lead，下一句被講到前先滑到中央，seek 時 pin 回當前句）+ **獨立頂層「播客」section**（`PodcastHomeView`，iOS TabView 第 2 / Catalyst sidebar；軸 B Phase 3，podcast 不再經書架進入）：串流首頁 = 繼續收聽橫排 shelf（跨 series 最近未完成，`PodcastShelf`+`PodcastContinueRailCard`）+ 所有節目 grid（followed 排前+star）；series→episode→player 全 value-based push 在自有 `NavigationStack` + **連續播放 auto-advance**（本集播畢自動續播同 series 下一可播集，`PodcastQueue` entitlement gate：free 播完 ep1 不跨集、guest 不續）+ **分層授權 UX（guest/free/pro）**：客戶端 tier policy `PodcastAccess`（鏡射後端 `podcast_access.py`，由 `subscriptionManager.hasProAccess` + token 存在推導）；訪客可瀏覽 catalog（`optionallyAuthedData` 無 token 亦放行），但 episode row／hero CTA 鎖定（`lock.fill` badge）、tap 彈 `LoginSheet`；free 只開 ep1（hero「免費試聽 3 分鐘」→ player 播放獨立 `preview.*` 並顯示 brand 試聽條 + 升級 CTA），ep2+ 鎖定 tap 彈 `SubscriptionPaywallSheet`（`PaywallSource.podcast`）；player 自帶防禦式 gate（deep-link/continue-playing 直達非可播集 → `lockedGateView`，不載入音訊）。pro 全開。`PodcastEpisode` 新增 `previewAvailable`/`previewDurationSec`
- **Auto-sync**: 60s cooldown + toggle onChange + 離線→連線恢復時重新評估 pending queue
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
- **Vocabulary / graph-link APIs**: hide/unhide/blocked pairs + `/api/vocab/review-events` 完整複習事件同步（client UUID 冪等、刪卡後事件仍保留）
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
- **Podcast API（分層授權 guest/free/pro）**: `/api/podcasts*`（手刻 Range/206 音訊串流 + `ep_num` Path 驗證；S3 模式 audio 副檔名由 metadata `audioFormat` 決定，相容 legacy mp3）。**訪客可瀏覽** list/detail/cover（`get_current_user_optional`）；`audio`/`subtitle` 同一 tier gate — guest→`401 {code:auth_required}`（須登入才能播）、free→只能聽每 series **ep1 的 `preview.*` 試聽片**＋讀 ep1 逐字稿（其餘 `403 {code:upgrade_required}`，付費集逐字稿不外洩）、pro→full；policy 在 `podcast_access.py`（牆統一、無 per-series 旗標）。free 試聽走**獨立預生成 `preview.*` 物件**（progressive MP4 單 moov 無法乾淨 byte 截斷）。+ series 封面 proxy `GET /api/podcasts/{sid}/cover`（image/png，缺則 404 → client 退程序化封面）+ per-user podcast progress LWW SQLite store（legacy 無認證 `/api/podcast-media/` 掛載已於 2026-05 移除）。生成 pipeline 工程文檔:`docs/sop/podcast_pipeline.md`
- **Podcast 上傳閉環 + drift 安全網**: pipeline 終端 `publish` stage 合成完成即自動上傳 S3 + verify（無手動步驟）;`ops/podcast_backfill_disk.py` served-disk→S3 回填 + `--check` reconcile;monitor `GET /api/remote/reconcile` 報 workspace↔S3「合成了但沒上傳」drift
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

## Chrome Extension (`chrome-extension/`)

- Side panel vocab lookup
- Chrome notebook scope + 管理：side panel 先讀 `/api/notebooks`，以 `active_notebook_id` 持久化目前單字本，`GET /api/vocab?notebook_id=...` 只顯示該本；若儲存的 notebook 已不存在則回落 canonical `default`。content popup 加詞讀同一 storage key，使網頁選詞寫入目前單字本而非永遠 default。scope row 提供 icon-only 新增 / 重新命名 / 刪除（default notebook 不可刪），name-only sheet 走 backend notebook CRUD，名稱驗證 1..100 字元。
- 單字本 filter chip 多選過濾複習狀態（空=全部）+ sort pill dropdown 切換 4 種排序（複習優先 / 字母序 / 最近新增 / 難度），對標 iOS `KGVocabView` 管線（state filter → search → sort）；無匹配顯示空狀態
- 單字本 row 點開全幅 word-detail push 面板（覆蓋於 list 上保留 scroll/search/filter）：hero(詞+詞性+難度+TTS) → 例句(目標詞 highlight，`markWordInExample`+`parseInlineMarks` 對標 iOS) → 釋義/定義 → 搭配 → 變化形 → 知識連結(對比/相關 group，本地語料命中可導航 push/back) → 複習進度 → metadata footer → 來源；TTS 走裝置端 Web Speech API；top bar share action 先走 Web Share、fallback clipboard，純文字格式由 `vocabPlainTextExport` 對齊 iOS `CardDocument.plainTextExport`；唯讀無 mutation
- 跨 context 詞庫刷新：頁面 popup 加入單字後 background bump storage `vocab_dirty`，side panel `storage.onChanged` → 非破壞性靜默刷新（保留 search/filter/sort/scroll/開啟中的 detail）
- **加詞本地暫存 → sync outbox（對齊 iOS）**：選詞加入不再即時裸 POST，改 optimistic enqueue 進 `chrome.storage` 的 `vocab_outbox`（每筆保留 `notebookId`；`pending/synced/failed` 狀態機鏡像 iOS `syncStatus`）+ 立即回 ack，背景 single-flight flush 依 notebook 分批 `POST /api/vocab?notebook_id=...` 收斂、失敗自動重試（網路抖動不丟詞；同 word 不同 notebook 不互相 dedup/收斂）；service worker spin-up 時 drain 殘留。flush 收斂後自動觸發同 notebook server enrich（`POST /api/pipeline?notebook_id=...`）並以 `chrome.alarms` 輪詢 `X-Pipeline-Pending` re-pull 回填，使 chrome 加的卡也長出詞性／例句／發音（不再永久裸卡）；sidepanel 即時顯示目前 notebook 的 pending／失敗詞（置頂 + 狀態標記「同步中／待重試」，對齊 iOS 待同步可見性）
- 閱讀選詞翻譯
- 閱讀 popup 加 Web Speech API 朗讀 + 明確 × 關閉鈕（sticky head，loading/translated/saved 各態皆在）；長文 popup `max-height` + 內部捲動
- 選字翻譯全域開關(options 頁「選字翻譯」master switch,storage key `kg_enabled` 預設開;content.js mouseup gate,跨分頁 onChanged live-sync 免重整)
- options 設定頁「翻譯語言」（source→target，經 background → `GET/PUT /api/user/config`；source∈{en,ja,ko,fr,de,es}、target∈{zh-Hant,zh-Hans,en,ja,ko}，登出禁用 + 存檔失敗 revert）
- options 帳號區「Pro 訂閱態」徽章（`GET /api/user/entitlements` 的 `pro.is_active`/`plan_name`；登入後載入，無法判定時隱藏）
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
- **iOS App Store/TestFlight 發版**(`ops/ios_release.sh`): archive→export→`--upload` 出 `.ipa`;ASC API key 簽章基建(無需手動匯入 distribution 憑證)+ manual signing(Apple Distribution cert + `KG App Store` profile)+ `--upload` 前 build-number guard(擋 TestFlight 重複)+ 共用 iOS build lock
- **App Store Connect 全表面控制台**(`ops/asc.sh`): 主體 codemagic CLI 包裝 + raw 旁路(唯讀 `ops/asc_get.py`、寫入 `ops/asc_write.py` 一般化 PATCH/POST/DELETE)。**唯讀**涵蓋 App 資訊/版本文案/審查狀態+備註/送審佇列(submissions)/截圖/分類/用戶評論/無障礙/訂閱+IAP+定價/訂閱優惠(sub-offers)/發布方式+分階段發布(release-plan)。**寫入**(皆預設 dry-run、`--yes` 才真送,經單一 `emit_write` gate):版本文案(set)/審查資訊(set-review)/App 層本地化 name+subtitle+privacy-url(set-appinfo)/EULA/內容版權/分類/年齡分級/評論回覆(reply-review)/訂閱名+描述+備註+價格(set-sub-*,改價動真實計費有 ⚠+保護既有訂戶)/發布方式(set-release-type)/分階段發布(phased start|pause|resume|complete|cancel)。**刻意不做**:submit-for-review/撤回送審、IAP 寫面(KG 無一次性 IAP)、訂閱優惠建立(走 GUI)、App 隱私權營養標+截圖上傳(無 public API);被拒原因 Resolution Center 文字 API 不可讀(須 GUI)。細節見 `docs/sop/ios.md §發版`
- **版號發布統一 CLI**(`ops/release.sh`): `status`(各 component 待發版 commit + 建議版號)/`changelog`/`bump`/`publish`(commit 版號檔+tag+push,dry-run 預設、`--yes` 才真送);`/release` slash command 為薄路由。委派 primitive `ops/release_bump.sh`/`ops/release_changelog.sh`(前身 `scripts/`)。無 tag-triggered CI,tag 為版本標記
- `podcast_upload.sh`: `series_id` regex + `createdAt` idempotent + rsync `--partial-dir --delay-updates` 原子 + 遠端 `index.json` flock
- **Podcast producer dashboard**(`lab/podcast/monitor/`,localhost:8765):workspace 列表 sidebar(search / 狀態 chip / sort recent⇄A→Z / mobile drawer,localStorage 持久)+ 每 workspace 富 summary(status `running|done|failed|awaiting|idle|fresh`、`milestones[]` 四產物關卡 + `gates[]` 兩道人工核准 gate 三態(passed/awaiting/pending)、progress、cost LLM/TTS split、episodes、last_updated、active_job 透過 `<ws>/.pipeline_job_id` sidecar 反查)+ 側欄進度改**三相雙閘軌**(PLAN/SCRIPT/AUDIO 三相條 + 兩 gate glyph,awaiting 琥珀脈動;subtitle 折進 audio 相細底線)+ 內嵌試聽(SRT chat-bubble 渲染:解析 `[Speaker]` 前綴將連續同講者 cue 合併成氣泡,兩位講者分左右兩色;每字 click-to-seek + 高亮同步保留)+ episode chip 顯示完整 TTS 模型 id(從 `ep_N_<variant>.meta.json` sidecar 讀;舊集數無 sidecar 時 fallback 為 `pro (?)` / `flash (?)` 表世代未知)+ LIVE ACTIVITY feed 把 `[...]` 方括號內容(TTS 情緒 tag / 集數清單)行內高亮成 badge + nav SETTINGS(⚙)面板(localStorage 持久,套用於下一條 pipeline,每旋鈕單一來源:PARALLEL workers(原 nav input 已收斂於此)、TTS MODEL 下拉(建立時凍結進 `.tts_model` sidecar、選非-3.1 family 顯示跨 family 風險紅字);spoiler 仍只在 NEW PODCAST modal)+ NEW PODCAST upload modal(可選 `tts_model`)+ UPLOAD / DELETE / RERUN-STAGE 動作 + **情境式推進鈕**(一顆鈕依狀態變身:awaiting→▶ APPROVE PLAN/SCRIPTS 寫 gate 標記續跑、idle/failed 有未完工→▶ RESUME 純 auto-resume、running→禁用、READY→隱藏)+ RECENT JOBS panel + PUBLISHED ON SERVER 遠端 series 管理(rm + index.json rebuild)。main 欄按 scope 分兩區:**THIS PODCAST**(選中 workspace:KPIs → stage 縱向 timeline → cost → episodes → live activity,band 顯示書名)與 **SERVER · all podcasts**(全域:recent jobs + published,recessed surface);stage 進度改縱向 timeline(spine dot + 連接線進度,running/failed 才顯 pill)。`./start.sh` 預設前景跑(`--bg` 給 pipeline.py auto-launch)
- Post-deploy smoke verify: `system/info` + health + sentry test event
- `backup_verify.sh`: restore drill + integrity check
- Chrome extension release bundle script + tests(Chrome manifest `version` 發行規格守門 + zip 排除 test/dev tools)
- pytest pinned in `pyproject.toml [dependency-groups].dev`(修 backend venv 無 pytest)
- **跨平台設計系統地基**: `design-system/tokens.json`(**W3C DTCG 格式**,跨平台 token SoT)經兩條生成鏈出貨 — **Style Dictionary**(`npm run build`,`sd.config.mjs`)→ iOS `DesignTokens.swift`(scalar bridge,禁手改)+ **`ops/gen_web_tokens.py`** → web CSS(`design-system/dist/` + chrome-extension + `backend/static/`)。手寫 primitives 源 `design-system/dist/kg-components.css`,複製進三 web surface(extension + 官網);chrome-extension 三 surface(sidepanel/popup/options)已消費此 primitives,視覺鏡像 iOS。已接線 scalar 群組(radius/spacing/type-scale/tracking/elevation,47 值)為 Figma→iOS 真注入,設計師 SOP 見 `docs/sop/figma-token-workflow.md`
- **設計系統三層 guard + CI 強制**: `token_drift_check.py`(**值**:SoT-inversion-aware,已接線解析 `DesignTokens.*` 引用、未接線比 `$swift` literal,含 `AppTag` chip padding/fill)+ `component_fidelity_check.py`(**組裝**:contract-based 守每個 primitive 選用哪個 token 對齊 iOS 元件,如 `.kg-btn` radius md/700、`.kg-chip`↔`AppTag`、`.kg-input` body+hairline)+ `gen_web_tokens.py --check`/`gen_figma_sets.py --check`/`gen_web_components.py --check`(**生成**:web CSS/JS/sidecar 無 stale 副本)+ `npm run build:check`(Style Dictionary:`DesignTokens.swift` ↔ tokens.json)+ extension `shared/*.test.js`(純邏輯/CSS/outbox/inline drift),聚合入口 `ops/verify_design_system.sh`,由 **repo 首支 GitHub Actions CI**(`.github/workflows/design-system.yml`,路徑觸發 + `npm ci`)+ `.githooks/pre-commit` 雙重強制
