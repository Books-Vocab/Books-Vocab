<!-- doc-meta
tier: structural
scope:
  - ios/BooksBrowser
  - backend/src/kg
verified_against: 4061750
-->
# BooksBrowser Architecture (Offline-First & Multi-User)

BooksBrowser 採用**離線優先 (Offline-first)** 的資料庫架構，以裝置端的 `SwiftData` 為唯一資訊來源 (Single Source of Truth)，並透過背景同步與遠端 Knowledge Graph (KG) 伺服器保持資料一致。完整的帳戶隔離機制確保多用戶與多設備場景下的資料安全。

**平台**：iOS 17+ / macOS 15.0+（macOS Reader 暫不啟用，其餘功能共用）

**Client 端**：iOS/macOS app、Chrome Extension（side panel 選詞翻譯）

---

## 💾 核心資料模型: `VocabularyEntry` & `AuthManager`

### 多帳戶認證架構

**AuthManager** (`AuthManager.swift`) 負責全應用的認證與帳號管理：
- **isLoggedIn**: 用戶是否已登入（Apple / Google Sign-In）
- **userId**: 當前活躍帳戶的 ID，儲存於 Keychain
- **token**: JWT 認證令牌，用於 KG API 呼叫的 `Authorization: Bearer` 標頭
- **Apple Sign-In**：原生 `ASAuthorization` 流程
- **Google Sign-In**：整合 GoogleSignIn SDK，支援多設備無縫切換
- **Web Auth**：後端提供 `/login` → Google/Apple OAuth callback → cookie-based admin session
- **Guest Mode**：未登入時仍允許查詞與本地儲存，帳號切換時自動清除舊帳號資料

### 生詞條目狀態管理

閱讀器中所有的生詞、以及知識庫中所有的卡片，在手機端都統一對應到同一個 SwiftData Model: `VocabularyEntry`。
我們透過 `syncStatus` 與 `actionType` 這兩個欄位來控制單字的狀態與流向。

- `syncStatus` 已由 `VocabularySyncState` 封裝：`pending` / `synced` / `failed`
- `actionType` 已由 `VocabularySyncAction` 封裝：`add` / `delete` / `edit`
- 實際持久化仍保留原始欄位，避免 SwiftData migration 成本，但業務邏輯應優先走 typed helper，如 `queueDelete()`、`markSynced()`
- 更完整的規則表見 [references/sync_lifecycle.md](references/sync_lifecycle.md)

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

支援格式：EPUB、TXT、MD、PDF（`BookshelfImportService` 統一入口，TXT/MD 經 `EPUBConverter` 轉 EPUB 後閱讀，PDF 走 `PDFReaderView` 獨立路徑）。macOS 端 Reader 暫不啟用（以 `#if os(iOS)` 隔離）。

1. **底線渲染 (Underline Rendering)**:
   打開書籍時，撈出所有非刪除的 `VocabularyEntry`，注入 JS 顯示底線。離線亦可。

2. **點擊單字 (Word Selection)**:
   - **已存在於本地**: 從 `VocabularyEntry` 取出翻譯/詞性/解釋瞬間顯示，`O(1)` 無網路。
   - **全新單字**: 並行觸發 Gemini API 翻譯 + Dictionary API 發音。翻譯時自動擷取 context sentence（書籍原文上下文）。儲存時寫入 `syncStatus = 0` 的 `VocabularyEntry`。

---

## 雙向同步機制 (BackgroundSyncActor & KGService)

App 實作了雙向同步流程，由 `BackgroundSyncActor`（`@ModelActor` 背景執行緒）驅動：

1. **Push Review State** — 推送本地複習狀態（`review_count`、`next_review_date` 等），LWW 策略以 `last_reviewed_at` 判定
2. **Push Daily Stats** — 推送每日複習統計
3. **Upload Deletes** — 找出 `actionType == "delete"` 項目，呼叫 API 刪除
4. **Upload Adds** — 找出 `syncStatus == 0` 新詞，POST 到 KG
5. **Fire-and-Forget Pipeline** — 呼叫 `/api/pipeline` 觸發背景 AI 處理（Enrich → Embed → Judge → Difficulty），每次執行寫入 `pipeline_log.db` 記錄 per-run/step timing + status + items
6. **Pull & Merge** — `pullCardsToLocal`：
   - 增量同步（`since` 時間戳），只拉異動過的 KGCard
   - 背景執行緒合併翻譯、詞性、難度、graph links
   - 全量同步時做 Orphan Cleanup（安全閾值 50 筆 / ratio < 0.8 保護）

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

### Chrome Extension Sync

Chrome Extension 走 REST API 直連，不經 iOS sync pipeline：
- `POST /api/vocab` + `POST /api/pipeline`（fire-and-forget）
- Auth token 從 options page 設定，存 `chrome.storage.local`

---

## 莫蘭迪 UI 視覺系統

系統透過 CSS 與 JS 注入到 Readium，實行極簡的莫蘭迪色調 (Morandi Aesthetic)：

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
- Reader panel / header / loading → `panelState`、`headerState`、`loadingState`
- Review reveal / navigation / swap → `reviewRevealSpring`、`reviewNavigationSpring`、`reviewCardSwapSpring`
- Sync phase / step update → `phaseChange`、`feedbackPulse`

這層規範的主文檔在 `docs/dev/ui-design.md` 的 `Motion Contract`。
若要改動畫規則，先更新該文檔，再修改程式；若是查編譯或 SwiftUI 實作錯誤，回 `docs/dev/ios-dev.md`。
若要確認現有有哪些可重用 UI 零件與互動模式，查 `docs/references/ui_component_pattern_inventory.md`。
若要確認各主畫面有哪些狀態已覆蓋、哪些還沒補齊，查 `docs/references/ui_state_matrix.md`。
若要查 backend 部署、debug、測試與格式規範入口，查 `docs/dev/backend-dev.md`。
