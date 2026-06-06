<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/BooksBrowser/
  - backend/src/kg/
verified_against: e286e0fd
-->
# BooksBrowser Architecture (Offline-First & Multi-User)

BooksBrowser 採用**後端權威、離線優先**的資料架構。已後端化的跨裝置 domain state 以 Knowledge Graph (KG) 伺服器為權威來源；尚未後端化的共享 state 依本文資料權威邊界分階段遷移。iOS 的 `SwiftData` 應收斂為本機投影、離線 cache 與 outbox 執行基礎，不再作為跨裝置 Single Source of Truth 的長期架構。完整的帳戶隔離機制確保多用戶與多設備場景下的資料安全。

本機仍必須保存資料，因為核心場景包含離線閱讀、離線查詞、離線複習與低延遲 UI。但本機保存的語意分三類：

- **Authoritative remote state**：後端 DB / object storage 是權威，client 只持有鏡像與 pending intent。
- **Device cache**：可刪可重建的媒體、封面、subtitle、下載音訊、書籍檔案副本。
- **Local-only ephemeral state**：單次 session、debug、尚未決定是否同步的 UI 暫態。

**平台**：iOS 17+ / iPadOS 17+ / Mac Catalyst（macOS 15.0+，`SUPPORTS_MACCATALYST`，非原生 macOS — 核心依賴 Readium 僅 iOS）

**Client 端**：iOS / Mac Catalyst app、Chrome Extension（side panel 選詞翻譯）

---

## 資料權威邊界

| 資料類型 | 權威來源 | iOS 保存語意 | 備註 |
|---|---|---|---|
| 帳號 / session | Backend auth + Keychain token | Keychain session cache | 登出 / token invalidation 必須清本機 user-scoped projection |
| Vocabulary card / graph links / notebook assignment | Backend card / graph / notebook stores | `VocabularyEntry` projection + outbox | 本地新增、刪除、hide/unhide 先 optimistic，再同步收斂 |
| Review state | Backend card review fields | `VocabularyEntry` review fields projection | LWW 以 `last_reviewed_at` 判定 |
| Review event log | Backend `review_events` append-only log | `ReviewRecord` projection | client UUID 冪等；日曆與每日明細讀事件鏡像 |
| Notebook metadata | Backend `/api/notebooks/*` | `Notebook` projection + pending mutation | cover photo 本機 path 只是 device cache；遠端 cover 需另設 asset 權威 |
| Podcast catalog | Backend podcast catalog / object storage | `PodcastSeries` / `PodcastEpisode` cache | 空 server list 不視為權威刪除，避免短暫 index 故障 mass tombstone |
| Podcast progress | Backend `podcast_progress` LWW store | `PodcastProgress` projection | CloudKit 只能視為 legacy/過渡，不應再當跨裝置權威 |
| Podcast follow | 目標為 backend user preference | 目前 `PodcastSeries.isFollowed` local preference | 多平台前需後端化，否則 web/Android 看不到 |
| Book metadata / reading progress | 目標為 backend library store | 目前 `Book` 由 SwiftData CloudKit 保存 | 後端化時保存 metadata、locator、progress、preferred notebook；原始檔走 asset/object storage |
| Book / podcast media files | Object storage 或本機匯入來源 | FileManager cache / download | 不塞 SQLite；可刪後重抓或要求重新下載 |
| Reader / review / translation / appearance settings | 目標為 backend user config | 目前混用 UserDefaults + iCloud KVS | 多平台前需 typed server config；UserDefaults 只作啟動快取 |
| UI filter / sort / session snapshot / debug URL | Local-only unless explicitly promoted | UserDefaults / memory | 不影響跨裝置資料完整性，可維持本機 |

### 遷移原則

