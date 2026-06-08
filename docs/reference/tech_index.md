<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/
  - ios/BooksBrowser/
  - ops/
  - lab/
verified_against: a281cba6
-->
# Technical Reference Index

快速 look up:endpoint / DB / env var / iOS 模組 / ops 腳本叫什麼、定義在哪。
新增 router / table / env var / ops 腳本時,**同 PR 內補一行**。

---

## Backend API Routers (`backend/src/kg/routers/`)

| 檔案 | Endpoint prefix | 用途 |
|------|-----------------|------|
| `auth.py` | `/auth/*` | JWT 驗證、Apple/Google token 交換 |
| `web_auth.py` | `/login`, `/auth/web/{google,apple}/*` | Web OAuth + admin cookie session。`/login` 會 mint `oauth_state` HttpOnly Secure cookie；Google 走 redirect state，Apple 以 SameSite=None state cookie + `response_mode=form_post` 直送 Apple authorize，callback 以 cookie/state compare 防 CSRF |
| `user.py` | `/api/user/*` | 設定、entitlements、quota |
| `vocab.py` | `/api/vocab/*` | 單字 CRUD、批量、incremental sync、review state (`/api/vocab/review`)、review events (`/api/vocab/review-events`) |
| `notebook.py` | `/api/notebooks/*` | 筆記簿 CRUD、cover |
| `translate.py` | `/api/translate/*` | quick / phrase / explain |
| `pipeline.py` | `/api/pipeline*` | 圖譜生成流程觸發（iOS sync 收斂後 + chrome-extension 加詞 outbox flush 收斂後皆 `POST /api/pipeline?notebook_id` 觸發 server enrich） |
| `podcast.py` | `/api/podcasts*` | 播客列表 / 媒體 / 進度 / 封面(`GET /api/podcasts/{sid}/cover`,image/png proxy,缺則 404)。**分層授權**(policy 在 `podcast_access.py`):browse(list/detail/cover)走 `get_current_user_optional` 允許**無 Authorization header 的訪客**；若 header 存在但 malformed / token invalid 則 401，不降級 guest；`audio`/`subtitle` 同一 tier gate（`_require_episode_access`）— guest→`401 {code:auth_required}`、free→只給 ep1（audio 服務 `preview.*`、subtitle 給 ep1 逐字稿；其餘 `403 {code:upgrade_required}`）、pro→full（防付費集逐字稿外洩）；`progress` 仍 `get_current_user`，OpenAPI 以 `api_models/podcast.py` response models 固定 schema |
| `podcast_access.py` | — | 播客分層 policy(純函式,免 FastAPI):`resolve_podcast_tier(user|None)→guest/free/pro`(由 auth + `_is_pro` 推導,**無 per-series 旗標**,牆統一)、`is_free_previewable_episode`(`FREE_PREVIEW_EP_NUM=1`)、stem 常數、error code。free preview 走**獨立 `preview.*` 物件**而非 byte 截斷(progressive MP4 單 moov 無法乾淨截) |
| `billing.py` | `/api/billing/*` | App Store 收據與 server-to-server 通知 |
| `system.py` | `/api/system/*` | `/info`、health |
| `admin.py` | `/api/admin/*`, `/admin/*` | dashboard / user detail / logs / test-matrix |
| `static_pages.py` | `/`(landing) / `/privacy.html` / `/support.html` / `/terms.html` / `/guide.html` | 根路徑 landing 首頁(App Store CTA + token device mock)+ 4 法律/支援頁;全吃 `/static/*` CSS、共用 site shell |

`api.py` 另以 `app.mount("/static", StaticFiles(directory=backend/static))`(`if is_dir` 守衛)服務公開頁的設計系統資產(`kg-tokens.css` / `kg-components.css` / `site.css` + `site-motion.js`〔無框架 progressive-enhancement scroll-reveal〕+ `img/`〔og-image / favicon / apple-touch-icon 等 PWA·SEO 資產〕+ brand woff2 字體)。`kg-tokens.css`·`kg-components.css` 由 `ops/gen_web_tokens.py` 生成,不手改;rsync-only-backend deploy 與 Dockerfile `COPY static/` 確保隨容器出貨。

## SQLite Log Stores (`backend/src/kg/`)

| 檔案 | 主要 table | 用途 |
|------|-----------|------|
| `user_store.py` | users / sessions | 帳戶、provider、session |
| `judge_log.py` | `judge_log` | LLM judge 決策追蹤、acceptance rate |
| `translate_log.py` | `translate_log` + cache hits | 翻譯呼叫紀錄、cross-user cache、admin search |
| `pipeline_log.py` | `pipeline_runs` | 圖譜管道 per-run/step timing |
| `token_tracker.py` | `token_usage` | LLM token / cost,provider-aware |
| `llm_error_log.py` | `llm_errors` | 真實 LLM 基礎設施失敗(429/5xx/timeout)記錄；落 DB 前遮罩 bearer/API key/token/password/secret-like 值 |
| `podcast_progress.py` | `podcast_progress` | per-user 播客 LWW 進度 |
| `review_events.py` | `review_events` | per-user 複習事件 append-only log；`event_id` 為 client UUID 冪等主鍵，供 iOS 月曆與每日明細跨裝置同步。pull 以 server 端單調遞增 `ingested_at` 為 cursor watermark（回應含 `cursor` 欄位），用 ingestion 序而非 `reviewed_at`，避免遲到事件漏拉。**SoT 回溯帳本**:已加寬 SRS 前後快照欄(`interval_before/after`、`next_review_before/after`、`review_count_after`、`streak_after`、`lapse_after`)+ `is_synthetic`(True=一次性回填的合成過去、False=上線後累積的真實事件),供深度研究逐筆還原學習曲線;欄位全 nullable、ADD COLUMN 冪等遷移、新舊 client 互通 |
| `graph_event_log.py` | `graph_events` + `graph_snapshots` | per-user 圖譜 append-only 變更帳本(**SoT 回溯**)。`GraphEventStore` 記 7 種 mutation(`link_added`/`updated`/`hidden`/`unhidden`/`deprecated`/`restored`(deprecated→active,與 unhidden 區隔)/`deleted`)每筆含 confidence/status before+after、`reason`(add/update 帶 link 當前理由)、`source`(`auto`=pipeline / `manual`=使用者 API / `ops`=ops_edit·運維遷移 / `synth`=合成回填)、`is_synthetic`;`event_id` 冪等、`ingested_at` 單調 watermark。共用 `sqlite_ledger.py`(serialized-tx recipe + 單調時鐘)。`GraphSnapshotStore` 存 links 全量快照(`links_json` + `is_synthetic`),`latest()` 以 `(taken_at desc, snapshot_id desc)` 決定式 tie-break;並已提供週期性 checkpoint policy:某 notebook 若尚無 snapshot，第一個真實 mutation 後立刻補一張；之後每累積固定數量 graph events 再補下一張，讓 replay 重建長度有界。攔截點在 `GraphStore`(唯一 100% 覆蓋,pipeline AI 回寫亦經此),emit 走單筆交易批寫，成功寫 event 後再依 provider 解析 live snapshot store 補 checkpoint(LRU 逐出後重建,不丟事件) |
| `admin_audit.py` | `admin_audit_log` | grant/revoke 等管理員操作 |
| `app_store.py` | app store receipts | 訂閱收據 |
| `secret_store.py` | secrets | 加密憑證 |
| `mem_log.py` | (in-memory) | admin in-memory log capture |

Data dir 透過 `KG_DATA_DIR` env 切換。`orphan_scan` 為 cross-DB consistency scanner(`/api/admin/orphan-scan`)。

## Environment Variables

完整清單見 `docs/sop/deploy.md`。此處列分組與代表項:

