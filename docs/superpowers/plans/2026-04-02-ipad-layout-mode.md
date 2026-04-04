# iPad Layout Mode — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** iPad regular width 獲得跟 macOS 一致的 side panel 體驗，同時建立 LayoutMode enum 統一收口所有 compact/regular 判斷。
**Architecture:** LayoutMode enum 封裝 sizeClass + platform 判斷；合併 SheetDetailRouter + MacDetailState 為跨平台 DetailRouter；NotebookListView 用 LayoutMode 分支取代 `#if os()` 分支。
**Tech Stack:** SwiftUI, Swift Observation, `horizontalSizeClass`, `#if os()` compile-time branching

**Spec:** `docs/superpowers/specs/2026-04-02-ipad-layout-mode-design.md`

---

## Task 1: LayoutMode Enum

**Files:**
- Create: `ios/BooksBrowser/Platform/LayoutMode.swift`
- Test: iOS build (`./ops/ios_build.sh`)

- [ ] **Step 1: 建立 LayoutMode.swift**

```swift
//
//  LayoutMode.swift
//  BooksBrowser
//
//  統一 compact/regular layout 判斷

import SwiftUI

enum LayoutMode: Equatable {
    case compact
    case regular

    init(horizontalSizeClass: UserInterfaceSizeClass?) {
        #if os(macOS)
        self = .regular
        #else
        self = (horizontalSizeClass == .compact) ? .compact : .regular
        #endif
    }

    /// 是否使用 inline detail panel（而非 sheet）
    var usesInlineDetail: Bool {
        self == .regular
    }

    /// 內容最大寬度
    var contentMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity
        case .regular: return 720
        }
    }

    /// 書架封面高度
    var bookshelfCoverHeight: CGFloat {
        switch self {
        case .compact: return AppBookshelfMetrics.coverHeightCompact
        case .regular: return AppBookshelfMetrics.coverHeightRegular
        }
    }

    /// 書架 grid item
    var bookshelfGridItem: GridItem {
        switch self {
        case .compact: return GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        case .regular: return GridItem(.adaptive(minimum: 180, maximum: 240), spacing: AppShellMetrics.sectionSpacing)
        }
    }

    /// Reader header title max width
    var readerTitleMaxWidth: CGFloat {
        switch self {
        case .compact: return ReaderPresentationMetrics.Header.titleMaxWidth
        case .regular: return ReaderPresentationMetrics.Header.titleMaxWidthRegular
        }
    }
}
```

- [ ] **Step 2: 跑 build 確認編譯通過**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**
Message: `ios: add LayoutMode enum for unified compact/regular layout decisions`

---

## Task 2: 合併 DetailRouter

**Files:**
- Modify: `ios/BooksBrowser/Platform/DetailRouter.swift`
- Delete: `ios/BooksBrowser/Views/Vocabulary/MacDetailState.swift`
- Test: iOS build

- [ ] **Step 1: 修改 DetailRouter.swift — 移除 `#if os(iOS)` guard，重新命名 class**

將 `SheetDetailRouter` → `DetailRouter`，移除 `#if os(iOS)` / `#endif`。Protocol `DetailRouting` 和 environment key 不變。

修改前：
```swift
// MARK: - iOS Implementation

#if os(iOS)
@Observable @MainActor
final class SheetDetailRouter: DetailRouting {
    ...
}
#endif
```

修改後：
```swift
// MARK: - Concrete Implementation

@Observable @MainActor
final class DetailRouter: DetailRouting {
    var selectedEntry: VocabularyEntry?
    var activeReviewSession: TodayReviewSession?
    var contextEntries: [VocabularyEntry] = []

    var hasDetail: Bool { selectedEntry != nil || activeReviewSession != nil }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) {
        activeReviewSession = nil
        selectedEntry = entry
        contextEntries = allEntries
    }

    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) {
        selectedEntry = nil
        activeReviewSession = session
        contextEntries = allEntries
    }

    func dismiss() {
        selectedEntry = nil
        activeReviewSession = nil
        contextEntries = []
    }
}
```

- [ ] **Step 2: 刪除 MacDetailState.swift**

檔案路徑：`ios/BooksBrowser/Views/Vocabulary/MacDetailState.swift`