- 後端化不是移除本機資料，而是把本機資料降級成 projection / cache / outbox。
- 新增跨裝置 user-facing state 時，預設先設計後端權威 contract；只有明確 local-only 的 UI 暫態才可只放 `UserDefaults`。
- CloudKit / iCloud KVS 不再作為新功能的跨裝置權威。既有使用處可分階段退場，退場前必須有後端 contract、資料 migration 與 rollback gate。
- 書籍與音訊等大型資產走 object storage 或本機 cache；SQLite / SwiftData 只保存 metadata、進度與檔案索引。
- 衝突解決必須寫成 contract：append-only event 用 client UUID 冪等，偏好設定與 progress 用 timestamp LWW，刪除/封存用 tombstone 或明確 bucket 收斂。

### User config contract（目標狀態）

目前後端 `/api/user/config` 只持久化 translation language；iOS 仍把多個跨裝置偏好放在 `UserDefaults` / iCloud KVS。多平台化前，user config 應收斂成 typed server contract，並讓本機 store 只作啟動快取與離線 pending patch。

| Config domain | 目標欄位 | 目前 iOS 來源 | 衝突規則 |
|---|---|---|---|
| `translation` | `source_lang`、`target_lang`、`updated_at` | `TranslationLanguage` + iCloud KVS；後端已保存語言但缺 timestamp LWW | `updated_at` LWW；遠端失敗 rollback 本機 |
| `reader` | `font`、`font_size`、`line_height`、`scroll_mode`、`underline_opacity`、`updated_at` | `ReaderSettings` UserDefaults + iCloud KVS | 整個 reader object LWW；debug hit-testing 不同步 |
| `review` | `mode`、custom intervals、`progress_paused`、`progress_paused_at`、`updated_at` | `ReviewSettingsStore` UserDefaults | LWW；pause/resume 必須跨裝置一致，避免 due/reviewed 計算漂移 |
| `appearance` | `mode`、`updated_at` | `AppAppearanceStore` UserDefaults + iCloud KVS | LWW；`.system` 只保存 mode，不保存 resolved value |
| `language` | `app_language`、`updated_at` | `AppLanguageStore` UserDefaults + iCloud KVS | LWW；`.system` 只保存 selection，不保存系統解析結果 |
| `podcast` | `followed_series_ids`、`updated_at` | `PodcastSeries.isFollowed` local SwiftData | LWW 或 per-series timestamp；server list 用於排序與 cross-platform follow |
| `vocab_ui` | `active_notebook_id` | `activeNotebookId` UserDefaults | LWW；server 必須拒絕已刪 notebook，client 保留本機 fallback |

分階段實作時，先擴充後端 response 以向後相容方式回傳 optional domains，再讓 iOS 依 domain-level `updated_at` merge。每個 domain 的 PATCH 必須是 partial update，不能用缺欄位覆蓋既有 server config；client 也不能在 fetch 失敗時把本機舊值重新 PUT 成權威。

### Podcast state migration（目標狀態）

Podcast catalog 與 media 已由後端 / object storage 提供，iOS 的 series / episode rows 是 cache。剩餘要收斂的是 per-user state：progress 已有後端 LWW store，follow 仍是本機偏好。

| State | 現況 | 目標 | 退場條件 |
|---|---|---|---|
| Catalog | `/api/podcasts*` + object storage 權威；iOS `PodcastSeries` / `PodcastEpisode` cache | 維持現況 | 不使用空 catalog 進行 mass tombstone；短暫 S3 index 故障只降級 |
| Progress | 後端 `podcast_progress.db` LWW；iOS `PodcastProgress` 仍在 SwiftData CloudKit store | 後端為唯一跨裝置權威；iOS row 只作 cache + pending push | iOS 啟動 / catalog sync 先 pull remote，播放中節流 push；確認 migration 後把 `PodcastProgress` 移出 CloudKit config |
| Follow | `PodcastSeries.isFollowed` local SwiftData | 後端 user config 或 dedicated follow endpoint 權威；iOS optimistic toggle + rollback | API 回傳 followed set + `updated_at`；iOS 首次 migration 上傳本機 followed series；server 拒絕不存在 / deleted series |
| Downloaded audio | `PodcastDownloadManager` 本機檔案 | 純 device cache | 登出 / account switch 清本機下載；不可當作跨裝置權威 |
| Cover cache | `podcast-covers/` 本機檔案 | 純 device cache | server cover retracted 時刪 cache；登出清 cache |