- **LLM & Embedding**: `GEMINI_API_KEY` / `GEMINI_MODEL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `LLM_PROVIDER_*`(per-call-type 路由) / `LLM_PROVIDER_DEFAULT` / `JUDGE_CONFIDENCE_THRESHOLD`(judge link 接受門檻,default `0.7`;換低校準 judge model 時調低)
- **Auth & SSO**: `JWT_SECRET` / `ADMIN_TOKEN` / `ADMIN_PASSWORD` / `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `APPLE_BUNDLE_ID` / `CHROME_EXTENSION_ID` / `APP_STORE_CONNECT_*`
- **Secret encryption**: `SECRET_ENC_KEY`(可選)— `secret_store.py` 對 `enc:` stored secret 的對稱加密根金鑰,`sha256(SECRET_ENC_KEY)` 派生 Fernet key。**未設時 fallback `sha256(JWT_SECRET)`**(既有部署零破壞)。設了它後,**輪換 `JWT_SECRET` 不再令 stored secret 無法解密**(兩者脫鉤);解密採多金鑰容錯(當前 key 先試,失敗退回 legacy `sha256(JWT_SECRET)`),過渡期無需 re-encrypt migration。
- **Quota & Rate Limit**: `FREE_DAILY_LIMIT_USD` / `PRO_DAILY_LIMIT_USD` / `API_RATE_LIMIT` / `TRANSLATE_RATE_LIMIT` / `KG_ALLOW_SANDBOX_PURCHASE` / `RATE_LIMIT_TRUSTED_HOPS`(匿名請求取 XFF 倒數第 N 段作 rate-limit key,default `1` = 現行單層 Caddy 行為;前置 N 層可信代理時設 `N+1`,見 `host_topology.md`)
- **Log retention**: `JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS` / `LLM_ERROR_LOG_RETENTION_DAYS`
- **Cache**: `TRANSLATE_CACHE_TTL_DAYS`
- **Service / Ops**: `KG_DATA_DIR` / `CORS_ORIGINS` / `KG_LOG_TZ`(ops-side only — 僅 root `devops.sh` 顯示 log 時間用,不影響 backend runtime) / `SENTRY_DSN` / `SENTRY_ENVIRONMENT`
## iOS 模組地圖 (`ios/BooksBrowser/`)

| 目錄 | 用途 |
|------|------|
| `Views/` | 場景視圖(書架、筆記、播客、複習、reader、settings) |
| `Services/` | 後端通訊(`KGService`)、認證、雲同步、analytics、sentry;`KGServing` 拆窄協定 `BackgroundSyncing`(`backgroundSync`+`lastBackgroundSyncError`),`ExplicitSync` 為顯式同步(pull-to-refresh/toolbar/⌘R)政策單一真相(資格 gate `isLoggedIn && !isDemoMode`〔登出/demo no-op〕+ 成功 toast、失敗 warning + read-then-clear) |
| `Models/` | 實體(Book / Notebook / VocabularyEntry / PodcastSeries) + 書籍 sidecar metadata (`BookManifest` / `BookLibraryReconciler`: `Documents/Books/.metadata/*.json`；正常啟動補 manifest-backed missing row / missing manifest / 同檔名去重，裸檔補 row 僅限明確 recovery opt-in；覆蓋 legacy `Documents/EPUBs` / `.icloud` placeholder) + tokens(`AppMetrics` 含 `AppMotion`/`AppSpacing`/`Radius`/`Elevation`;`AppSkin` 拆 `+BaseValues`/`+Environment`;feature-local metrics:`ReaderMetrics` / `TodayReviewMetrics` / `BookshelfMetrics` / `PodcastPlayerMetrics` / `NotebookStackMetrics`)。`DesignTokens.swift` 為 **Style Dictionary 生成**(禁手改)的 scalar bridge — `tokens.json`→`npm run build`→ PascalCase 巢狀 scalar enum(`Radius.Scale`/`Space.Scale`/`Typography.Scale`/`Typography.Tracking`/`Elevation.Steps.Z*`…);已接線 scalar 群組(`AppRadius`/`AppSpacing` scale/`AppFonts.TypeScale`+`Tracking`/`AppElevation`,共 47 值)改為引用 `DesignTokens.*`,顏色/`AppMotion`/`LineSpacing`/`AppSkin` 仍手寫 literal(見「Web 設計系統」) |
| `UIComponents/` | 可重用元件(buttons / cards / banners / toast / skeleton) |
| `Platform/` | iOS / Mac Catalyst 橋接(`PlatformRepresentable` 型別 alias、`PlatformCompatibility` modifier wrapper、`LayoutMode`、`MacWindowChrome` Catalyst 視窗尺寸+沉浸 title bar、`MacMenuCommands` Catalyst 頂部選單列+⌘ 快捷鍵、`AppCommandCoordinator` app-global menu intent、`FocusedCommandValues` focusedSceneValue 動作通道) |
| `Localization/`,`*.lproj/` | i18n(en / ja / ko / zh-Hans / zh-Hant) |
| `Debug/` | DEBUG-only — `CatalogScene` + `Scenarios/*Scenarios.swift` + `CatalogPreviewAuth`(Playbook iOS catalog,啟用方式見 `docs/sop/ios.md §Playbook Catalog`)。`CatalogScene.Manifest` 是 surface taxonomy 的 SoT:每個 category 宣告 `CatalogSurface{kind,feature,screen}`,`indexJSONData()` 吐 `catalog_index.json` 給離線 gallery 消費(取代像素/regex 猜測);契約由 `CatalogCoverageTests` 強制(一螢幕一 `featureScreen`、無重複/缺漏/漏宣告 kind) |

iOS 大規模重構後執行 `ops/gen_ios_baseline.sh` 更新 `docs/snapshot/ios_baseline.md`。
PR 開出前(或 CI)跑 `ops/docs_lint.sh` 日常 gate,確認 `docs/registry.yml` 與本次 changed docs 無 ERROR,並檢視 registry impact hints 是否需要同步文件；全 repo doc debt 盤點才跑 `ops/docs_lint.sh --audit` / `--all`。

## iOS — i18n / Locale 模組 (`ios/BooksBrowser/`)

| 元件 | 路徑 | 用途 |
|------|------|------|
| `L10n` | `Localization/L10n.swift` | string / format 三層 fallback(current → en → key);format 走 NSString 觸發 plural rule |
| `AppLanguage` / `AppLanguageStore` | `Models/AppLanguage.swift` | 5 語言選單 + UserDefaults + iCloud KV;`effectiveLanguage` 解析 `.system`;`locale` vs `formatLocale` 分流 |
| `LocaleAwareFormatter` | `Models/LocaleAwareFormatter.swift` | 跟 AppLanguage 的 thread-safe DateFormatter/Number/Relative cache,format-in-lock,語言變更時 invalidate |
| `Localizable.stringsdict` | `<lang>.lproj/` | NSStringPluralRuleType plural variations;新增 key 流程見 `docs/sop/i18n_plural_keys.md` |
| `TranslationLanguage` | `Models/TranslationLanguage.swift` | 翻譯來源/目標語言;UserDefaults + iCloud KV + updatedAt LWW;預設值讀 `Locale.preferredLanguages`(script-aware) |
| `ReviewSettings` / `ReviewSettingsStore` | `Models/ReviewSettings.swift` | 複習設定 + **pause review clock**;**mode/自訂 SRS 參數與 pause 各自三層** UserDefaults + iCloud KV + updatedAt LWW(`ReviewModeLWW` / `ReviewClockLWW` 整組原子),登入經 `/api/user/config` 的 `review_mode` / `review_clock` push/fetch + rollback、server cold-start wins;autoplay 純本地 |
| `KGFeatureFlags` | `Models/KGFeatureFlags.swift` | iOS-side feature gates(目前控 `serverTranslationLwwEnabled` / `serverReviewClockLwwEnabled` / `serverReviewModeLwwEnabled` / `vocabularyLangPayloadEnabled`) |
| `AppFonts.cjk{Sans,Serif}FallbackName` | `Models/AppFonts.swift` | 依 effectiveLanguage 切 CJK fallback(PingFangTC/SC、Hiragino、AppleSDGothic) |
| `SpeechService.voiceCode(for:)` | `Services/SpeechService.swift` | TranslationLanguage → BCP-47 region 對 AVSpeechSynthesisVoice 的 mapping(zh-Hant → zh-TW) |

## Ops 腳本 (`ops/`)

