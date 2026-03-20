# Concurrency & 現代化修正

Branch: `worktree-concurrency-modernize`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 目標

修正 onChange 舊式簽名、補齊 @MainActor 標註、GraphWebView 更新合併。

## Tasks

### Task 1: onChange 簽名升級

搜尋所有 `.onChange(of:` 使用點，找出用舊式 2 參數 closure 的（即 `{ oldValue, newValue in` 或 `_ newValue in` 而非 `{ _, newValue in }`）。

注意：iOS 17 的 onChange 簽名是：
```swift
.onChange(of: value) { oldValue, newValue in }
```
而 iOS 16 的舊式是：
```swift
.onChange(of: value, perform: { newValue in })
```

找出所有仍用 iOS 16 舊式的地方，升級為 iOS 17 簽名。

主要檔案（根據分析）：
- `ios/BooksBrowser/Views/Settings/SettingsView.swift`
- 其他可能的檔案（用 grep 搜尋 `.onChange(of:` + `perform:` 模式）

### Task 2: @MainActor 標註補齊

搜尋所有 Coordinator 類（grep `class.*Coordinator`），確認是否標註 `@MainActor`。

需要補齊的（根據分析）：
- `KGVocabCoordinator`
- `SyncCoordinator`
- 其他缺少標註的 Coordinator

注意：如果 Coordinator 已經是 `@Observable`，Swift 6 可能已經隱式推導 @MainActor。先確認現有標註再決定是否需要補。

### Task 3: Task { @MainActor in } → MainActor.run

搜尋 `Task { @MainActor in` 或 `Task { await MainActor.run` 模式。如果外層已在 @MainActor 環境中，直接移除 Task 包裝。如果確實需要跳線程，改為更明確的寫法。

### Task 4: GraphWebView 更新合併

讀取 `ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift`。

在 `updateUIView` 中，theme/forces/data 三層變化目前各自獨立觸發 JavaScript 注入。加入簡單的合併策略：
- 使用 signature 比較（已有 lastThemeSignature 等）確保不重複呼叫
- 如果多個屬性同時變化，只呼叫一次 sendInitGraph

### Task 5: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 零 iOS 16 舊式 onChange 簽名
- Coordinator 類有正確的 @MainActor 標註
- GraphWebView 不重複注入 JavaScript
- 編譯通過

## Files Modified
- 多個 View 檔案（onChange 升級）
- Coordinator 檔案（@MainActor）
- `ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift`
