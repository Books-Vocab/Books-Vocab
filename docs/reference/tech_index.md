<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/
  - ios/BooksBrowser/
  - ops/
  - lab/
verified_against: d52ace71
-->
# Technical Reference Index

快速 look up:endpoint / DB / env var / iOS 模組 / ops 腳本叫什麼、定義在哪。
新增 router / table / env var / ops 腳本時,**同 PR 內補一行**。

---

## Backend API Routers (`backend/src/kg/routers/`)

| 檔案 | Endpoint prefix | 用途 |
|------|-----------------|------|
| `auth.py` | `/auth/*` | JWT 驗證、Apple/Google token 交換 |
| `web_auth.py` | `/login`, `/auth/web/{google,apple}/*` | Web OAuth + admin cookie session |
| `user.py` | `/api/user/*` | 設定、entitlements、quota |
| `vocab.py` | `/api/vocab/*` | 單字 CRUD、批量、incremental sync |
| `notebook.py` | `/api/notebooks/*` | 筆記簿 CRUD、cover |
| `translate.py` | `/api/translate/*` | quick / phrase / explain |
| `pipeline.py` | `/api/pipeline*` | 圖譜生成流程觸發 |
| `podcast.py` | `/api/podcasts*` | 播客列表 / 媒體 / 進度 |
| `billing.py` | `/api/billing/*` | App Store 收據與 server-to-server 通知 |
| `system.py` | `/api/system/*` | `/info`、health |
| `admin.py` | `/api/admin/*`, `/admin/*` | dashboard / user detail / logs / test-matrix |
| `static_pages.py` | `/privacy.html` / `/support.html` / `/terms.html` / `/guide.html` | 靜態頁 |

## SQLite Log Stores (`backend/src/kg/`)

| 檔案 | 主要 table | 用途 |
|------|-----------|------|
| `user_store.py` | users / sessions | 帳戶、provider、session |
| `judge_log.py` | `judge_log` | LLM judge 決策追蹤、acceptance rate |
| `translate_log.py` | `translate_log` + cache hits | 翻譯呼叫紀錄、cross-user cache、admin search |
| `pipeline_log.py` | `pipeline_runs` | 圖譜管道 per-run/step timing |
| `token_tracker.py` | `token_usage` | LLM token / cost,provider-aware |
| `podcast_progress.py` | `podcast_progress` | per-user 播客 LWW 進度 |
| `admin_audit.py` | `admin_audit_log` | grant/revoke 等管理員操作 |
| `app_store.py` | app store receipts | 訂閱收據 |
| `secret_store.py` | secrets | 加密憑證 |
| `mem_log.py` | (in-memory) | admin in-memory log capture |

Data dir 透過 `KG_DATA_DIR` env 切換。`orphan_scan` 為 cross-DB consistency scanner(`/api/admin/orphan-scan`)。

## Environment Variables

完整清單見 `docs/sop/deploy.md`。此處列分組與代表項:

- **LLM & Embedding**: `GEMINI_API_KEY` / `GEMINI_MODEL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `LLM_PROVIDER_*`(per-call-type 路由) / `LLM_PROVIDER_DEFAULT` / `JUDGE_CONFIDENCE_THRESHOLD`(judge link 接受門檻,default `0.7`;換低校準 judge model 時調低)
- **Auth & SSO**: `JWT_SECRET` / `ADMIN_TOKEN` / `ADMIN_PASSWORD` / `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `APPLE_BUNDLE_ID` / `CHROME_EXTENSION_ID` / `APP_STORE_CONNECT_*`
- **Quota & Rate Limit**: `FREE_DAILY_LIMIT_USD` / `PRO_DAILY_LIMIT_USD` / `API_RATE_LIMIT` / `TRANSLATE_RATE_LIMIT` / `KG_ALLOW_SANDBOX_PURCHASE` / `RATE_LIMIT_TRUSTED_HOPS`(匿名請求取 XFF 倒數第 N 段作 rate-limit key,default `1` = 現行單層 Caddy 行為;前置 N 層可信代理時設 `N+1`,見 `host_topology.md`)
- **Log retention**: `JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS`
- **Cache**: `TRANSLATE_CACHE_TTL_DAYS`
- **Service / Ops**: `KG_DATA_DIR` / `CORS_ORIGINS` / `KG_LOG_TZ`(ops-side only — 僅 root `devops.sh` 顯示 log 時間用,不影響 backend runtime) / `SENTRY_DSN` / `SENTRY_ENVIRONMENT`
- **Claude Code Gateway**: `CCG_API_TOKEN`(詳見 `docs/sop/claude-gateway.md`)
- **Antigravity Proxy**: 純本機執行(`bun run src/server.ts` on `localhost:3000`),無遠端 endpoint;詳見 `docs/sop/antigravity-proxy.md`
- **Codex Gateway**: 純本機執行(`.venv/bin/codex-lb` on `127.0.0.1:2455`),讀 `~/.codex/auth.json` OAuth;詳見 `docs/sop/codex-gateway.md`