| 腳本 | 用途 |
|------|------|
| `ios_ops.sh` | iOS ops 統一入口(agent 優先用):`status`(`--json` schema `kg.ios.status.v1`,只回 project/Organizer/TestFlight quick summary)、`build`/`test`/`archive`(委派 primitives；一般 `build --json` / `test --json` 由 façade 執行 delegate 後回傳 `kg.ios.run.v1`，內嵌 `kg.ios.diagnostics.v1`；`archive --json` 回 `kg.ios.archive.v1` 並拆出 `archive/export/upload` 三段語意；`test --cache-status|--prepare-cache|--clean-cache --json` 保留原生 `kg.ios.test-cache.v1`。三者 verdict `timings.lockWaitMs` 統一記錄 `/tmp/kg-ios-build.lock` 排隊等待時間，build/test/release 同義，讓 agent 區分「排隊久」vs「執行久」，snapshot timing surface 也會 passthrough 新增 timing 欄位)、`archives`(Organizer `.xcarchive` 查詢)、`issues`(xcodebuild log diagnostics)、`logs`(runtime log show + 噪音過濾；`--follow --json` 逐行輸出 `kg.ios.log-stream.v1`)、`sentry`(iOS Sentry wiring 摘要；`--json` schema `kg.ios.sentry.v1`，`issues[]` 為 wiring failure 單一真相——doctor verdict / snapshot nextActions / sentryWarnings 全衍生自此,新增 wiring check 只改 `sentry_summary_json` 一處)、`doctor`(read-only release readiness；`--json` schema `kg.ios.doctor.v1`，直接內嵌 sentry 與 `summary.verdict/counts`)、`workflow release`(read-only 發版步驟編排；`--json` schema `kg.ios.workflow.v1`)、`gate release`(read-only release hard-stop verdict；`--json` schema `kg.ios.gate.v1`；exit code `0=pass`/`1=warn`/`2=block`)、`xcode`/`environment`(read-only Xcode/project/destination/simulator inventory；`--json` schema `kg.ios.xcode.v1`)、`simulator`/`sim`(booted simulator / app data container / app process 狀態；host-side process probe；所有 action 都回 `timings` 與 `kg.ios.simulator.v1`)、`catalog prepare|snapshots|clean`(Playbook catalog 截圖控制面；`snapshots` 支援 `--group`/`--scenario`/`--reuse-build` 與 `--dataset`/`--dataset-file`，先注入 snapshot test process，必要時 fallback 到 simulator 暫存檔。observability:長 xcodebuild 階段(build-for-testing/test-without-building/full-test)發 stderr phase heartbeat,stdout 維持純 `kg.ios.catalog.v1` JSON;`--reuse-build` cache-miss 回頂層 `status:"cache-miss"`(非泛 error)+ `catalog-cache` error 帶 hint;`uniform-image-detected` 改走 `validation.status:"warn"` / 頂層 `status:"warn"`，不再把已生成 PNG 誤判成 fatal error；成功複製 PNG 後會在同一個 `out_root` 自動生成 `review.html` / `review_manifest.json` / `review_state.json` sidecar；**無 scope 的 full run 若未顯式指定 `--out-root`，還會自動持久化到 `build/snapshots/catalog-full-<UTC timestamp>/`，並在 payload 的 `workspaceArtifact` 回傳新 artifact 路徑**；失敗時 salvage simulator container 內已生成 PNG(`artifacts.containerPngCount` + `copy.salvaged`,errors 內 `catalog-salvage` 為 info note,可區分「未生成」vs「生成但未複製」))、`runs`/`reports`(read-only 最近 build/test/archive verdict + artifact path + 內嵌 `kg.ios.diagnostics.v1`；`--json` schema `kg.ios.runs.v1`)、`snapshot`/`dashboard`(read-only 一次拉 readiness/workflow/gate/sentry/xcode/simulator/runs；共用 `kg.ios.snapshot.v1` formatter，第一屏直接給 `summary.verdict/counts/nextActions/timings`，並內嵌 workflow/gate/sentry/xcode/simulator/runs/diagnostics)、`commands`/`capabilities`(read-only 自描述 catalog；`--json` schema `kg.ios.commands.v1`，同步列出穩定 child schema)。高風險 upload 仍只在 `archive --upload` 明示時發生。測試 `ops/test_ios_ops.sh` + `ops/tests/test_ios_diagnostics.py` |
| `capture_profile.py` | capture/行銷編排層與 screenshot 主 orchestrator：把 `ops/devops_kg_safe.sh ops-edit ...` 的 demo 資料造景、`ops/ios_ops.sh catalog snapshots --dataset-file ...`、`promotion/screenshots/scripts/frame_catalog_screenshots.py` 的本地 iPhone 套框、以及 `promotion/screenshots/scripts/render_screenshots.py` 的最終 marketing renderer 收進單一 profile/workflow。profile schema:`kg.capture.profile.v1`，描述 `materialize(uid, seedFile, expectationFile?, steps[])`、`snapshot(datasetFile, destination, groups/scenarios)`、`render(...)`，並用 `shots[]` 定義 `sourceScenario`、`appearance`、`copy.title/subtitle`、`outputName`；runner schema:`kg.capture.run.v1`，支援 `plan` / `materialize` / `verify` / `snapshot` / `render` / `run` / `derive-expectation`。安全模型:預設 dry-run，不加 `--commit` 不會讓 `ops-edit` 真寫入；若 profile 設 `materialize.expectationFile`，`verify` 會呼叫 `ops-cli world-diff` 做 expected-vs-actual audit，而 `run --commit` 會在 snapshot 前先驗證 world；`run` 在 dry-run 下會把 materialize/verify 留為 planned steps，但仍可跑 snapshot→frame→render；若 `--reuse-build` 命中 stale cache，會自動先跑 `catalog prepare` 再重試 snapshot。`derive-expectation <profile>` 從 `seedFile + materialize.steps` **純宣告**導出 `kg.ops_world_expectation.v1`(`backend/src/kg/ops_world_expectation.py:derive_expectation`，不讀 DB)，寫回 `expectationFile`(`--out` 覆蓋路徑、無則印 stdout、`--check` 對既有檔做 drift guard 回非零);防 tautology 的關鍵是只導 verbatim-safe 欄位 = `ops_edit` 直寫 ∩ `project_user_world` 有 surface(故 notebook `name/cover_pattern/color`、card `content/meaning`、link `from/to/kind`、config `review_clock.is_paused` 導出;card `review` 聚合、`pos`(寫入但 projection 不撈)、active-notebook(name→id 轉換)刻意不導,避免 false-fail / tautology)。`marketing_demo_expectation.json` 即由此命令再生的 generated artifact(手寫易漏斷言)。範例 profile:`ops/capture_profiles/marketing_demo.json` + `marketing_demo_expectation.json` |
| `catalog_review_entry.py` | catalog review artifact 入口：`current` 從 `build/snapshots/*/review_manifest.json` 掃描現有 artifact，先偏好 `isUsable=true` 的 artifact，再以**名稱時間序**選出最新 blessed artifact（不再把「圖數比較多」誤當成「更新」），並輸出 `reviewHtml` / `reviewManifest` / `promiseCounts` / `heroCandidates` / `staleArtifacts` / `supersededArtifactCount` 摘要；`serve [--port]` 會先停掉同 port 既有 listener，再以 blessed artifact root 啟本機 `http.server` 直接服務 `review.html`；`prune-stale [--dry-run]` 可刪掉 `totalImages=0` 的空 review 殼；`prune-superseded [--dry-run]` 可刪掉較舊但仍可用的 artifact，只保留最新 blessed 一份。適合 agent/human 在多份 catalog 輸出並存時先解「該看哪份」與「本機快速預覽」兩個問題。測試：`ops/tests/test_catalog_review_entry.py` |
| `catalog_review_cli.py` | catalog review / UI asset gallery CLI：`summary`/`show`/`list`/`stats`/`report` 查 artifact 與單張資產、`gaps` 查 surface 層 lane-aware 覆蓋缺口（哪些可上架 surface 缺哪些 ship-critical 狀態，machine 面對應 gallery Coverage 視圖）、`mark`/`apply` 寫 review state、`verify`/`repair`/`doctor` 做 sidecar 健康檢查與操作建議，另有 `hero`/`coverage`/`cleanup` shortcut 視角。輸入是 `review_manifest.json + review_state.json`，主用途是離線審圖、批量標記、以及對 `review.html` 內的 `assetID/permalink` 做機器可讀操作。lane/feature/screen taxonomy 由 snapshot run 吐的 `catalog_index.json`（iOS source SoT）決定，缺檔才降級為透明邊緣像素 + title regex heuristic（見 `catalog_review_taxonomy.build_taxonomy(declared=)`）。測試：`ops/tests/test_catalog_review.py` |
| `catalog_contact_sheet.py` | UI 資產 montage 工具：把 N 張 catalog PNG 合成**一張**帶 label 的 contact sheet，讓 agent 一次 `Read` 看多張畫面、省 image token（機器臉看圖的正解，取代 preview/headless 瀏覽器）。filter 走 manifest：`--surface`/`--lane`/`--facet`/`--feature`/`--appearance light\|dark\|both`/`--limit`/`--cols`，印出合成 PNG 路徑供 Read。PEP723（Pillow 經 `uv run --with pillow` ephemeral，lazy import 故純 grid 邏輯仍可在 backend venv 測）。測試：`ops/tests/test_contact_sheet.py` |
| `ios_diagnostics.py` | iOS diagnostics adapter：`xcresulttool get build-results` 為 build/archive 優先資料源，抽官方 `.xcresult` 的 `errorCount`/`warningCount`/issues；`--kind test` 用 `xcresulttool get test-results summary/tests/metrics` 抽 executed/failures/failing tests、`testBodyMs`/`xcresultSessionMs` 與 `XCTApplicationLaunchMetric` 的 `AppLaunch average/min/max/samples`。raw xcodebuild log parser 只作 fallback，分類 Swift 6 concurrency、StoreKit config、SPM、signing。文字輸出第一屏 summary，`--json` 給 agent/CI。`ios_build.sh` / `ios_test.sh` / `ios_release.sh` / `ios_ops.sh runs|snapshot` 已接線 |
| `ios_archive.sh` | 本機 Xcode Organizer archive 唯讀查詢:`list`/`latest`/`inspect` + `--json`,讀 `~/Library/Developer/Xcode/Archives/**/*.xcarchive/Info.plist` 的 `CFBundleShortVersionString`/`CFBundleVersion`/bundle id/creation date,不 export/刪除/上傳 |
| `ios_build.sh` | iOS Release build,共享 `shlock`;保留 raw xcodebuild log,結束即跑 `ios_diagnostics.py` 顯示 warnings/errors 摘要 |
| `ios_test.sh` | iOS test runner;預設 unit target,支援 `--ui` / `--all-targets` / `--file` / `-g` / `--list` / `--launch-benchmark` / `--cache-status` / `--prepare-cache` / `--clean-cache` / `--ui-launch-profile <standard|ui-smoke>`;unit scope 走 dedicated `BooksBrowserUnitTests` scheme，UI scope 走 dedicated `BooksBrowserUITests` scheme；`--launch-benchmark` 固定跑 `BooksBrowserUITests/testLaunchPerformance`；runner 先走 `simulator ensure-booted`,再用 cache-first `build-for-testing`/`test-without-building` 重用 `.cache/ios-test-derived-data`;UI profile 透過 `KG_UI_TEST_APP_ARGS_JSON` 注入 `XCUIApplication.launchArguments`;verdict JSON 會寫 `timings.bootMs/buildForTestingMs/testInvocationMs/testBodyMs/xcresultSessionMs/xcresultHarnessOverheadMs/appLaunchAverageMs/appLaunchSamples/invocationOverheadMs/xcodebuildMs/totalMs` 與 `cache.status`;`kg.ios.test-cache.v1` 現也會回 `artifacts.buildLog/resultBundle`，讓 `prepare-cache` 失敗時能直接追 build-for-testing 證據；cache JSON schema 會回 `productsReady` / `xctestrunPath` / `buildForTestingMs`;第一屏 diagnostics 另外印 `[ios][test-timing] ...` 與有量測時的 `[ios][perf] metric=AppLaunch ...`;仍保留共享 build lock、heartbeat、`Test.xcresult` + raw log + `[ios][tests]` summary,false-green 執行數優先取官方 `.xcresult`、raw log fallback,build DB lock retry |
| `ios_test_matrix.sh` | 逐 Swift 測試檔隔離跑 BooksBrowserTests(委派 `ios_test.sh`),`--timeout` / `--start-at`,debug 用;最終才跑 all-tests |
| `ios_release.sh` | iOS App Store/TestFlight 發版:archive→export→`--upload`(對外 gate,預設不上傳);archive 階段保存 raw log + `Archive.xcresult` 並跑 `ios_diagnostics.py` 第一屏列 warnings/errors;會寫 `kg_ios_archive_verdict(.json)`，JSON schema `kg.ios.archive.v1`，含 `archive/export/upload` 狀態、artifact path 與 `timings.lockWaitMs/archiveMs/exportMs/uploadMs/totalMs`;manual signing(Apple Distribution cert + `KG App Store` profile,一次性建置與憑證見 `~/.secrets/apple/README.md`);共用 `/tmp/kg-ios-build.lock`;`--upload` 前擋重複 build number;`--key <id>` 選 ASC API key。設定檔 `ios/ExportOptions.plist` |
| `asc.sh` | App Store Connect **全表面控制台**(主體 codemagic CLI,同 `ios_release.sh` 的 `asc()` wrapper)。唯讀:`versions`/`builds`/`metadata`/`info`/`review-status`/`review-detail`/`submissions`/`screenshots`/`categories`/`reviews`/`accessibility`/`subscriptions`/`iap`/`pricing`/`sub-offers`/`release-plan`(codemagic 未暴露者走 raw 旁路 `ops/asc_get.py`,唯讀 GET helper,uv shebang 自帶 pyjwt+cryptography,env 參數化 key;JWT 只在 helper、主檔零 JWT)。寫入(皆預設 dry-run,`--yes` 才真送,經單一 `emit_write` gate):`set`(版本文案 appStoreVersionLocalization)/`set-review`(appStoreReviewDetail)/`set-appinfo`(appInfoLocalization name/subtitle/privacy-url)/`set-eula`/`set-content-rights`/`set-category`/`set-rating`/`reply-review`(customerReviewResponses)/`set-sub-name|desc|review-note`/`set-sub-price`(⚠動計費,preserveCurrentPrice 保護既有訂戶)/`set-release-type`(releaseType)/`phased`(appStoreVersionPhasedReleases start/pause/resume/complete/cancel)——codemagic 未暴露者走 raw 旁路 `ops/asc_write.py`(一般化 PATCH/POST/DELETE helper,body 由 stdin,JWT 只在 helper、主檔零 JWT,4xx/5xx→`{_httpError}`、204→`{_ok}`)。**刻意不做**:submit-for-review/撤回送審、IAP 寫面(KG 無一次性 IAP)、訂閱優惠建立(逐地區高風險走 GUI)、App 隱私權營養標(無 public API)、截圖上傳(無 codemagic 命令);被拒原因 Resolution Center 文字 API 不可讀(須 GUI);`.p8` 路徑 `${ASC_KEY_DIR:-~/.secrets/apple}` 可覆寫。測試 `ops/test_asc.sh`(164 斷言) |
| `asc_text_bundle.py` | App Store Connect 文案 bundle 工具:`dump --output <json>` 一次拉 App 層本地化、EULA、版本文案、版本 copyright、review detail、截圖摘要、訂閱群組/方案/本地化、訂閱價格摘要、試用/優惠摘要、評論、無障礙宣告;`apply <json>` 以 live ASC 為 current 做 dry-run diff,`--yes` 才 PATCH 低風險文字欄位(appInfoLocalization、endUserLicenseAgreement、appStoreVersion.copyright、appStoreVersionLocalization、appStoreReviewDetail、subscriptionGroupLocalization、subscription.reviewNote、subscriptionLocalization)。不送審、不撤回、不上傳截圖、不改價格/發布控制;內建 ASC 長度驗證避免部分寫入。測試 `ops/tests/test_asc_text_bundle.py` |
| `release.sh` | **版號發布統一入口**(對標 `ops_cli.py` 單入口風格):`status`(各 component 自上個 `api/*`,`ios/*` tag 以來的待發版 commit + 建議 semver bump,唯讀)、`changelog <api\|ios>`(委派 `release_changelog.sh`,唯讀)、`bump <api\|ios> <x.y.z>`(委派 `release_bump.sh`,改本地版號檔)、`publish <api\|ios> <x.y.z>`(commit 版號檔 + tag + push,**dry-run 預設、`--yes` 才真送**;preflight 擋 tag 重複/版號未 bump)。**無 tag-triggered CI**,tag 為版本標記、GitHub Release 須手動建。`/release` command 為薄路由。測試 `ops/test_release.sh` |
| `branch_audit.sh` | 遠端分支 reachability 審計:`git fetch --all --prune` 後掃 `refs/remotes/origin/*`,以 `origin/main..<branch>` ahead count 判斷 main 是否已包含該分支 commit,再用 `gh pr list --state all --head <branch>` 補 PR 狀態。分類 `safe-delete`(ahead=0)、`open-pr`、`merged-pr-but-ahead`(PR merged 但仍 ahead,exit 1)、`orphan-ahead`/`stale-ahead`(無 open PR 且 ahead,exit 2);`--json` schema `kg.branch_audit.v1`;`--delete-merged` 預設 dry-run,`--yes` 才 `git push origin --delete <branch>`。cleanup all 前置 gate,防止把 PR merged 誤當 commit 已進 main |
| `review_audit.sh` | review receipt 審計。預設掃 `origin/main..HEAD`，也可 `--base <rev>` 或 `--rev-range <a..b>`；commit 必須帶 `Reviewed-by: <reviewer>` 或 `Review-Exempt: <reason>`。合法 exemption 白名單固定為 `trivial-typo` / `rename-only` / `format-only` / `generated-snapshot` / `single-line-small-file`。`--json` schema `kg.review_audit.v1`，輸出每個 commit 的 `status`(`reviewed` / `exempt` / `missing-review` / `invalid-exemption`)與 trailers/files；任一缺 receipt 或非法豁免 exit `2`。用來把 `docs/sop/review_discipline.md` 從 SOP 變成可驗證 contract |
| `capability_matrix.py` | agent capability contract。輸出 key control-plane surfaces 的 `minimumTier`(`observer` / `operator` / `editor` / `production-capable`)、`sideEffect`、`scope`、`purpose` 與固定 `command`；`--json` schema `kg.capability_matrix.v1`，`--tier` 可只看某個 tier。設計目標是把「這個 agent 能不能碰這個 surface」從散落文件變成單一可查 JSON；目前先覆蓋 repo audit / devops safe wrapper / iOS ops / capture profile 幾條高槓桿入口 |
| `test_ops.sh` | ops regression 聚合入口。預設非 ASC suite:`release` / `ios-release` / `backup-verify` / `devops` / `deploy-smoke` / `infra-health` / `branch-audit` / `review-audit` / `capability-matrix` / `python-entrypoints` / `ui-token` / `docs-lint` / `ios-ops` / `ios-test-discovery` / `chrome-bundle` / `podcast-ops`;optional release surface:`asc`(ASC shell + text bundle offline tests) / `release-surfaces`(`release`+`ios-release`+`asc`)。也可指定 group,`--list` 列清單。`branch-audit`、`review-audit`、`capability-matrix` 都用離線/本地 fixture 驗證結構化 contract，不依賴 live GitHub 狀態；`python-entrypoints` 掃全 `ops/*.py`，禁止裸 `python3` shebang、要求 executable Python entrypoint 使用 uv shebang、有 shebang 即須有 executable bit |
| `release_bump.sh` | 版號改寫 primitive(api: `backend/pyproject.toml`+`src/kg/api.py` / ios: `project.pbxproj` 的 `MARKETING_VERSION`+`CURRENT_PROJECT_VERSION`+1);一般經 `release.sh bump` 呼叫。前身 `scripts/bump-version.sh` |
| `release_changelog.sh` | changelog 生成 primitive(依 `api:`/`ios:` prefix 從 git log 自上個同類 tag 分類成 新功能/修復/其他/維運);一般經 `release.sh changelog` 呼叫。前身 `scripts/generate-changelog.sh` |
| `gen_ios_baseline.sh` | 再生 `docs/snapshot/ios_baseline.md` 快照 |
| `migrate_sot_history.py` | **SoT 回溯帳本一次性遷移** CLI(`backend/src/kg/sot_history_migrate.py` 的 ops 入口,uv shebang)。對指定 `-u <uid>` 或 `--all` 用戶:**就地**只清 legacy `review_events.db` 的 card_id NULL junk(一次性 `.premigration.bak` 備份 + 前置 WAL checkpoint;不 unlink,不孤兒化 server inode)、從 `cards.db` 確定式合成 SRS 完整的 `review_events`(`is_synthetic=True`、event_id 為 uuid5)、逐 notebook 從 terminal links 合成 `graph_events` 史、並存初始全量 `graph_snapshots`。purge 由 `.sot_history_migrated` marker 鎖定**僅首次**(上線後 re-run 絕不刪真實事件,合成靠 event_id 去重補上)。**dry-run 預設且唯讀**(不改 schema/不建檔);`--apply` 才寫且需 `--i-stopped-the-api`(防 live-dir 併發寫);`resolve_uid` 走 `data_dir()`、存在性 hard guard;冪等可重跑。輸出 `MigrationReport`。合成引擎 `demo_review_synth.py`(複習史)+ `graph_history_synth.py`(圖譜史) |
| `devops_kg_safe.sh` | 部署 / 維護 safe wrapper。命令面:`preflight` / `deploy` / `restart` / `status` / `health [--json]` / `logs [n]` / `caddy-status` / `caddyfile` / `docker-ps` / `docker-logs [n]` / `disk-usage` / `memory-usage` / `docker-stats` / `backup` / `backup-s3-test` / `env-check` / `env-drift` / `migrate` / `users` / `user-info <id>` / `run` / `container-run` / `migrate-run` / `ops-cli` / `ops-edit` / `container-script`。其中新增的 typed debug surfaces 皆是固定唯讀命令映射，目標是把高頻 debug 查詢從自由字串 `run` 收斂掉；對 `docker ps` / `sudo systemctl status caddy` / `df -h` 等已 typed 查詢，raw `run` 會直接拒絕並提示對應子命令。`run/container-run/migrate-run` 保留為例外 escape hatch。預設擋 `setup` / `push-env` / `delete-user` / `ssh` / destructive run command；任意遠端命令先經 `is_blocked_run` |
| `status_all.sh` | 相容入口；不再直接 SSH，委派 `devops_kg_safe.sh status` + `devops_kg_safe.sh health` 一覽 backend / caddy / 容器 / host health |
| `backup_verify.sh` | tarball 還原演練 + SQLite integrity |
| `kg_backup.sh` | server 端 streaming tar → S3 backup;cron 觸發,日誌 `/var/log/kg_backup.log` |
| `cron/kg-backup.cron` | `/etc/cron.d/kg-backup`(daily UTC 03:00) |
| `chrome_ext_bundle.sh` | Chrome extension 打包發行;驗證 manifest `version` 符合 Chrome 規格(1-4 段、0..65535、無 leading zero / prerelease / all-zero),發行 zip 排除測試檔與頂層 `tools/` 開發工具 |
| `chrome_verify.sh` | Chrome extension **啟動煙霧測試**(agent-facing,零安裝;改 chrome-extension 後跑此)。三層 fail-fast:(1) `tools/static.mjs` — manifest 引用完整性 / JS syntax(ESM 偵測) / HTML 資產引用 / i18n key 覆蓋;(2) `node --test shared/*.test.js background.test.mjs`(純邏輯 + CSS 不變式 + inline-mirror drift + background outbox/enrich effect 守門);(3) `tools/smoke.mjs` — 用系統既有 Chrome `--headless=new` 透過 CDP `--remote-debugging-pipe` + `Extensions.loadUnpacked` 載入 unpacked extension(Chrome≥126 headless 禁 `--load-extension`,該 CDP 命令只在 pipe 模式開放),開 sidepanel/options 斷言每個 `[hidden]` computed `display:none` + KG token 已套用(anti-false-green)+ 無未捕捉例外;獨立 user-data-dir 不碰使用者 profile。`--static-only` 跳 Layer 3(無瀏覽器 CI host);`CHROME_BIN` override 二進位 |
| `chrome_parity.sh` | Chrome ⟷ iOS **視覺對標工具**(開發輔助,非 gate)。沿用 chrome_verify 的 CDP-pipe + `Extensions.loadUnpacked` 基建:`tools/shots.mjs` 逐 UI case 注入 in-page mock 走真實 render path：sidepanel/options 呼叫 `setState`/`applyView`/`openNotebookSheet`/`openDetail`/`renderLoggedIn`/`renderProStatus` 等 global；content popup case 以 `tools/content-popup-harness.html` 載入 production `content/content.js`，mock `chrome.runtime.sendMessage`/`chrome.storage` 後用 DOM selection 觸發真 popup，並在截圖前 assert selector 初始值與改選後 `addVocab.notebookId` 會跟著變。所有 case 393×852@3x 截 1179×2556(同 iOS 參考圖解析度,回讀 token/host 防 false-green);`tools/compare.mjs` 按 parity manifest 與 iOS 圖(`~/Desktop/IOS截圖參考/`,`IOS_REF_DIR` override)並排 montage 成總覽 contact sheet。`--audit` 另跑 `tools/parity-audit.mjs`，逐 case 產生 `diff.png`、2x 放大對照 `zoom.png`、`palette.txt` 色票/平均色、`metrics.json`(RMSE/MAE/SSIM/pHash)與 `summary.json`，用於細節差異與顏色 drift 追蹤。涵蓋 sidepanel content(light/dark/sepia)/content-popup-notebook/outbox-failed/notebook-sheet/detail/options/empty/error 10 case;其中 `--audit` 只對有 iOS reference 的 case 出 diff/metrics。產物 git-ignored(`tools/{shots,compare,audit}/`) |
| `podcast_upload.sh` | 播客資源上傳(workspace 佈局 → S3,idempotent + index 重建);pipeline 終端 `publish` stage 自動呼叫 |
| `podcast_backfill_disk.py` | served-disk(`/app/data/podcasts/`)→ S3 回填 + `--check` drift reconcile;容器內 boto3 跑(dry-run 預設、無 delete、注入 `audioFormat`) |
| `podcast_preview_backfill.py` | free-tier **試聽片**回填,與 audio/cover 完全解耦:對 bucket 內既有 series,下載 `ep_01/audio.<fmt>` → `ffmpeg -t 180 -c copy` → PUT `ep_01/preview.<fmt>` → RMW `metadata.json` ep1 `previewAvailable`/`previewDurationSec`(不 bump updatedAt → 冪等;不重建 index,preview 欄在 episodes 內被 index strip)。`--all`/`--series`、dry-run 預設、`--execute` 才寫、`--check` drift(in_sync/missing/flag_without_preview/preview_without_flag);per-series 失敗記錄不中斷批次。新 series 由 `ops/podcast_upload.sh` 在 publish 時對 ep_01 自動生成 preview(同 stream-copy) |
| `podcast_cover_publish.py` | 播客**封面**(re)發布,與 audio 完全解耦:只 PUT `<sid>/cover.png` + RMW `metadata.coverImageURL=/api/podcasts/<sid>/cover?v=<sha16>` + 重建 index(**不**重組 audio、**不** reconcile/prune,故對 local↔S3 不同步的 series 安全 —— `upload.sh` 不可用於只換封面)。`v` 為 cover bytes SHA-256 前 16 碼,供 iOS 本地封面 cache-bust;原子靠排序(cover→metadata→index)+ 冪等(同圖同 URL、不 bump updatedAt)+ 可重入;`--check` cover⟷metadata drift(legacy 無版本 URL 在無 local bytes 時視為有效指向；有 local cover 且 token 不符時回 `pending_publish`);dry-run 預設、`--execute` 才寫。`--all --workspaces-dir` / `--workspace` / `--series` |
| `podcast_ops.py` | 播客 pipeline **headless 觀測 CLI**(讀-only):把 dashboard(`lab/podcast/monitor/server.py`)的 disk-derived 邏輯搬上終端/SSH/cron。subcommand `status`(各 workspace 狀態瀑布 + 集數 + 進度 + 花費,exit 2=有 failed/1=有 awaiting/0=ok)、`episodes <ws>`(逐集 plan/script/audio/subtitle 關卡矩陣)、`cost [--workspace]`(TTS+LLM 花費,單一或聚合 + by-model)、`covers`(有音頻卻缺 `plan/cover.png`)皆**純磁碟**(免 boto3);`reconcile`(合成了但沒上 S3 的 drift)、`series`(S3 catalog)需 boto3+`PODCAST_BUCKET`,缺則 clean exit 3。`--json` 契約:stdout 只有 JSON,banner/warning 走 stderr。邏輯 import 自 `monitor/{cost,workspace_status}.py`(無第二份實作) |
| `monitor/workspace_status.py` | podcast dashboard 的 disk-derived 狀態原語(FastAPI-free)。從 `server.py` 抽出(`_stages_done`/`_scan_pipeline_log_status`/`_milestones`/`_episode_status`/`_gate_states`/`_workspace_has_audio`/`reconcile_workspaces`/`audio_episode_numbers`/`disk_status`/`headless_summary`),`server.py` 與 `ops/podcast_ops.py` 共 import 同一份(SoT) |
| `test_devops.sh` | devops 工具測試 |
| `docs_lint.sh` | docs control-plane gate/audit:預設 `gate` 驗 `docs/registry.yml` + 本分支/工作樹 changed docs,並呼叫 `docs_impact.py` 輸出 registry impact hints(warn-only,不計入 `--strict`)；若有 impact hints,會順手印 `./ops/docs_impact.py --since <base> --explain` 作為 suppression/debug follow-up；`--changed` / `--since <rev>` / `--files <docs...>` 做本次改動 gate；`--registry` 只驗 registry；`--audit` / `--all` 才做全 repo frontmatter + staleness 盤點並暴露既有 invalid anchor / stale debt；`--strict` 將 lint WARN 升為 fail，`STALE_THRESHOLD` env 調閾值。linked worktree 內會檢查呼叫者 checkout,不強制跳回 main |
| `docs_impact.py` | 讀 `docs/registry.yml` 的 path-hint detector:`--since <rev>` 掃 `<rev>..HEAD` + index/worktree/untracked paths,`--files <paths...>` 供測試/腳本指定 changed paths,`--json` 輸出機器可讀候選；`--explain` 額外列出被 registry `!path` / `!glob` 排除掉的 suppressed candidates,方便調 registry 精度或追查噪音/漏報。若某份 doc 仍有有效 impact,但部分 changed path 被 suppression 壓掉,同一個 impact 也會額外帶 `excluded_paths` / `excluded_by`（human 輸出對應 `excluded_changed=` / `excluded_by=`）。輸出的是可能受影響 doc ids / paths / triggers,供 doc-sync/review 判斷；支援 registry `!path` / `!glob` 排除 broad source 下的已知誤報；`kind=generated` 會輸出 `generator` 供 agent 判斷「跑生成器,不手改」；不做 AST semantic detection、不直接 fail PR |
| `docs_registry_coverage.py` | registry 覆蓋率 audit:掃 `docs/**/*.md`(排除 assets/legal),比對 `docs/registry.yml` 的 `path` 清單,輸出 registered / unregistered counts,並把未登記項分成 `active_unregistered`(reference/sop/policy/runbook/missing tier 等應進控制面)與 `backlog_unregistered`(archive/plans/specs/snapshot 等非日常 gate debt)；`--json` 給機器讀；`--strict` 只對 active 未登記項 exit 1,用於追蹤控制平面覆蓋 debt |
| `docs/registry.yml` | 文檔控制平面 registry:列出活文檔 `id/path/kind/authority/triggers/sources/generator`。doc-sync / review / gate 的路由以 registry 為 SoT,path 只做 impact hint,語意 trigger 才是同步判斷核心；`sources` 內 `!path` / `!glob` 表示排除規則 |
| `gen_web_tokens.py` | 從 `design-system/tokens.json`(W3C DTCG 格式,跨平台 token SoT)生成 web CSS(`design-system/dist/{kg-tokens,kg-components}.css` + chrome-extension `shared/{tokens,kg-components}.css` + `backend/static/{kg-tokens,kg-components}.css`);手寫 primitives 源 `dist/kg-components.css` 複製進三 surface;`--check` CI gate 比對 on-disk 是否 stale。生成檔禁手改 |
| `gen_web_components.py` | 從 `design-system/components.json`(複合元件**結構** SoT)生成 web CSS+JS:`kg-component-structures.css`(dist + chrome-extension `shared/` + `backend/static/` 三副本)+ `review-gradient.js`。token 以 `var(--*)` 引用(非硬編碼,token 改值自動傳播);支援 `_emit_modifiers`(`.class--active` 等 markup-toggled BEM modifier,states pseudo 之外)。生成檔禁手改;`uv run python ops/gen_web_components.py` 重生,`--check` 為 CI/pre-commit stale gate |
| `token_drift_check.py` | drift guard(**值層**)— 驗證 `tokens.json` 每個 token 仍對齊 iOS Swift。**SoT-inversion-aware**:已接線 scalar 群組(radius/spacing/type-scale/tracking/elevation)iOS 端引用 `DesignTokens.*`,`parse_design_tokens`/`_swift_num` 把引用解析回值再比對(證明 tokens.json==iOS 跨 SoT 反轉仍成立,且抓得到誤接線的值偏移);未接線群組(`AppColors`/`AppTheme`/`AppMotion` spring 物理層/`AppFonts` LineSpacing/`UIComponents` 的 `AppTagMetrics` chip padding + `AppTag` fill opacity)仍直接比對 literal。偏移不可 merge |
| `component_fidelity_check.py` | drift guard(**組裝層**)— contract-based 驗證 `design-system/dist/kg-components.css` 每個手寫 primitive *選用* 的 token 對齊 iOS 元件契約(`.kg-chip`↔`AppTag`、`.kg-btn`↔`AppActionButtonStyle` radius md/700、`.kg-card`↔`AppSectionCardStyle`、`.kg-input` body(17)+hairline、`.kg-banner` caption(12)+v8、serif heading 700…),刻意的 web 發散(brand-hero CTA / banner 形狀)亦 pin 防回歸。`token_drift` 守值、它守*選用哪個值*;stdlib-only,env override `KG_COMPONENTS_CSS` |
| `verify_design_system.sh` | 設計系統完整性**聚合 gate** = `token_drift_check` + `gen_web_tokens --check` + `gen_figma_sets --check` + `gen_web_components --check` + `npm run build:check`(Style Dictionary:`DesignTokens.swift` ↔ tokens.json byte-for-byte)+ `component_fidelity_check`(若存在)+ extension `shared/*.test.js`;pre-commit hook 與 CI 共用入口,任一失敗 exit 1。Python guard 刻意用 `uv run --no-project` 與 backend 68-套件 venv 解耦 |
| `data_inspect.py` | 本地 DB 卡片 / 圖譜 / 管道質量分析 |
| `catalyst_lint.sh` | Mac Catalyst runtime-crash 守門(`--report` / `--strict`);現抓「`.toolbar`/`ToolbarItem` 內掛 `.popover`」(present 過場 trap)。詳見 `docs/sop/ios.md §Catalyst 雷區` |
| `graph_analysis.py` | 圖譜連結閾值審計 |
| `i18n_lint.sh` | iOS 字串在地化掃描(`--report` / `--baseline` / `--baseline-check` / `--strict`),擋 raw 中文、static formatter、`.xcstrings needs_review`。詳見 `docs/sop/i18n_lint.md` |
| `inject_codemod.py` | iOS InjectionNext 三件套自動注入(`import Inject` / `@ObserveInjection` / `.enableInjection()`)。`--dry-run` / `--apply` / `--scope <subdir>` |
| `injection_lint.sh` | iOS hot reload 覆蓋率守門(同 `i18n_lint` 四模式)。三規則:View struct 有 `@ObserveInjection`、per-file arity、`import Inject` 共存性。詳見 `docs/sop/ios.md §Hot Reload` |

