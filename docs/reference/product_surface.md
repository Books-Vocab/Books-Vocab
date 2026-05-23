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
verified_against: 41bf8dd
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
- **macOS multiplatform** (macOS 15.0+): Cmd+N / Cmd+F shortcuts
- **Notebook robustness**: `resolveNotebookId` chokepoint + `sanitizeOutbox` orphan migration + `triggerPipelinesIsolated` per-notebook isolation + stale `activeNotebookId` cleanup + tombstone defense
- **Notebook bookshelf**: LazyVGrid card grid + `NotebookCard` + cover system (12-color palette + 6 SwiftUI Canvas patterns + PhotosPicker custom image) + ProgressCapsule + VocabReviewBanner (separated due/unlearned) + pending tab → SyncView integration + export dual-entry + sort menu + empty-state CTA + `NotebookCardActions` reusable context menu
- **Podcast player**: audio + sentence-level SRT highlight + reader-parity 翻譯 via `VocabularyContextProtocol` + phrase 長按整句 + auto-pause-on-lookup + subtitle size S/M/L/XL/XXL + series 追蹤 toggle + 已追蹤浮上書庫頂端 + per-user progress sync to backend
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
- **Static pages**
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
- **Podcast API**: `/api/podcasts*` 認證端點 + `/api/podcast-media/` StaticFiles 無條件掛載 + Range/206 支援 + `ep_num` Path 驗證 + per-user podcast progress LWW SQLite store
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
- 閱讀選詞翻譯
- Auth token 整合
- woff2 字型
- Side panel error state taxonomy + settings entry + `AbortError` safety

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
- Admin cost summary + trends
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

## Claude Code Gateway (`lab/claude-code-gateway/`,vendored,third-party)

- Claude Code CLI → OpenAI-compatible `/v1/chat/completions`
- 公網 `https://wordnexus.lol/claude/v1` (Caddy `/claude/*` → port 8090)
- Bearer `CCG_API_TOKEN`,模型別名 `sonnet`/`opus`/`haiku`
- 現行呼叫點 `lab/podcast/pipeline.py`(PoC `lab/archive/podcast_architect_poc.py`)
- 詳見 `docs/sop/claude-gateway.md`

## Antigravity Proxy (`lab/antigravity-proxy/`,vendored,third-party)

- Google Antigravity OAuth → OpenAI-compatible `/v1/chat/completions`(直接 HTTP 打 Google sandbox endpoint)
- **2026-05-23 撤出公網**:純本機 `bun run start` → `http://localhost:3000/v1`,不再走 VPS / Caddy(封號風險考量)
- 多 Google Pro 帳號 pool + 自動 quota rotation + healthScore;OAuth refresh tokens 存本機 `lab/antigravity-proxy/antigravity-accounts.json`(不在 git)
- 可用模型:`claude-opus-4-6-thinking`/`gemini-2.5-pro`/`gemini-3.1-pro-low`/`gemini-3.5-flash-low`/`gpt-oss-120b-medium` 等(訂閱戶權限範圍)
- **與 KG 邏輯獨立**(podcast pipeline 不呼叫此 proxy);個人實驗用
- 詳見 `docs/sop/antigravity-proxy.md`

## Codex Gateway (`lab/codex-gateway/`,vendored,third-party)

- ChatGPT Plus/Pro 訂閱 → OpenAI-compatible `/v1/chat/completions` + `/v1/responses`(讀 `~/.codex/auth.json` OAuth token 轉發)
- 純本機 `127.0.0.1:2455`(FastAPI + uv);不上 VPS、不過 Caddy(預防性 air-gap)
- 模型線(2026-05-23 ChatGPT **Plus** 訂閱實測):**僅 `gpt-5.3-codex`** 可用;`gpt-5` / `gpt-5-codex` / `gpt-5.4-codex` / `gpt-5.1-codex` 全回 `not supported when using Codex with a ChatGPT account`。Pro / Business / Enterprise 可用範圍更大,dashboard 自動 sync
- **與 KG 邏輯獨立**;個人實驗 / OpenClaw / Cursor 本機接入
- 詳見 `docs/sop/codex-gateway.md`

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
- Post-deploy smoke verify: `system/info` + health + sentry test event
- `backup_verify.sh`: restore drill + integrity check
- Chrome extension release bundle script + tests
- pytest pinned in `pyproject.toml [dependency-groups].dev`(修 backend venv 無 pytest)
