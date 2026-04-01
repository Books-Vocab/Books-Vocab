# macOS Inspector Panel Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** macOS 上將 WordDetailSheet 和 TodayReviewView 從 sheet 改為 `.inspector()` 右側面板，解決內容裁切問題。
**Architecture:** 在 VocabularyListView 和 NotebookListView 加 macOS-only `.inspector()` modifier，coordinator state 驅動內容切換，iOS 完全不動。
**Tech Stack:** SwiftUI `.inspector(isPresented:)` (macOS 14+)

---

### Task 1: VocabularyListView+Sheets — macOS 分支移除 sheet

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift:29-69`

- [ ] **Step 1: macOS 分支跳過 selectedEntry 和 activeReviewSession 的 sheet**

在 `VocabularyListSheets.body` 中，將 `selectedEntry` sheet 和 `activeReviewSession` sheet 用 `#if os(iOS)` / `#endif` 包裹，macOS 不掛這些 sheet（改由 inspector 負責）。

```swift
// line 29-32: selectedEntry sheet — 僅 iOS
#if os(iOS)
.toastSheet(item: $coordinator.selectedEntry) { entry in
    WordDetailSheet(entry: entry, allEntries: allEntries)
        .appSheet(.large)
}
#endif

// line 33-69: activeReviewSession — 已有 #if os(iOS)/#elseif os(macOS)，移除 macOS 分支
#if os(iOS)
.platformFullScreenCover(item: Binding(
    get: { sizeClass == .compact ? coordinator.activeReviewSession : nil },
    set: { coordinator.activeReviewSession = $0 }
)) { session in
    TodayReviewView(
        entries: session.entries,
        allEntries: allEntries,
        currentUserID: AuthManager.shared.userId,
        onClose: { coordinator.activeReviewSession = nil }
    )
    .toastOverlay()
}
.toastSheet(item: Binding(
    get: { sizeClass == .regular ? coordinator.activeReviewSession : nil },
    set: { coordinator.activeReviewSession = $0 }
)) { session in
    TodayReviewView(
        entries: session.entries,
        allEntries: allEntries,
        currentUserID: AuthManager.shared.userId,
        onClose: { coordinator.activeReviewSession = nil }
    )
    .appSheet(.large)
}
#endif
// macOS 的 .platformFullScreenCover 整段刪除
```

- [ ] **Step 2: Build 確認**
Run: `./ops/ios_build.sh`

---

### Task 2: VocabularyListView — 加 macOS inspector

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift:48-104`

- [ ] **Step 1: 加 inspector modifier（macOS only）**

在 `VocabularyListView.body` 的 modifier chain 中，`VocabularyListSheets` 之後加：

```swift
#if os(macOS)
.inspector(isPresented: Binding(
    get: { coordinator.selectedEntry != nil || coordinator.activeReviewSession != nil },
    set: { isPresented in
        if !isPresented {
            coordinator.activeReviewSession = nil
            coordinator.selectedEntry = nil
        }
    }
)) {
    macInspectorContent
        .inspectorColumnWidth(min: 350, ideal: 420, max: 600)
}
#endif
```

- [ ] **Step 2: 加 macInspectorContent computed property**

```swift
#if os(macOS)
@ViewBuilder
private var macInspectorContent: some View {
    if let session = coordinator.activeReviewSession {
        TodayReviewView(
            entries: session.entries,
            allEntries: allEntries,
            currentUserID: AuthManager.shared.userId,
            onClose: { coordinator.activeReviewSession = nil }
        )
    } else if let entry = coordinator.selectedEntry {
        WordDetailSheet(
            entry: entry,
            allEntries: allEntries,
            wrapInNavigation: false
        )
    }
}
#endif
```

- [ ] **Step 3: Build 確認**
Run: `./ops/ios_build.sh`

---

### Task 3: NotebookListView — 跨本複習也用 inspector

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:154-165`

- [ ] **Step 1: macOS 分支改 inspector**

將現有的：
```swift
.platformFullScreenCover(item: $activeReviewSession) { session in
    TodayReviewView(...)
    .toastOverlay()
    #if os(macOS)
    .frame(minWidth: 500, minHeight: 600)
    #endif
}
```

改為平台分支：
```swift
#if os(iOS)
.platformFullScreenCover(item: $activeReviewSession) { session in
    TodayReviewView(
        entries: session.entries,
        allEntries: allEntries,
        currentUserID: authManager.userId,
        onClose: { activeReviewSession = nil }
    )
    .toastOverlay()
}
#elseif os(macOS)
.inspector(isPresented: Binding(
    get: { activeReviewSession != nil },
    set: { if !$0 { activeReviewSession = nil } }
)) {
    if let session = activeReviewSession {
        TodayReviewView(
            entries: session.entries,
            allEntries: allEntries,
            currentUserID: authManager.userId,
            onClose: { activeReviewSession = nil }
        )
    }
}
#endif
```

- [ ] **Step 2: Build 確認**
Run: `./ops/ios_build.sh`

---

### Task 4: TodayReviewPresenter — 適應 inspector 寬度

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift:154`

- [ ] **Step 1: 移除 maxWidth 600 限制（inspector 寬度本身已受控）**

```swift
// 原本
.frame(maxWidth: 600)
.frame(maxWidth: .infinity)

// 改為
#if os(iOS)
.frame(maxWidth: 600)
.frame(maxWidth: .infinity)
#else
.frame(maxWidth: .infinity)
#endif
```

- [ ] **Step 2: Build + 視覺驗證**
Run: `./ops/ios_build.sh`
在 macOS 上啟動 app，驗證 inspector 中複習卡片佈局正常。

---

### Task 5: 端到端驗證

- [ ] **Step 1: macOS 驗證**
  - 點單字 → inspector 開啟顯示 WordDetailSheet，內容可完整滾動
  - 啟動複習 → inspector 切換為 TodayReviewView，底部按鈕可見
  - 複習完成 → inspector 自動關閉
  - 複習中選單字 → review 優先顯示
  - NotebookList 跨本複習 → inspector 正常

- [ ] **Step 2: iOS 回歸驗證**
  - iPhone: 單字 detail → sheet，複習 → fullScreenCover
  - iPad: 單字 detail → large sheet，複習 → large sheet

- [ ] **Step 3: Commit**
