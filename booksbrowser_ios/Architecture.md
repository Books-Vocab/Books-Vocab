# 🏗 BooksBrowser Architecture (Offline-First & Multi-User)

BooksBrowser 採用**離線優先 (Offline-first)** 的資料庫架構，以裝置端的 `SwiftData` 為唯一資訊來源 (Single Source of Truth)，並透過背景同步與遠端 Knowledge Graph (KG) 伺服器保持資料一致。完整的帳戶隔離機制確保多用戶與多設備場景下的資料安全。

---

## 💾 核心資料模型: `VocabularyEntry` & `AuthManager`

### 多帳戶認證架構

**AuthManager** (`AuthManager.swift`) 負責全應用的認證與帳號管理：
- **isLoggedIn**: 用戶是否已登入（Google Sign-In 或自訂 User ID）
- **userId**: 當前活躍帳戶的 ID（Google ID 或自訂密語），儲存於 Keychain
- **token**: 不透明的認證令牌，用於 KG API 呼叫的 `Authorization: Bearer` 標頭
- **Google Sign-In 支持**：整合 GoogleSignIn SDK，支援多設備無縫切換
- **Guest Mode**：未登入時仍允許查詞與本地儲存，帳號切換時自動清除舊帳號資料

### 生詞條目狀態管理

閱讀器中所有的生詞、以及知識庫中所有的卡片，在手機端都統一對應到同一個 SwiftData Model: `VocabularyEntry`。
我們透過 `syncStatus` 與 `actionType` 這兩個欄位來控制單字的狀態與流向。

- `syncStatus` 已由 `VocabularySyncState` 封裝：`pending` / `synced` / `failed`
- `actionType` 已由 `VocabularySyncAction` 封裝：`add` / `delete` / `edit`
- 實際持久化仍保留原始欄位，避免 SwiftData migration 成本，但業務邏輯應優先走 typed helper，如 `queueDelete()`、`markSynced()`
- 更完整的規則表見 [../docs/sync_lifecycle.md](../docs/sync_lifecycle.md)

| `syncStatus` | `actionType` | 含義 | 在哪裡顯示？ |
|-------------|--------------|------|-------------|
| 0 | `"add"` (預設) | **待收錄**：在手機新增，但尚未上傳至 KG 伺服器 | `VocabularyListView` 頁籤「待收錄」清單、`SyncView` 的上傳階段 |
| 1 | `"add"` | **知識庫**：已經與 KG 伺服器同步過，存在於雲端的單字 | `KGVocabView` 頁籤「知識庫」清單 |
| 0 / 1 | `"delete"` | **待刪除**：使用者在手機點擊刪除，等待上傳告訴 KG 伺服器也要刪除 | 隱藏不顯示，僅在 `SyncView` 執行刪除 Request |

> **注意：執行緒安全 & 帳號隔離**
> - 所有與後端同步並寫入 SwiftData 的操作，都會使用獨立的背景 `ModelContext` 來執行，避免 UI 卡頓
> - 帳號切換時，`AuthManager.logout()` 會自動呼叫 `KGService.clearLocalData()` 以清除舊帳號的 SwiftData，確保完全隔離

---

## 📖 閱讀器 (ReaderView) 的離線運作

1. **底線渲染 (Underline Rendering)**:
   打開 EPUB 書籍時，`ReaderView` 會直接發起一個 `@Query`，撈出所有 `actionType != "delete"` 的 `VocabularyEntry`。
   這包字串陣列被送到 `ReadiumNavigatorView` 的 WebView 裡注入 JS。因此，只要是資料庫裡有的單字，即使沒有網路也能立刻出現藍色底線。

2. **點擊單字 (Word Selection)**:
   - **已存在於本地 (命中 Query)**: 點擊時，從該筆 `VocabularyEntry` 取出 `translation`, `partOfSpeech`, `explanation` 瞬間顯示在面板上，這是一個 `O(1)` 的無網路操作。
   - **全新單字 (未命中 Query)**: 面板彈出，並行觸發 Gemini API 獲取 AI 翻譯，以及 Dictionary API 獲取預設發音。儲存時寫入一筆 `syncStatus = 0` 的 `VocabularyEntry`。