同時在 Xcode project 中移除引用（若有 `.pbxproj` 需更新）。

- [ ] **Step 3: 全域搜尋 `SheetDetailRouter` 和 `MacDetailState` 引用，替換為 `DetailRouter`**

已知引用點：
- `NotebookListView.swift:48` — `@State private var sheetRouter = SheetDetailRouter()` → 移除（Task 3 處理）
- `NotebookListView.swift:45` — `@State private var macDetail = MacDetailState()` → 移除（Task 3 處理）

若其他檔案有引用，一併替換。

- [ ] **Step 4: 跑 build 確認編譯通過**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 5: Commit**
Message: `ios: merge SheetDetailRouter + MacDetailState into cross-platform DetailRouter`

---

## Task 3: NotebookListView — LayoutMode 分支取代 `#if os()` 分支

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Test: iOS build

這是最大的改動。現有的 `#if os(iOS)` 和 `#if os(macOS)` 各 ~30 行的 detail 呈現邏輯，合併為 LayoutMode 分支。

- [ ] **Step 1: 替換 state 宣告**

修改前（第 44-49 行）：
```swift
    #if os(macOS)
    @State private var macDetail = MacDetailState()
    @State private var isEditingMacDetailEntry = false
    #elseif os(iOS)
    @State private var sheetRouter = SheetDetailRouter()
    #endif
```

修改後：
```swift
    @State private var detailState = DetailRouter()
    @State private var isEditingDetailEntry = false
```

- [ ] **Step 2: 替換 `onChange(of: activeReviewSession)` 的平台分支**

修改前（第 158-166 行）：
```swift
            .onChange(of: activeReviewSession) { _, session in
                if let session {
                    #if os(macOS)
                    macDetail.showReview(session, allEntries: allEntries)
                    #elseif os(iOS)
                    sheetRouter.showReview(session, allEntries: allEntries)
                    #endif
                    activeReviewSession = nil
                }
            }
```

修改後：
```swift
            .onChange(of: activeReviewSession) { _, session in
                if let session {
                    detailState.showReview(session, allEntries: allEntries)
                    activeReviewSession = nil
                }
            }
```

- [ ] **Step 3: 替換 detail 呈現區塊（第 206-265 行）— 從 `#if os` 改為 LayoutMode**

移除整個 `#if os(iOS)` ... `#elseif os(macOS)` ... `#endif` 區塊，替換為：

```swift
        .environment(\.detailRouter, detailState)
        .modifier(DetailPresentation(
            detailState: detailState,
            layoutMode: LayoutMode(horizontalSizeClass: sizeClass),
            allEntries: allEntries,
            currentUserID: authManager.userId,
            isEditingDetailEntry: $isEditingDetailEntry,
            navigationPath: $navigationPath
        ))
```

- [ ] **Step 4: 建立 DetailPresentation ViewModifier（在 NotebookListView.swift 底部或獨立 extension）**

