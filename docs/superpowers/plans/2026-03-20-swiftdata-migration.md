# SwiftData Migration 策略

Branch: `worktree-swiftdata-migration`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 問題

VocabularyEntry 新增了 #Index 和 optional 欄位（rootForm、inflections 等），但無版本管理策略。舊用戶升級時索引會沈默重建，可能卡住啟動。

## Tasks

### Task 1: 分析現況
讀取以下檔案了解 SwiftData 設定：
- `ios/BooksBrowser/Models/VocabularyEntry.swift` — 完整 model 定義
- `ios/BooksBrowser/BooksBrowserApp.swift` — ModelContainer 配置
- 搜尋 `ModelContainer`、`Schema`、`VersionedSchema`、`SchemaMigrationPlan` 在整個 ios/ 目錄

### Task 2: 評估 migration 需求
根據 Task 1 的發現：
- 如果已有 VersionedSchema → 新增版本
- 如果沒有 → 評估是否需要（SwiftData 對 optional 新欄位自動處理）
- 確認 #Index 變更是否需要 migration（SwiftData 自動處理索引變更，不需要顯式 migration）

### Task 3: 實作必要的 migration
根據 Task 2 的評估結果：
- 如果需要 VersionedSchema：建立 V1 和 V2 schema + migration plan
- 如果不需要：在 BooksBrowserApp.swift 中確保 ModelContainer 配置有 `isStoredInMemoryOnly: false` 和正確的 schema 設定
- 加上防禦性的 migration 錯誤處理（如果 container 初始化失敗，重建資料庫而非 crash）

### Task 4: 加入啟動安全檢查
在 App 啟動流程中加入：
- ModelContainer 初始化 try-catch
- 失敗時的 fallback 策略（例如刪除本地快取重新同步）
- 用 print/os_log 記錄 migration 結果

### Task 5: 編譯驗證
- `./ops/ios_build.sh`

## 注意
- 不要破壞現有用戶的資料
- SwiftData 在 iOS 17.4+ 對 lightweight migration 有良好支援
- 如果分析後認為不需要顯式 migration（SwiftData 自動處理），在 PR 中說明理由即可

## Files Modified
- `ios/BooksBrowser/BooksBrowserApp.swift`（或 ModelContainer 配置處）
- 可能新增 migration 相關檔案
