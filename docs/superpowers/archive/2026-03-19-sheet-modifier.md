# Sheet Presentation Modifier

Branch: `worktree-sheet-modifier`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 目標

提取 `.appSheet()` ViewModifier，消除 8 個檔案 21 處重複的 `.presentationDetents` + `.presentationDragIndicator` + `.presentationContentInteraction` 組合。

## 設計

```swift
enum AppSheetPreset {
    case large      // detents([.large]) + dragIndicator(.visible) + scrolls
    case medium     // detents([.medium])
    case adaptive   // detents([.medium, .large]) + dragIndicator(.visible)
}

extension View {
    func appSheet(_ preset: AppSheetPreset) -> some View { ... }
}
```

## Tasks

### Task 1: 建立 AppSheetModifier
- 在 `ios/BooksBrowser/UIComponents/` 新增 `AppSheetModifier.swift`
- 實作 3 種 preset

### Task 2: 替換所有使用點
- `ReaderView.swift` (2 處) → `.appSheet(.adaptive)`
- `ArchivedVocabSheet.swift` → `.appSheet(.large)`
- `KGVocabView.swift` (2 處) → `.appSheet(.large)` + `.appSheet(.medium)`
- `TodayReviewView.swift` → `.appSheet(.medium)`
- `KnowledgeGraphView.swift` → `.appSheet(.large)`
- `VocabularyListView+Sheets.swift` (2 處)
- `NotebookFilterChip.swift` → `.appSheet(.medium)`
- `NotebookEditSheet.swift` → `.appSheet(.medium)`

### Task 3: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 所有 21 處替換為 `.appSheet()`
- 編譯通過

## Files Modified
- `ios/BooksBrowser/UIComponents/AppSheetModifier.swift` (NEW)
- 8 個使用端檔案