Progress CloudKit 退場不可直接刪 schema。安全順序：

1. 後端 progress endpoint 與 iOS pull/push 已雙向上線，且 tie-break 規則一致（同 instant 取較大 position）。
2. 新版本 iOS 啟動時先把現有 CloudKit/local `PodcastProgress` 補推到後端，再 pull remote merge。
3. 觀測一個發版週期後，`PodcastProgress` 改到 local-only store；CloudKit 舊資料只讀一次 migration，不再作權威。
4. 最後移除 CloudKit dependency 前，確認 `Book` 也已有後端 library contract；否則 `CloudStore` 還會因 `Book` 存在而保留。

Follow 後端化應優先走 user config domain（`podcast.followed_series_ids`），除非需要 per-series audit / notification 才拆 dedicated table。client 的 toggle contract 必須是 optimistic local update，server 失敗 rollback；若 server 回傳某 series 已不存在，client 應清除該 follow 並顯示一般同步收斂，不視為 fatal error。

### Reading library migration（目標狀態）

`Book` 目前由 SwiftData CloudKit 保存 metadata、cover blob、`lastReadLocatorJSON`、`progression`、`preferredNotebookId` 與檔名；實體檔案在 iCloud container / Documents。這讓 iOS 裝置間可同步，但 web / Android / backend 無法讀取，且 CloudKit schema 仍綁住 app 資料架構。後端化後應拆成兩層：

| Layer | 後端權威 | iOS cache | 備註 |
|---|---|---|---|
| Library metadata | `book_id`、title、author、format、source hash、cover asset id、created/updated/deleted timestamps | `Book` projection | `book_id` 應為 server id；本機 UUID 可作 migration client id |
| Reading position | `last_locator_json`、`progression`、`date_last_read`、`updated_at` | `Book.lastReadLocatorJSON` / `progression` cache | LWW；EPUB/PDF 都走同一 contract，避免 PDF 顯式 save、EPUB debounce save 行為漂移 |
| Notebook binding | `preferred_notebook_id` | `Book.preferredNotebookId` cache | server 拒絕 deleted / nonexistent notebook；client 失敗 fallback 到 active/default |
| Asset manifest | object key、size、sha256、format、upload status | `epubFileName` / local path cache | 原始 EPUB/PDF/TXT/MD 不進 SQLite；TXT/MD 轉 EPUB 後可同時保留 original asset |
| Cover | cover asset key 或 derived thumbnail | local cover cache / optional SwiftData blob during migration | 大圖不長期塞 SwiftData blob；可由 backend 產生或 client upload |

建議 API contract（後續實作，非現況）：

- `GET /api/library/books?since=`：增量列出 metadata + tombstone。
- `POST /api/library/books`：建立 book metadata，帶 `client_book_id` 冪等鍵與 optional asset manifest。
- `PATCH /api/library/books/{book_id}`：partial update metadata / notebook binding。
- `PUT /api/library/books/{book_id}/position`：LWW 更新 locator / progression。
- `POST /api/library/books/{book_id}/asset-upload`：取得 object storage upload target 或宣告本機-only asset。
- `GET /api/library/books/{book_id}/asset`：下載 / redirect 至可授權的 object storage URL。

Migration 順序：

1. 先只同步 metadata + reading position，不要求原始檔上傳；跨裝置可看到書目與進度，但沒有 asset 時顯示「需下載 / 重新匯入」狀態。
2. 加入 asset upload entitlement / quota policy：免費層可只同步 metadata；Pro 或明確容量限制才同步原始檔。
3. iOS 首次啟動 migration 掃描現有 `Book`，以 `client_book_id` 冪等 upsert 到後端；成功後保存 `remoteBookId`（後續實作需新增欄位）。
4. Reader 每次 debounce save 後排 position outbox，不讓翻頁直接阻塞網路；進背景 / 關閉 reader 時 flush 本機與 best-effort remote。
5. 後端 metadata / position 穩定後，`Book` 可移出 CloudKit store；但移除 CloudKit entitlement 前要確認沒有其他 model 仍依賴 CloudKit。