```swift
private struct DetailPresentation: ViewModifier {
    let detailState: DetailRouter
    let layoutMode: LayoutMode
    let allEntries: [VocabularyEntry]
    let currentUserID: String?
    @Binding var isEditingDetailEntry: Bool
    @Binding var navigationPath: NavigationPath

    func body(content: Content) -> some View {
        if layoutMode.usesInlineDetail {
            content
                .safeAreaInset(edge: .trailing, spacing: 0) {
                    if detailState.hasDetail {
                        HStack(spacing: 0) {
                            Divider()
                            inlineDetailPanel
                                .frame(minWidth: 350, idealWidth: 420, maxWidth: 600)
                        }
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                    }
                }
                .animation(AppMotion.standardSpring, value: detailState.hasDetail)
                .onChange(of: navigationPath) { _, path in
                    if path.isEmpty { detailState.dismiss() }
                }
                .onChange(of: detailState.selectedEntry?.id) { _, entryID in
                    if entryID == nil { isEditingDetailEntry = false }
                }
                .toastSheet(isPresented: Binding(
                    get: { isEditingDetailEntry && detailState.selectedEntry != nil },
                    set: { isEditingDetailEntry = $0 }
                )) {
                    if let entry = detailState.selectedEntry {
                        WordEditSheet(entry: entry)
                    }
                }
        } else {
            content
                .toastSheet(item: Binding(
                    get: { detailState.selectedEntry },
                    set: { if $0 == nil { detailState.dismiss() } }
                )) { entry in
                    WordDetailSheet(entry: entry, allEntries: detailState.contextEntries)
                        .appSheet(.large)
                }
                .platformFullScreenCover(item: Binding(
                    get: { detailState.activeReviewSession },
                    set: { if $0 == nil { detailState.dismiss() } }
                )) { session in
                    TodayReviewView(
                        entries: session.entries,
                        allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                        currentUserID: currentUserID,
                        onClose: { detailState.dismiss() }
                    )
                    .toastOverlay()
                }
        }
    }

    @ViewBuilder
    private var inlineDetailPanel: some View {
        if let session = detailState.activeReviewSession {
            TodayReviewView(
                entries: session.entries,
                allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                currentUserID: currentUserID,
                onClose: { detailState.dismiss() }
            )
        } else if let entry = detailState.selectedEntry {
            VStack(spacing: 0) {
                VocabOverlayHeader(
                    title: entry.word,
                    systemImage: "character.book.closed",
                    onClose: { detailState.dismiss() },
                    trailing: {
                        VocabChromeIconButton(
                            systemImage: "pencil",
                            label: "編輯".localized,
                            action: { isEditingDetailEntry = true }
                        )
                    }
                )
                WordDetailSheet(
                    entry: entry,
                    allEntries: detailState.contextEntries,
                    wrapInNavigation: false,
                    showsInlineChrome: false
                )
            }
        }
    }
}
```

- [ ] **Step 5: 移除舊的 `macDetailPanel` computed property（第 337-371 行的 `#if os(macOS)` 區塊）**

整個 `#if os(macOS)` / `private var macDetailPanel` / `#endif` 刪除。

- [ ] **Step 6: 加入 LayoutMode 切換時的 auto-dismiss**

在 `DetailPresentation` modifier 的 `body` 最外層（`if layoutMode.usesInlineDetail` 之前）加入：

```swift
.onChange(of: layoutMode) { _, newMode in
    if !newMode.usesInlineDetail {
        // 從 regular 切到 compact（iPad split-screen 縮小），
        // dismiss inline detail 避免 stale state。
        // 設計決策：intentional dismiss — review session 會被中斷。
        // 理由：compact 的 fullScreenCover 無法從 inline panel 無縫接續，
        // 且 split-screen 切換本身就是使用者主動改變布局，重新開始複習是合理的。
        detailState.dismiss()
        isEditingDetailEntry = false
    }
}
```

注意：此 `onChange` 需要 `DetailPresentation` 的 `layoutMode` 是從外部每次 body re-evaluate 時傳入的值，不需要額外 `@State`。

- [ ] **Step 7: 跑 build 確認編譯通過**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 8: Commit**
Message: `ios: NotebookListView — LayoutMode-based detail presentation for iPad side panel`

---

## Task 4: 遷移其他 sizeClass 消費點

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderViewPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderViewPresenter+Headers.swift`
- Test: iOS build

- [ ] **Step 1: BookshelfView.swift — sizeClass → LayoutMode**

修改前：
```swift
    @Environment(\.horizontalSizeClass) private var sizeClass
    ...
    private var columns: [GridItem] {
        let item: GridItem = sizeClass == .regular
            ? GridItem(.adaptive(minimum: 180, maximum: 240), spacing: AppShellMetrics.sectionSpacing)
            : GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        return [item]
    }

    private var coverHeight: CGFloat {
        sizeClass == .regular ? AppBookshelfMetrics.coverHeightRegular : AppBookshelfMetrics.coverHeightCompact
    }
```

修改後：
```swift
    @Environment(\.horizontalSizeClass) private var sizeClass
    ...
    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    private var columns: [GridItem] { [layoutMode.bookshelfGridItem] }

    private var coverHeight: CGFloat { layoutMode.bookshelfCoverHeight }
```

- [ ] **Step 2: VocabularyListView.swift — 移除 sizeClass 傳遞**

修改前：
```swift
    @Environment(\.horizontalSizeClass) var sizeClass
    ...
    .modifier(VocabularyListSheets(
        coordinator: coordinator,
        allEntries: allEntries,
        sizeClass: sizeClass
    ))