Container 內 ops-cli(`card-find`、`db-query`、`llm-errors`、`user-config <uid>`（唯讀檢視 users.json 的 user config:translation / review_clock / review_mode / **vocab_ui** active notebook,active notebook 後端化）、`world-state <uid>`（穩定 schema `kg.ops_world_state.v1`;直接投影 `record/config + notebooks/cards + graph_*.json`，graph 驗證繞快取讀磁碟）、`world-diff <uid> <spec.json>`（expectation schema `kg.ops_world_expectation.v1`；只比對 spec 宣告欄位，輸出 `kg.ops_world_diff.v1` 穩定 mismatch list/path，供 scenario verify 與 replay audit）、`ops_analyze.py` levels 1-6 等)由 `devops` skill 包裝呼叫。傳輸層以 `printf %q` 序列化 argv,任意特殊字元 SQL 可安全穿越單次遠端 bash 解析。

**寫入面**:`backend/ops_edit.py`(`devops.sh ops-edit` / `devops_kg_safe.sh ops-edit`)為 `ops_cli.py` 唯讀查詢的可寫對應面 —— 建用戶 / 增改刪卡 / 設複習態 / 搬卡(`card-move`)/ 筆記本 CRUD(`notebook-create`/`update`/`delete`; `notebook-update` 支援 `--sort-order` 做 surface 排序造景)/ 連結圖譜(`link-add`/`update`/`delete`/`list`; `link-add --if-exists keep|update` 明示重跑語意,`update` 會覆寫既有 link 的 `kind/confidence/reason`)/ `user-config-set`(寫 `users.json` 的 per-user `translation` / `review_clock` / `review_mode` / `vocab_ui.active_notebook_id`，供 Settings / active notebook 等行銷畫面定向造景)/ `seed` 整套 demo 帳號(冪等可重跑;支援頂層 `review_anchor` 與單卡 `review.anchor` 固定複習時鐘,`source` 以 `VocabSource` schema 驗證後寫入)/ `clone-demo <source_uid> <target_uid>` 高保真複製真帳號 vocab 層(cards/notebooks/graph/embeddings/candidates,SQLite 走 online backup API、衍生檔 copy2)+ 由複習聚合(`review_count`/`lapse_count`/`review_streak`/`last_reviewed_at`)確定式合成 `review_events.db`(餵 iOS heatmap/streak;`backend/src/kg/demo_review_synth.py`)；`--expect-source-fingerprint` 可 pin 來源 vocab 層，避免來源漂移讓 clone 結果改變。另補 `world-snapshot` / `world-restore`，把 `users.json + users/* + data_dir root DB` 當成整個 world 做快照/回滾。內建行銷 seed:`ops/seeds/marketing_demo.json`(3 本 notebook / 12 cards / 6 links / 4 new + 4 due + 4 reviewed 的固定展示分布，適合 Today Review / notebook / graph 截圖)。`--notebook`/`--to-notebook`/`--active-notebook` 接受 id 或 name(自動解析,杜絕孤兒卡);link 嚴格 per-notebook(兩端 card 須與 link 同本,`card-move` 搬卡會硬刪原本跨本 link、`notebook-delete` 非空須 `--cascade`)。安全模型(`backend/src/kg/ops_edit_shared.py:EditContext`):**dry-run 預設**(`--commit` 才寫)、寫前自動 tar 備份 user_dir 到 `data_dir/_ops_backups/`，且單帳號備份會內嵌該 uid 的 `users.json` record/email-index snapshot，讓 `restore` 能一起回復 config/identity；world 級備份落在 `data_dir/_ops_world_backups/`。寫後讀回 verify(link 讀盤繞快取、複習態驗時間不變量、user config 讀回 users.json 驗證)、append `_ops_edit_audit.jsonl`(含失敗操作);`restore` 驗備份 arcname==uid 才解壓。寫入複用 app 的 `CardStore`/`GraphStore`/`NotebookStore`(SoT,不重刻 NFC/dedup/graph merge);只 import per-user store,不碰會自寫的全域 log 單例。同 `%q` argv transport、同 `--json` 契約。

