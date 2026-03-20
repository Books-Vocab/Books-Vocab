# SwiftData 效能修正 — @Query Predicate + @Index + 搜尋 debounce

Branch: `worktree-swiftdata-perf`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 目標

修正 3 個缺 Predicate 的 @Query、為 VocabularyEntry 加 @Index、為搜尋欄加 debounce。

## Tasks

### Task 1: VocabularyEntry 加 @Index

讀取 `ios/BooksBrowser/Models/VocabularyEntry.swift`，在 `syncStatus`、`actionType`、`notebookId`、`dateAdded` 欄位加上 SwiftData `@Attribute` 的 `.spotlight` 或在 class 上使用 compound index。

注意：SwiftData 的索引方式是在 `@Model` class 上面加 `static var indexes: [[IndexColumn<Self>]]` 或使用 `Index<VocabularyEntry>` macro（iOS 17+）。請先讀檔案確認 SwiftData 版本和現有 schema 再決定語法。

### Task 2: StatsPresenter @Query 加 Predicate

讀取 `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`。

找到 `@Query var reviewRecords: [ReviewRecord]`（無 filter），改為帶 Predicate 的查詢。如果此處確實需要全部記錄（統計用途），可保留但加註解說明理由。如果可以過濾（例如只看某時間範圍），加上合適的 Predicate。

### Task 3: NotebookListView @Query 加 Predicate

讀取 `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`。

找到無 filter 的 `@Query(sort:) var allEntries: [VocabularyEntry]`。分析此 query 的用途 — 如果只是取 count，改用 `@Query(filter:)` 或改為 computed property。如果真的需要全部，改為更高效的 count query。

### Task 4: SettingsView @Query 加 Predicate

讀取 `ios/BooksBrowser/Views/Settings/SettingsView.swift`。

同理處理無 filter 的 `@Query var allEntries: [VocabularyEntry]`。

### Task 5: 搜尋 debounce

找到所有 searchText 綁定的 `.onChange(of: searchText)` 或直接綁定到 filter 的位置。加入 debounce 機制。

SwiftUI 原生方式：用 `.task(id: searchText)` 配合 `try? await Task.sleep(for: .milliseconds(300))` 實現 debounce，而非直接在 onChange 中過濾。

主要檔案：
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`（如果有 search）

### Task 6: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 所有 @Query 都有明確的 Predicate 或有註解說明為何需要全量查詢
- VocabularyEntry 有 index
- 搜尋有 debounce
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Models/VocabularyEntry.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- `ios/BooksBrowser/Views/Settings/SettingsView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
