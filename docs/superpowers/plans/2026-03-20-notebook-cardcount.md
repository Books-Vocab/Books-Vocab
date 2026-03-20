# NotebookListView cardCount/dueCount N+1 修復

Branch: `worktree-notebook-cardcount`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 問題

NotebookListView 中，ForEach notebook 內呼叫 `cardCount(for:)` 和 `dueCount(for:)` 在每次 body 更新時遍歷完整 `allEntries` 陣列做 filter。100 notebook × 10K 詞條 = 200 次陣列遍歷。

## Tasks

### Task 1: 分析現況
讀取 `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift` 完整檔案，找到：
- `allEntries` 的 @Query 定義
- `cardCount(for:)` 和 `dueCount(for:)` 的實作
- ForEach 中如何呼叫這些方法

### Task 2: 重構為預計算 Dictionary
在 body 或 computed property 中，一次遍歷 allEntries 建立兩個 Dictionary：
```swift
private var cardCounts: [String: Int]  // notebookId → count
private var dueCounts: [String: Int]   // notebookId → due count
```
這樣 ForEach 內部只是 dictionary lookup（O(1)），而非每次 filter 整個陣列。

### Task 3: 更新 ForEach 中的呼叫
將 `cardCount(for: notebook)` 改為 `cardCounts[notebook.remoteId] ?? 0`，同理 dueCount。

### Task 4: 移除舊的 helper 方法
刪除 `cardCount(for:)` 和 `dueCount(for:)` 方法。

### Task 5: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 不再有 N+1 遍歷
- 功能不變
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