## Web 設計系統(`design-system/`)

跨平台 design token 橋接層。Token SoT = `tokens.json`(W3C DTCG),經兩條生成鏈出貨:**Style Dictionary → iOS `DesignTokens.swift`**(scalar bridge)與 **`gen_web_tokens.py` → web CSS**。

| 項目 | 路徑 / 值 |
|------|-----------|
| Token SoT | `design-system/tokens.json` — **W3C DTCG 格式**(`$type`/`$value`/`$description`/`$swift` provenance);scalar 群組已成 Figma→iOS 真注入,顏色等仍由 iOS Swift literal 主導、tokens.json 鏡像(見下 SoT 方向) |
| iOS 生成鏈 | `npm run build`(`package.json` script)→ Style Dictionary(`design-system/sd.config.mjs` 自訂 `kg/swift-tokens` format,排除 color/web-only,PascalCase 巢狀 scalar enum)→ `ios/BooksBrowser/Models/DesignTokens.swift`(禁手改);`npm run build:check`(`design-system/sd-check.mjs`)為 byte-for-byte stale gate |
| web 生成鏈 | `ops/gen_web_tokens.py`(DTCG → web CSS,見 ops 表) |
| **SoT 方向**(接線後二分) | **已接線 scalar**(`AppRadius`/`AppSpacing` scale/`AppFonts.TypeScale`+`Tracking`/`AppElevation`,47 值):tokens.json→`npm run build`→`DesignTokens.swift`→iOS 引用,Figma 改值重編即生效。**未接線**(全部顏色+`WCAGContrastTests`、`AppMotion`、`LineSpacing`、`AppSkin`):iOS Swift literal 為 SoT、tokens.json 鏡像。設計師接 tokens.json 的 SOP 見 `docs/sop/figma-token-workflow.md` |
| Guard(三層)| **值** `ops/token_drift_check.py`(SoT-inversion-aware:已接線解析 `DesignTokens.*` 引用回值、未接線比 literal)+ **生成** `gen_web_tokens.py --check` + `gen_figma_sets.py --check` + `gen_web_components.py --check`(on-disk CSS/JS/sidecar ↔ tokens/components 無 stale)+ **組裝** `ops/component_fidelity_check.py`(primitive *選用* 的 token ↔ iOS 元件契約)。皆見 ops 表 |
| 聚合入口 + 強制 | `ops/verify_design_system.sh` 跑齊三層 + `npm run build:check` + extension `shared/*.test.js`;由 `.github/workflows/design-system.yml`(repo 首支 GitHub Actions CI,相關路徑變動才跑;含 `npm ci`)與 `.githooks/pre-commit`(`git config core.hooksPath .githooks`;DS 檔被 stage 才跑,缺 uv/node 告警跳過,CI 為硬 gate)共用 |
| 一次性遷移工具 | `ops/migrate_tokens_to_dtcg.py`(自研格式 → DTCG,已執行完成,留檔) |
| 生成輸出(canonical) | `design-system/dist/kg-tokens.css`(生成)+ `design-system/dist/kg-components.css`(**手寫** primitives 源,component_fidelity 守護對象) |
| 消費副本 | chrome-extension `shared/tokens.css`(生成)+ `backend/static/{kg-tokens,kg-components}.css`(生成/複製,官網用) |
| **複合元件結構 SoT** | `design-system/components.json` — 手寫**結構**契約(primitive 之上的 BEM 容器/modifier,如 `VocabFilterChipBar`:chips 容器 + chip + count + `--active` modifier,SoT = iOS `AppFilterChipBar`/`AppTabSelector` vocab style)。token 僅 by-reference。與 `dist/kg-components.css`(primitive)分層共存 |
| 結構生成鏈 | `ops/gen_web_components.py`(components.json → `dist/kg-component-structures.css` + `review-gradient.js`,各複製進 chrome-extension `shared/` + `backend/static/`;見 ops 表)。生成檔禁手改 |
| Shadow-DOM 安全 | token CSS selector 用 `:root, :host`,供 extension 注入 closed shadow root 仍生效 |