## iOS 模組地圖 (`ios/BooksBrowser/`)

| 目錄 | 用途 |
|------|------|
| `Views/` | 場景視圖(書架、筆記、播客、複習、reader、settings) |
| `Services/` | 後端通訊(`KGService`)、認證、雲同步、analytics、sentry |
| `Models/` | 實體(Book / Notebook / VocabularyEntry / PodcastSeries) + tokens(`AppMetrics` 含 `AppMotion`/`AppSpacing`/`Radius`/`Elevation`;`AppSkin` 拆 `+BaseValues`/`+Environment`;feature-local metrics:`ReaderMetrics` / `TodayReviewMetrics` / `BookshelfMetrics` / `PodcastPlayerMetrics` / `NotebookStackMetrics`) |
| `UIComponents/` | 可重用元件(buttons / cards / banners / toast / skeleton) |
| `Platform/` | iOS / Mac Catalyst 橋接(`PlatformRepresentable` 型別 alias、`PlatformCompatibility` modifier wrapper、`LayoutMode`、`MacWindowChrome` Catalyst 視窗尺寸+沉浸 title bar、`MacMenuCommands` Catalyst 頂部選單列+⌘ 快捷鍵、`AppCommandCoordinator` app-global menu intent、`FocusedCommandValues` focusedSceneValue 動作通道) |
| `Localization/`,`*.lproj/` | i18n(en / ja / ko / zh-Hans / zh-Hant) |
| `Debug/` | DEBUG-only — `CatalogScene` + `Scenarios/*Scenarios.swift`(Playbook iOS catalog,啟用方式見 `docs/sop/ios.md §Playbook Catalog`) |

iOS 大規模重構後執行 `ops/gen_ios_baseline.sh` 更新 `docs/snapshot/ios_baseline.md`。
PR 開出前(或 CI)跑 `ops/docs_lint.sh` 確認所有 doc frontmatter 完整、verified_against 未過期(預設閾值 30 commits)。

## iOS — i18n / Locale 模組 (`ios/BooksBrowser/`)

| 元件 | 路徑 | 用途 |
|------|------|------|
| `L10n` | `Localization/L10n.swift` | string / format 三層 fallback(current → en → key);format 走 NSString 觸發 plural rule |
| `AppLanguage` / `AppLanguageStore` | `Models/AppLanguage.swift` | 5 語言選單 + UserDefaults + iCloud KV;`effectiveLanguage` 解析 `.system`;`locale` vs `formatLocale` 分流 |
| `LocaleAwareFormatter` | `Models/LocaleAwareFormatter.swift` | 跟 AppLanguage 的 thread-safe DateFormatter/Number/Relative cache,format-in-lock,語言變更時 invalidate |
| `Localizable.stringsdict` | `<lang>.lproj/` | NSStringPluralRuleType plural variations;新增 key 流程見 `docs/sop/i18n_plural_keys.md` |
| `TranslationLanguage` | `Models/TranslationLanguage.swift` | 翻譯來源/目標語言;UserDefaults + iCloud KV + updatedAt LWW;預設值讀 `Locale.preferredLanguages`(script-aware) |
| `KGFeatureFlags` | `Models/KGFeatureFlags.swift` | iOS-side feature gates(目前控 `serverTranslationLwwEnabled` / `vocabularyLangPayloadEnabled`) |
| `AppFonts.cjk{Sans,Serif}FallbackName` | `Models/AppFonts.swift` | 依 effectiveLanguage 切 CJK fallback(PingFangTC/SC、Hiragino、AppleSDGothic) |
| `SpeechService.voiceCode(for:)` | `Services/SpeechService.swift` | TranslationLanguage → BCP-47 region 對 AVSpeechSynthesisVoice 的 mapping(zh-Hant → zh-TW) |