刪除語意必須是 tombstone，而不是只刪本機 row。使用者刪書時：

- metadata tombstone 同步到後端，其他裝置隱藏該書。
- 本機檔案可立即刪除；object storage asset 是否刪除由 retention / recovery policy 決定。
- 詞卡的 `bookId` 關聯不應硬刪詞卡；只解除來源書關聯或保留書名 snapshot。

---

## 核心資料模型: `VocabularyEntry` & `AuthManager`

### 多帳戶認證架構

**AuthManager** (`AuthManager.swift`) 負責全應用的認證與帳號管理：
- **isLoggedIn**: 用戶是否已登入（Apple / Google Sign-In）
- **userId**: 當前活躍帳戶的 ID，儲存於 Keychain
- **token**: JWT 認證令牌，用於 KG API 呼叫的 `Authorization: Bearer` 標頭
- **Apple Sign-In**：原生 `ASAuthorization` 流程
- **Google Sign-In**：整合 GoogleSignIn SDK，支援多設備無縫切換
- **Web Auth**：後端提供 `/login` → Google/Apple OAuth callback → cookie-based admin session；`/login` 會為 Apple form-post flow 預先 mint `oauth_state` HttpOnly Secure cookie，callback 必須通過 state compare
- **Guest Mode**：未登入時仍允許查詞與本地儲存，帳號切換時自動清除舊帳號資料

### 生詞條目狀態管理

閱讀器中所有的生詞、以及知識庫中所有的卡片，在手機端都統一對應到同一個 SwiftData Model: `VocabularyEntry`。`VocabularyEntry` 是後端 card state 的本機 projection，同時承載離線新增 / 刪除 outbox，不是跨裝置權威。
我們透過 `syncStatus` 與 `actionType` 這兩個欄位來控制單字的狀態與流向。

- `syncStatus` 已由 `VocabularySyncState` 封裝：`pending` / `synced` / `failed`
- `actionType` 已由 `VocabularySyncAction` 封裝：`add` / `delete` / `edit`
- 實際持久化仍保留原始欄位，避免 SwiftData migration 成本，但業務邏輯應優先走 typed helper，如 `queueDelete()`、`markSynced()`
- 更完整的規則表見 [reference/sync_lifecycle.md](../reference/sync_lifecycle.md)

| `syncStatus` | `actionType` | 含義 | 在哪裡顯示？ |
|-------------|--------------|------|-------------|
| 0 | `"add"` (預設) | **待收錄**：在手機新增，但尚未上傳至 KG 伺服器 | `VocabularyListView` 頁籤「待收錄」清單、`SyncView` 的上傳階段 |
| 1 | `"add"` | **知識庫**：已經與 KG 伺服器同步過，存在於雲端的單字 | `KGVocabView` 頁籤「知識庫」清單 |
| 0 / 1 | `"delete"` | **待刪除**：使用者在手機點擊刪除，等待上傳告訴 KG 伺服器也要刪除 | 隱藏不顯示，僅在 `SyncView` 執行刪除 Request |

> **注意：執行緒安全 & 帳號隔離**
> - 所有與後端同步並寫入 SwiftData 的操作，都會使用獨立的背景 `ModelContext` 來執行，避免 UI 卡頓
> - 帳號切換時，`AuthManager.logout()` 會自動呼叫 `KGService.clearLocalData()` 以清除舊帳號的 SwiftData，確保完全隔離

---

## 閱讀器 (ReaderView) 的離線運作

