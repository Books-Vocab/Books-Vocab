# VocabSceneShell — 統一狀態容器

Branch: `worktree-vocab-scene-shell`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 目標

提取 `VocabSceneShell<Content>` 元件，統一 Vocabulary 場景的 loading/empty/error/content 四態切換模式，消除 8 個檔案 13 處重複的 `VStack { Spacer; StateCard; Spacer }.padding().vocabCanvasBackground()` 模式。

## 設計

```swift
/// 統一 Vocabulary 場景的四態容器
struct VocabSceneShell<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin

    enum Phase {
        case loading(title: String, systemImage: String)
        case empty(title: String, systemImage: String, description: String)
        case error(title: String, systemImage: String, retryAction: () -> Void)
        case content
    }

    let phase: Phase
    @ViewBuilder let content: () -> Content
}
```

容器內部邏輯：
- loading → `VocabStateMessageCard` + `ProgressView`
- empty → `VocabEmptyStateCard`
- error → `VocabStateMessageCard` + retry Button
- content → 直接呈現 `content()`
- 所有非 content 態自動包裝 `VStack { Spacer(); card; Spacer() }.padding(vocabSkin.metrics.cardBlockPadding).vocabCanvasBackground()`

## Tasks

### Task 1: 建立 VocabSceneShell 元件
- 在 `ios/BooksBrowser/Views/Vocabulary/Components/` 下新增 `VocabSceneShell.swift`
- 實作上述 Phase enum + ViewBuilder 容器
- 支援 `@ViewBuilder accessory` 用於自訂 empty/error 狀態的 action 按鈕
- 加入 `#Preview` 覆蓋四態

### Task 2: 遷移 KGVocabView
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- 替換第 50-100 行的三個 if-else 分支為 `VocabSceneShell`
- 保留 content 區塊（第 101 行以後）原封不動

### Task 3: 遷移 StatsPresenter
- `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`
- 替換第 52-65 行的 loading 態

### Task 4: 遷移 PendingVocabPresenter
- `ios/BooksBrowser/Views/Vocabulary/Scenes/PendingVocabPresenter.swift`
- 替換第 28-44 行的 empty 態（注意此處用 ScrollView 容器 — SceneShell 需支援）

### Task 5: 遷移 KnowledgeGraphPresenter
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KnowledgeGraphPresenter.swift`
- 替換 `centeredStateCard` helper 為 SceneShell

### Task 6: 遷移 NotebookListView
- `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- 替換 empty state

### Task 7: 編譯驗證
- 執行 `./ops/ios_build.sh`
- 確認 exit 0

## Acceptance Criteria
- 所有遷移檔案使用 VocabSceneShell 取代手寫狀態容器
- 零 regression — UI 行為不變
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Views/Vocabulary/Components/VocabSceneShell.swift` (NEW)
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/PendingVocabPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KnowledgeGraphPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