---

## 🔄 雙向同步機制 (SyncView & KGService)

為了保持本地的離線資料與遠端 KG 伺服器一致，App 實作了雙向同步流程 (Two-way Sync Pipeline)：

1. **上傳刪除 (Upload Deletes)**
   App 找出所有 `actionType == "delete"` 的項目，呼叫 API 請 KG 後端刪除該單字。成功後，把這筆紀錄從手機徹底刪除。
2. **上傳新增 (Upload Adds)**
   App 找出所有 `syncStatus == 0` 的項目，這些是剛在書本裡查到的新單字。呼叫 API 送去 KG，成功後 KG 會開始背景 Pipeline（AI Enrichment -> Link -> Difficulty -> Optional External Sync）。
3. **觸發 AI 處理 (Fire-and-Forget)**
   呼叫 `/api/pipeline` 交由伺服器在背景 (`BackgroundTasks`) 處理（AI Enrichment -> Link -> Difficulty -> Optional External Sync），App 收回控制權準備進入第四步。同步頁目前只顯示本地工作流進度，不再維持 SSE 連線監看伺服器內部步驟。
4. **下載遠端知識庫 (Pull & Merge)**
   這也是最關鍵的最後一步！當遠端處理完畢後，執行 `pullCardsToLocal`：
   - 帶上本地儲存的 `kg_last_incremental_sync` 時間戳記，發起 `api/vocab` 將遠端伺服器 *異動過* 的 KGCard 抓下來（**增量同步 Incremental Sync**）。
   - 在**背景執行緒 (Background Context)** 遍歷所有下載的卡片，將最新的翻譯、AI 詞性、難易度 `difficultyTier`，甚至是軟刪除標記 (`isDeleted`) **合併與覆寫**進本地的 `VocabularyEntry`。
   - 確保他們的 `syncStatus` 統一設為 `1`。
   - **清理孤兒 (Orphan Cleanup)**：只有在進行**全量同步 (Full Sync)** 時，如果本地有 `syncStatus == 1` 的資料，但在抓下來的 KGCard 列表裡找不到，代表它在遠端被物理刪除，手機本地也會立刻觸發 `context.delete()` 來保持資料同步。

---

## 🎨 莫蘭迪 UI 視覺系統

系統透過 CSS 與 JS 注入到 Readium，實行了極簡的莫蘭迪色調 (Morandi Aesthetic)：

- **字體 (Typography)**: 預設英文字體為 `Athelas` (Apple 原生高品質字體)，搭配 `Biotif` 作為中性且清晰的介面與等寬字型。
- **透明度控制 (Underline Opacity)**:
  透過 `ReaderSettings` 面板可調節 `--vocab-opacity` 這個 CSS Variable，最高可把底線調整為 0% (完全隱藏)。
  這個設定值保存在 `UserDefaults`，每次翻頁或設定異動時會透過 JS 即時套用至 DOM，不再需要重新 reload 書本。
- **介面隱形化 (Invisible UI)**:
  底線不使用強烈的 border，改用柔和的 `linear-gradient` 底色覆蓋；點擊高亮 (Active Word) 不採用深色 Highlight，而是利用低對比度的粗邊框與 4% Alpha 的底色框住單字，達成「克制的存在感」。

### Motion Layer

除了色彩、字體與材質，BooksBrowser 現在也把 motion 視為設計系統的一部分。

- 動畫語意層集中在 `BooksBrowser/Models/AppMetrics.swift` 的 `AppMotion`
- 共享 transition 也集中在同一檔案，避免 feature 各自發明不同進出方式
- Reader、Review、Sync 是目前優先完成收斂的三條主路徑

目前映射原則：
- Reader panel / header / loading → `panelState`、`headerState`、`loadingState`
- Review reveal / navigation / swap → `reviewRevealSpring`、`reviewNavigationSpring`、`reviewCardSwapSpring`
- Sync phase / step update → `phaseChange`、`feedbackPulse`

這層規範的主文檔在 `docs/ui-design.md` 的 `Motion Contract`。
若要改動畫規則，先更新該文檔，再修改程式；若是查編譯或 SwiftUI 實作錯誤，回 `docs/ios-dev.md`。