支援格式：EPUB、TXT、MD、PDF（`BookshelfImportService` 統一入口，TXT/MD 經 `EPUBConverter` 轉 EPUB 後閱讀，PDF 走 `PDFReaderView` 獨立路徑）。`EPUBConverter` 拆三檔：核心 `EPUBConverter.swift`、Markdown 解析 `EPUBConverter+Markdown.swift`、純 Swift ZIP 寫入 `EPUBConverter+MinimalZIP.swift`（避免 ZipFoundation 依賴）。Reader 以 `#if os(iOS)` 隔離 —— Catalyst 下 `os(iOS)` 為 true 故仍編譯仍啟用（非原生 macOS，無 AppKit 路徑）。

1. **底線渲染 (Underline Rendering)**:
   打開書籍時，撈出所有非刪除的 `VocabularyEntry`，注入 JS 顯示底線。離線亦可。

2. **點擊單字 (Word Selection)**:
   - **已存在於本地**: 從 `VocabularyEntry` 取出翻譯/詞性/解釋瞬間顯示，`O(1)` 無網路。
   - **全新單字**: 並行觸發 LLM 翻譯（provider 由 backend registry 路由，預設 Gemini）+ Dictionary API 發音。翻譯時自動擷取 context sentence（書籍原文上下文）。儲存時寫入 `syncStatus = 0` 的 `VocabularyEntry`。

---

## 雙向同步機制 (BackgroundSyncActor & KGService)

App 實作了雙向同步流程，由 `BackgroundSyncActor`（`@ModelActor` 背景執行緒）驅動。同步的目標是讓本機 projection 收斂到後端權威狀態，並把離線期間產生的 pending intent 送上後端：

1. **Push Review State** — 推送本地複習狀態（`review_count`、`next_review_date` 等），LWW 策略以 `last_reviewed_at` 判定
2. **Push Review Events** — 推送完整複習事件（`event_id`、`card_id`、`word_snapshot`、`notebook_id`、`feedback`、`reviewed_at`、`created_at`），以 client UUID 冪等去重
3. **Upload Deletes** — 找出 `actionType == "delete"` 項目，呼叫 API 刪除
4. **Upload Adds** — 找出 `syncStatus == 0` 新詞，POST 到 KG
5. **Fire-and-Forget Pipeline** — 呼叫 `/api/pipeline` 觸發背景 AI 處理（Enrich → Embed → Judge → Difficulty），每次執行寫入 `pipeline_log.db` 記錄 per-run/step timing + status + items
6. **Pull & Merge** — `pullCardsToLocal`：
   - 增量同步（`since` 時間戳），只拉異動過的 KGCard
   - 背景執行緒合併翻譯、詞性、難度、graph links
   - 全量同步時做 Orphan Cleanup（安全閾值 50 筆 / ratio < 0.8 保護）
7. **Pull Review Events** — 從 `/api/vocab/review-events` 增量拉回跨裝置複習事件，寫入本地 `ReviewRecord` 鏡像；月曆與每日明細只讀真實事件，不再用 daily aggregate placeholder 補洞

### Bilateral Optimistic Sync（hide/unhide/delete links）

Graph link 操作採用 bilateral optimistic 策略：
- 使用者操作 → **立即本地修改** → 排入 `bilateralOps` queue
- 下次 sync 時 `flushPendingOperations` 批量 POST 到 server
- Server 端 hide/unhide 是 idempotent，重複推送安全
- Blocked pairs：hard delete link 時寫入 blocked pair，防止 pipeline 重新生成

### One-Shot Judge 子系統

Pipeline 的 Link 階段現由 one-shot judge 取代舊的 candidate queue：
- **pending_judge**：embed 完成後，候選 link 寫入 `pending_judge` 而非直接建立
- **Selective Prompt**：LLM 一次性判斷 pending pairs 是否值得連結，batch 模式節省 86% input tokens
- **Degree Cap**：`MAX_DEGREE` 限制每個 node 的 to-side 連結數，hidden links 不計入
- **judge_log**：完整記錄每次判斷的 accept/reject 決策，供 admin dashboard 顯示 acceptance rate
- **Blocked pairs**：hard delete 時寫入 blocked pair，judge 不會重新提議

### Translate Log