## Backup / Disaster Recovery

| 項目 | 值 / 路徑 |
|------|-----------|
| L1 Lightsail AutoSnapshot | 每日 UTC 22:00,保留 7 份 |
| L3 S3 bucket | `s3://kg-backups-prod-967512079054`(ap-northeast-1, Versioning + MFA Delete + SSE-S3,**無 lifecycle**) |
| S3 IAM user | `kg-backup-agent` — 僅 `s3:PutObject*`,無 Delete / List |
| Server backup script | `/usr/local/bin/kg_backup.sh`(root 755) |
| Server cron | `/etc/cron.d/kg-backup` — daily UTC 03:00 |
| Server log | `/var/log/kg_backup.log`(每執行一行:exit / bytes / sha256 / key) |
| Server AWS profile | `/home/ubuntu/.aws/`(uid 1000)+ `/root/.aws/`(cron 用) |
| S3 key 格式 | `data/YYYY-MM-DD.tar.gz`(UTC 日期) |
| Lifecycle | 無(MFA Delete 互斥)— 永久累積,手動清見 `backup_restore.md §7` |
| 手動觸發 | `./ops/devops_kg_safe.sh backup-s3-test` |
| Restore SOP | `docs/sop/backup_restore.md` |
| 三層策略總覽 | `docs/sop/backup.md` |