```

修改後：
```swift
    // 移除 @Environment(\.horizontalSizeClass) var sizeClass（此 view 不再需要）
    ...
    .modifier(VocabularyListSheets(
        coordinator: coordinator,
        allEntries: allEntries
    ))
```

- [ ] **Step 3: VocabularyListView+Sheets.swift — 移除 sizeClass 參數**

修改前：
```swift
struct VocabularyListSheets: ViewModifier {
    @Bindable var coordinator: VocabularyListCoordinator
    let allEntries: [VocabularyEntry]
    let sizeClass: UserInterfaceSizeClass?
```

修改後：
```swift
struct VocabularyListSheets: ViewModifier {
    @Bindable var coordinator: VocabularyListCoordinator
    let allEntries: [VocabularyEntry]
```

- [ ] **Step 4: ReaderViewPresenter+Headers.swift — sizeClass → LayoutMode**

修改前（第 41-43 行）：
```swift
                    .frame(maxWidth: sizeClass == .regular
                        ? ReaderPresentationMetrics.Header.titleMaxWidthRegular
                        : ReaderPresentationMetrics.Header.titleMaxWidth)
```

修改後：
```swift
                    .frame(maxWidth: LayoutMode(horizontalSizeClass: sizeClass).readerTitleMaxWidth)
```

注意：`readerTitleMaxWidth` 已在 Task 1 的 `LayoutMode.swift` 中定義。`ReaderViewPresenter.swift` 本身的 `@Environment(\.horizontalSizeClass) var sizeClass` 保留（因為 extension 中引用），改為透過 computed property `var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }` 間接使用。

- [ ] **Step 5: 跑 build 確認編譯通過**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 6: Commit**
Message: `ios: migrate sizeClass consumers to LayoutMode`

---

## Task 5: platformContentMaxWidth 更新

**Files:**
- Modify: `ios/BooksBrowser/Platform/PlatformCompatibility.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift`
- Test: iOS build

- [ ] **Step 1: 在 PlatformCompatibility.swift 新增 LayoutMode-aware 版本**

在現有 `platformContentMaxWidth` 下方加入：

```swift
    @ViewBuilder
    func platformContentMaxWidth(for layoutMode: LayoutMode) -> some View {
        self.frame(maxWidth: layoutMode.contentMaxWidth)
            .frame(maxWidth: .infinity)
    }
```

- [ ] **Step 2: TodayReviewPresenter.swift — 用 LayoutMode-aware 版本**

找到 `.platformContentMaxWidth()` 呼叫（第 171 行），替換為：

```swift
.platformContentMaxWidth(for: LayoutMode(horizontalSizeClass: sizeClass))
```

若 TodayReviewPresenter 尚未有 `sizeClass`，需加入 `@Environment(\.horizontalSizeClass) private var sizeClass`。

- [ ] **Step 3: 移除舊的無參數 `platformContentMaxWidth()` 方法**

確認無其他呼叫點後，刪除舊版本：

```swift
    // 刪除
    @ViewBuilder
    func platformContentMaxWidth(_ width: CGFloat = 600) -> some View { ... }
```

- [ ] **Step 4: 跑 build 確認編譯通過**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 5: Commit**
Message: `ios: platformContentMaxWidth now LayoutMode-aware (600→720 for regular)`

---

## Task 6: 最終驗證

- [ ] **Step 1: 跑完整 build**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 2: 確認 `#if os` 減少**
Run: `grep -r '#if os' ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift | wc -l`
Expected: 0（NotebookListView 不再有 `#if os` 分支，除非有其他非 detail 相關的分支）

- [ ] **Step 3: 確認 MacDetailState.swift 已刪除**
Run: `test ! -f ios/BooksBrowser/Views/Vocabulary/MacDetailState.swift && echo "DELETED"`
Expected: DELETED

- [ ] **Step 4: 確認 LayoutMode 消費點**
Run: `grep -r 'LayoutMode' ios/BooksBrowser/ --include='*.swift' -l`
Expected: LayoutMode.swift + BookshelfView + NotebookListView + ReaderViewPresenter + PlatformCompatibility + TodayReviewPresenter