翻譯/解釋路徑新增結構化 LLM 呼叫日誌：
- 每次 LLM 呼叫記錄 prompt、response、token 消耗、latency
- **Cross-user cache**：相同 word+context 命中快取時跳過 LLM 呼叫
- Admin user detail page 可瀏覽 translate_log 記錄

### LLM Failure Log

LLM provider/SDK 的 terminal failure（429/5xx/timeout 等）另寫入 `llm_errors.db`，供 admin cost/error 趨勢補齊「有燒請求但無 usage」的觀測缺口；error message 入庫前必須遮罩 bearer/API key/token/password/secret-like 值。

### Chrome Extension Sync

Chrome Extension 走 REST API 直連，不經 iOS sync pipeline：
- `POST /api/vocab` + `POST /api/pipeline`（fire-and-forget）
- Auth token 從 options page 設定，存 `chrome.storage.local`

---

## Notion-inspired UI 視覺系統

系統透過 CSS 與 JS 注入到 Readium，實行極簡的 Notion-inspired 視覺：

- **字體 (Typography)**: 英文 `Athelas` + `Biotif`，中文 `STSongti-SC`。
- **透明度控制**: `ReaderSettings` 面板調節 `--vocab-opacity` CSS Variable。
- **介面隱形化**: 底線用柔和 `linear-gradient`，高亮用低對比度邊框 + 4% Alpha 底色。

### Toast Notification System

全 app 操作回饋走 `AppToastCoordinator`（EnvironmentKey 注入）：
- `AppToast`：capsule 形狀，支援 swipe dismiss，4 種 style（success/info/warning/error）
- `toastSheet` / `toastFullScreenCover`：自動注入 `toastOverlay()` 的 sheet wrapper
- `safeSaveWithToast()`：`ModelContext` 安全存檔 + toast 回饋
- 22 個 View 已接入

### Motion Layer

除了色彩、字體與材質，BooksBrowser 現在也把 motion 視為設計系統的一部分。

- 動畫語意層集中在 `BooksBrowser/Models/AppMetrics.swift` 的 `AppMotion`
- 共享 transition 也集中在同一檔案，避免 feature 各自發明不同進出方式
- Reader、Review、Sync 是目前優先完成收斂的三條主路徑

目前映射原則：
- Reader panel / header → `panelState`、`headerState`
- Review reveal / navigation → `reviewRevealSpring`、`reviewNavigationSpring`
- Modal / sheet 交換 → `modalSwapSpring`
- Sync phase / step update → `phaseChange`、`feedbackPulse`

這層規範的主文檔在 `docs/sop/ui-design.md` 的 `Motion Contract`。
若要改動畫規則，先更新該文檔，再修改程式；若是查編譯或 SwiftUI 實作錯誤，回 `docs/sop/ios.md`。
若要確認現有有哪些可重用 UI 零件與互動模式，查 `docs/reference/ui/components.md`。
若要確認各主畫面有哪些狀態已覆蓋、哪些還沒補齊，查 `docs/reference/ui/state_matrix.md`。
若要查 backend 部署、debug、測試與格式規範入口，查 `docs/sop/backend.md`。

---

## Crash Reporting Layer（Sentry）

Backend + iOS 同時整合 Sentry，opt-in 啟動且預設關閉（`SENTRY_DSN` / `Info.plist SentryDSN` 為空時整層 no-op）。本段只談架構分層 — 細節不在此重複。

- **Backend 實作**：`backend/src/kg/sentry_init.py`；FastAPI / Starlette / Logging integrations + auth header / OAuth query scrub；狀態暴露於 `/api/system/info`。
- **iOS 實作**：`ios/BooksBrowser/Services/AppCrashReporting.swift`；SPM 守門 + `BooksBrowserApp.init()` 第一步 bootstrap + `setUser` 連動 `authManager.isLoggedIn`。
- **Env / 取樣 / 隱私規範（SoT）**：`docs/sop/deploy.md §Sentry 錯誤追蹤`。
- **iOS bootstrap 順序 / `beforeSend` 過濾規則**：`docs/sop/ios.md §Crash Reporting`。