## Podcast Object Storage (Track B, 2026-06)

| 項目 | 值 / 路徑 |
|------|-----------|
| Bucket | Lightsail Object Storage `kg-podcasts-prod`(ap-northeast-1) |
| Key 結構 | `index.json`、`{series_id}/metadata.json`、`{series_id}/ep_NN/{audio.{m4a,mp3},subtitle.srt,script.md}` |
| 上傳工具 | `ops/podcast_upload.sh`(workspace 佈局,`aws s3 sync` + content-type)；`ops/podcast_backfill_disk.py`(served-disk 佈局,boto3) |
| 閉環觸發 | pipeline `publish` stage(`STAGES` 末)合成完成自動上傳 + verify;`GET /api/remote/reconcile`(monitor)報 workspace↔S3 drift |
| Monitor 客戶端 | `lab/podcast/monitor/remote.py`(boto3) |
| Backend 客戶端 | `backend/src/kg/routers/podcast.py`(boto3,proxy 模式;`Range` 直接轉給 S3) |

## LLM Eval Workbench (`lab/llm_eval/`)

| 項目 | 值 / 路徑 |
|------|-----------|
| 架構 SoT | `docs/reference/llm_eval.md` |
| 執行 SOP | `docs/sop/llm_eval.md` |
| Prompt registry | `lab/llm_eval/prompts/manifest.yaml` + `.md` templates |
| Datasets | `lab/llm_eval/datasets/*.jsonl` |
| 核心 API | `lab/llm_eval/llm_eval/__init__.py` — `run_eval()`, `compare_prompts()` |
| Provider 解析 | `lab/llm_eval/llm_eval/providers.py` — cloud registry + Ollama |
| 評分引擎 | `lab/llm_eval/llm_eval/scoring.py` — rule-based (OpenCC + schema + POS + lemma) |
| 執行引擎 | `lab/llm_eval/llm_eval/runner.py` — async parallel, bypass TrackedLLM |
| 測試 | `cd lab/llm_eval && uv run --extra dev pytest -q tests/` |
| audio 副檔名解析 | S3 模式 `_audio_filename` 讀 series `metadata.json` 的 `audioFormat`(缺則 probe m4a→mp3,per-series 快取);非-404 故障 loud-fail |
| 設定 env | `PODCAST_BUCKET` / `PODCAST_BUCKET_REGION` / `PODCAST_BUCKET_ENDPOINT_URL` / `PODCAST_BUCKET_QUOTA_BYTES` |
| 過渡 fallback | `PODCAST_BUCKET` unset → backend 回 disk `data/podcasts/`,且 `audio.m4a` → `audio.mp3` 探測 |
| 音頻格式 | AAC/M4A 128k `+faststart`(`TTS_OUTPUT_FORMAT=m4a`,`TTS_AAC_BITRATE=128k`) |
| TTS model 凍結 | `POST /api/pipeline/start[-saga]` 選填 `tts_model`(白名單 `tts_config.ALLOWED_TTS_MODELS`,非法 422)→ `pipeline.py --tts-model` 寫 `<ws>/.tts_model` sidecar → `stage_synthesize` 讀回注入 `TTS_MODEL` env(單一還原點,涵蓋 /start·/resume·/approve·CLI)。`<ws>/.script_tts_family`(scriptwrite 寫**實際** family = `resolve_tts_family`,非寫死 3.1;palette 由 `pipeline.inject_tts_palette` 依 family 注入,SoT `tts_tags.TAG_CONCEPTS`)供 synth 階段比對,跨 family 記 informational(synth 端 `sanitize_tags_for_family` 兜底)。詳見 `docs/sop/podcast_pipeline.md §3` |

