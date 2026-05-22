<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/
  - ios/BooksBrowser/
  - ops/
verified_against: 7c7a23b
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
| `podcast.py` | `/api/podcasts*`, `/api/podcast-media/*` | 播客列表 / 媒體 / 進度 |
| `billing.py` | `/api/billing/*` | App Store 收據與 server-to-server 通知 |
| `system.py` | `/api/system/*` | `/info`、health |
| `admin.py` | `/api/admin/*`, `/admin/*` | dashboard / user detail / logs / test-matrix |
| `static_pages.py` | `/privacy.html` / `/support.html` / `/terms.html` | 靜態頁 |

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

- **LLM & Embedding**: `GEMINI_API_KEY` / `GEMINI_MODEL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `LLM_PROVIDER_*`(per-call-type 路由) / `LLM_PROVIDER_DEFAULT`
- **Auth & SSO**: `JWT_SECRET` / `ADMIN_TOKEN` / `ADMIN_PASSWORD` / `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `APPLE_BUNDLE_ID` / `CHROME_EXTENSION_ID` / `APP_STORE_CONNECT_*`
- **Quota & Rate Limit**: `FREE_DAILY_LIMIT_USD` / `PRO_DAILY_LIMIT_USD` / `API_RATE_LIMIT` / `TRANSLATE_RATE_LIMIT` / `KG_ALLOW_SANDBOX_PURCHASE`
- **Log retention**: `JUDGE_LOG_RETENTION_DAYS` / `TRANSLATE_LOG_RETENTION_DAYS` / `PIPELINE_LOG_RETENTION_DAYS` / `TOKEN_USAGE_RETENTION_DAYS`
- **Cache**: `TRANSLATE_CACHE_TTL_DAYS`
- **Service / Ops**: `KG_DATA_DIR` / `CORS_ORIGINS` / `KG_LOG_TZ` / `SENTRY_DSN` / `SENTRY_ENVIRONMENT`
- **Claude Code Gateway**: `CCG_API_TOKEN`(詳見 `docs/sop/claude-gateway.md`)

## iOS 模組地圖 (`ios/BooksBrowser/`)

| 目錄 | 用途 |
|------|------|
| `Views/` | 場景視圖(書架、筆記、播客、複習、reader、settings) |
| `Services/` | 後端通訊(`KGService`)、認證、雲同步、analytics、sentry |
| `Models/` | 實體(Book / Notebook / VocabularyEntry / PodcastSeries) + tokens(`AppMetrics` 含 `AppMotion`/`AppSpacing`/`Radius`/`Elevation`) |
| `UIComponents/` | 可重用元件(buttons / cards / banners / toast / skeleton) |
| `Platform/` | iOS/macOS 特定(Widget、shortcuts、app intent) |
| `Localization/`,`*.lproj/` | i18n(en / ja / ko / zh-Hans / zh-Hant) |

iOS 大規模重構後執行 `ops/gen_ios_baseline.sh` 更新 `docs/snapshot/ios_baseline.md`。
PR 開出前(或 CI)跑 `ops/docs_lint.sh` 確認所有 doc frontmatter 完整、verified_against 未過期(預設閾值 30 commits)。

## Ops 腳本 (`ops/`)

| 腳本 | 用途 |
|------|------|
| `ios_build.sh` | iOS Release build,共享 `shlock` |
| `ios_test.sh` | iOS unit tests;`-g pattern` 過濾 |
| `gen_ios_baseline.sh` | 再生 `ios_frontend_baseline.md` 快照 |
| `devops_kg_safe.sh` | 部署 / 維護 safe wrapper |
| `status_all.sh` | 一覽 backend / caddy / 容器狀態 |
| `backup_verify.sh` | tarball 還原演練 + SQLite integrity |
| `chrome_ext_bundle.sh` | Chrome extension 打包發行 |
| `podcast_upload.sh` | 播客資源上傳(idempotent + 遠端 `index.json` flock) |
| `test_devops.sh` | devops 工具測試 |
| `docs_lint.sh` | docs/ frontmatter + staleness 檢查;`--strict` 嚴格模式;`STALE_THRESHOLD` env 調閾值 |
| `data_inspect.py` | 本地 DB 卡片 / 圖譜 / 管道質量分析 |
| `graph_analysis.py` | 圖譜連結閾值審計 |

Container 內 ops-cli(`db-query`、`ops_analyze.py` levels 1-6 等)由 `devops` skill 包裝呼叫。