## Ops 腳本 (`ops/`)

| 腳本 | 用途 |
|------|------|
| `ios_build.sh` | iOS Release build,共享 `shlock` |
| `ios_test.sh` | iOS unit tests;`-g pattern` 過濾 |
| `gen_ios_baseline.sh` | 再生 `ios_frontend_baseline.md` 快照 |
| `devops_kg_safe.sh` | 部署 / 維護 safe wrapper |
| `status_all.sh` | 一覽 backend / caddy / 容器狀態 |
| `backup_verify.sh` | tarball 還原演練 + SQLite integrity |
| `kg_backup.sh` | server 端 streaming tar → S3 backup;cron 觸發,日誌 `/var/log/kg_backup.log` |
| `cron/kg-backup.cron` | `/etc/cron.d/kg-backup`(daily UTC 03:00) |
| `chrome_ext_bundle.sh` | Chrome extension 打包發行 |
| `podcast_upload.sh` | 播客資源上傳(workspace 佈局 → S3,idempotent + index 重建);pipeline 終端 `publish` stage 自動呼叫 |
| `podcast_backfill_disk.py` | served-disk(`/app/data/podcasts/`)→ S3 回填 + `--check` drift reconcile;容器內 boto3 跑(dry-run 預設、無 delete、注入 `audioFormat`) |
| `test_devops.sh` | devops 工具測試 |
| `docs_lint.sh` | docs/ frontmatter + staleness 檢查;`--strict` 嚴格模式;`STALE_THRESHOLD` env 調閾值 |
| `data_inspect.py` | 本地 DB 卡片 / 圖譜 / 管道質量分析 |
| `catalyst_lint.sh` | Mac Catalyst runtime-crash 守門(`--report` / `--strict`);現抓「`.toolbar`/`ToolbarItem` 內掛 `.popover`」(present 過場 trap)。詳見 `docs/sop/ios.md §Catalyst 雷區` |
| `graph_analysis.py` | 圖譜連結閾值審計 |
| `i18n_lint.sh` | iOS 字串在地化掃描(`--report` / `--baseline` / `--baseline-check` / `--strict`),擋 raw 中文、static formatter、`.xcstrings needs_review`。詳見 `docs/sop/i18n_lint.md` |
| `inject_codemod.py` | iOS InjectionNext 三件套自動注入(`import Inject` / `@ObserveInjection` / `.enableInjection()`)。`--dry-run` / `--apply` / `--scope <subdir>` |
| `injection_lint.sh` | iOS hot reload 覆蓋率守門(同 `i18n_lint` 四模式)。三規則:View struct 有 `@ObserveInjection`、per-file arity、`import Inject` 共存性。詳見 `docs/sop/ios.md §Hot Reload` |

Container 內 ops-cli(`db-query`、`ops_analyze.py` levels 1-6 等)由 `devops` skill 包裝呼叫。

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
| audio 副檔名解析 | S3 模式 `_audio_filename` 讀 series `metadata.json` 的 `audioFormat`(缺則 probe m4a→mp3,per-series 快取);非-404 故障 loud-fail |
| 設定 env | `PODCAST_BUCKET` / `PODCAST_BUCKET_REGION` / `PODCAST_BUCKET_ENDPOINT_URL` / `PODCAST_BUCKET_QUOTA_BYTES` |
| 過渡 fallback | `PODCAST_BUCKET` unset → backend 回 disk `data/podcasts/`,且 `audio.m4a` → `audio.mp3` 探測 |
| 音頻格式 | AAC/M4A 128k `+faststart`(`TTS_OUTPUT_FORMAT=m4a`,`TTS_AAC_BITRATE=128k`) |
| TTS model 凍結 | `POST /api/pipeline/start[-saga]` 選填 `tts_model`(白名單 `tts_config.ALLOWED_TTS_MODELS`,非法 422)→ `pipeline.py --tts-model` 寫 `<ws>/.tts_model` sidecar → `stage_synthesize` 讀回注入 `TTS_MODEL` env(單一還原點,涵蓋 /start·/resume·/approve·CLI)。`<ws>/.script_tts_family`(scriptwrite 寫,目前恆 `3.1`)供 synth 階段比對,跨 family 打 WARN。詳見 `docs/sop/podcast_pipeline.md §3` |

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