## Cost & Billing(2026-06)

| 項目 | 值 / 路徑 |
|------|-----------|
| AWS account | `967512079054`(ap-northeast-1) |
| GCP billing account(Gemini) | `011E6D-6EE0E0-B1F479` |
| DeepSeek 入口 | `https://platform.deepseek.com/usage`(無 CLI) |
| Lightsail instance | `booksbrowser-kg-api-2gb` @ `small_3_0`(月費見 `cost_baseline.md §1`) |
| Lightsail Object Storage | `kg-podcasts-prod` @ `medium_1_0`(月費見 `cost_baseline.md §1`) |
| LLM usage DB | `{KG_DATA_DIR}/token_usage.db` table `token_usage` — `(user_id, call_type, input_tokens, output_tokens, provider, model, created_at)` |
| Pricing SoT | `backend/src/kg/llm/providers.py:REGISTRY`(per-token 快照與費率變更歷史見 `cost_baseline.md §2`) |
| Service mapping | `backend/src/kg/admin_cost_summary.py:_SERVICE_MAP` — translate / judge / pipeline / other |
| 自家 cost endpoint | `GET /api/admin/user-cost-summary?user_id=&range={24h\|7d\|30d\|month\|all}` |
| Lightsail 在 `aws ce` 回 $0 | Fixed bundle 不走 usage-based;查 bundle 走 `aws lightsail get-{instances,buckets}` |
| Baseline 月費表 / drift 閾值 / 變更歷史 | `docs/reference/cost_baseline.md` **(SoT)** |
| 月度盤點 / 異常追 SOP | `docs/sop/cost_review.md` |
| 觸發 skill | `billing`(read-only 分析+建議,執行交給 `devops`) |
