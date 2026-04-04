# Platform Adapter Consolidation — Design Spec

## 問題

42 個 inline `#if os()` 分散在 24 個 Swift 檔案中。每次新增跨平台功能，開發者需手動在每個 View 加平台分支，沒有機制提醒遺漏。

## 目標

1. 把重複的雙平台行為差異收進 `Platform/` adapter 層
2. 統一 detail routing（iOS sheet vs macOS inspector），消除手動接 `MacDetailState` 的模式
3. 預估消除 ~20 個 inline `#if os()` 區塊

## 不做

- PlatformContext 環境值（2 平台 compile-time 已知，不需 runtime 查詢）
- 改動 iOS-only 功能門控（Reader/Bookshelf 整檔 `#if os(iOS)` 保持不變）
- 改動 macOS-only chrome（鍵盤快捷鍵、help overlay 保持原位）

---

## Part A：擴充 PlatformCompatibility View Extensions

在 `Platform/PlatformCompatibility.swift` 新增以下 modifier：

### A1: `.platformTextInputConfig()`
```swift
// 現狀：4 處手動寫 #if os(iOS) .textInputAutocapitalization(.never) #endif
@ViewBuilder
func platformTextInputConfig() -> some View {
    #if os(iOS)
    self.textInputAutocapitalization(.never).autocorrectionDisabled()
    #else
    self.autocorrectionDisabled()
    #endif
}
```
影響檔案：`AddLinkSheet`, `KGVocabPresenter`（搜尋欄），其他 TextField 出現處。

### A2: `.platformListButtonStyle()`
```swift
// 現狀：NotebookListView 手動分支 .buttonStyle(.pressable) vs .buttonStyle(.plain)
@ViewBuilder
func platformListButtonStyle() -> some View {
    #if os(iOS)
    self.buttonStyle(.pressable)
    #else
    self.buttonStyle(.plain)
    #endif
}
```

### A3: `.platformContentMaxWidth(_ width: CGFloat = 600)`
```swift
// 現狀：TodayReviewPresenter 手動 #if os(iOS) .frame(maxWidth:600).frame(maxWidth:.infinity)
@ViewBuilder
func platformContentMaxWidth(_ width: CGFloat = 600) -> some View {
    #if os(iOS)
    self.frame(maxWidth: width).frame(maxWidth: .infinity)
    #else
    self.frame(maxWidth: .infinity)
    #endif
}
```

### A4: `.platformHideNavigationBar()`
```swift
// 現狀：TodayReviewPresenter 手動 #if os(iOS) .toolbar(.hidden, for: .navigationBar)
@ViewBuilder
func platformHideNavigationBar() -> some View {
    #if os(iOS)
    self.toolbar(.hidden, for: .navigationBar)
    #else
    self
    #endif
}
```

### A5: `.platformRefreshable(action:)`
```swift
// 現狀：KGVocabPresenter 手動 #if os(iOS) .refreshable { ... }
@ViewBuilder
func platformRefreshable(action: @escaping () async -> Void) -> some View {
    #if os(iOS)
    self.refreshable { await action() }
    #else
    self
    #endif
}
```
注意：macOS 的 toolbar refresh button 是場景特定的，不適合抽入通用 modifier。此 modifier 僅處理 iOS 端。

### A6: `PlatformAccessibility.announce(_:)`
```swift
// 現狀：AppToastCoordinator 手動分支 UIAccessibility vs NSAccessibility
enum PlatformAccessibility {
    static func announce(_ message: String) {
        #if os(iOS)
        UIAccessibility.post(notification: .announcement, argument: message)
        #elseif os(macOS)
        NSAccessibility.post(element: NSApp as Any,
                           notification: .announcementRequested,
                           userInfo: [.announcement: message])
        #endif
    }
}
```

### A7: `.platformShareAction(url:)`
```swift
// 現狀：VocabularyListView+Sheets 手動分支 ShareSheet (UIActivityViewController) vs ShareLink
// 統一為一個 View
struct PlatformShareView: View {
    let url: URL
    var body: some View {
        #if os(iOS)
        ShareSheet(url: url)
        #else
        ShareLink(item: url).padding()
        #endif
    }
}
```

### A8: `PlatformStore.manageSubscriptions(in:)`
```swift
// 現狀：SubscriptionPaywallSheet 手動分支 AppStore vs NSWorkspace
enum PlatformStore {
    @MainActor
    static func manageSubscriptions(in scene: Any? = nil) async {
        #if os(iOS)
        if let scene = scene as? UIWindowScene {
            try? await AppStore.showManageSubscriptions(in: scene)
        }
        #elseif os(macOS)
        if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
            NSWorkspace.shared.open(url)
        }
        #endif
    }
}
```

---

## Part B：DetailRouter — 統一 detail routing

### 問題分析

目前 5 個 View 需要顯示 word detail 或 review session：
1. `VocabularyListView+Sheets` — iOS: sheet/fullScreenCover; macOS: onChange → macDetail
2. `NotebookListView` — iOS: platformFullScreenCover; macOS: onChange → macDetail
3. `KnowledgeGraphView` — iOS: toastSheet; macOS: onChange → macDetail，fallback toastSheet
4. `WordDetailSheet` — link tap 時：macOS 有 macDetail 走 inspector，否則走 overlay stack
5. `KGVocabView` → `VocabularyListView+State` — macOS 透過 onEntrySelected callback 傳出

### 設計

引入 `DetailRouter` protocol + 兩個平台實作，透過 Environment 注入。

```swift
// Platform/DetailRouter.swift

/// 統一 detail 呈現的路由介面
@MainActor
protocol DetailRouting: Observable {
    /// 顯示單字詳情
    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry])
    /// 顯示複習 session
    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry])
    /// 關閉 detail
    func dismiss()
    /// 目前是否有 detail 顯示中
    var hasDetail: Bool { get }
    /// 目前選中的 entry（供 WordDetailSheet link tap 判斷）
    var selectedEntry: VocabularyEntry? { get }
    /// 目前的 review session
    var activeReviewSession: TodayReviewSession? { get }
    /// 上下文 entries
    var contextEntries: [VocabularyEntry] { get }
}
```

**macOS 實作**：直接讓現有 `MacDetailState` conform `DetailRouting`（已有所有方法，只需加 protocol conformance）。

**iOS 實作**：`SheetDetailRouter`，內部用 `@Published` 驅動 sheet 呈現。

```swift
#if os(iOS)
@Observable @MainActor
final class SheetDetailRouter: DetailRouting {
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
#endif
```

**Environment Key**：

```swift
/// Type-erased wrapper — existential `any DetailRouting` 會斷掉 @Observable tracking，
/// 必須用 concrete class 包裝。
@Observable @MainActor
final class AnyDetailRouter: DetailRouting {
    private let _showWord: (VocabularyEntry, [VocabularyEntry]) -> Void
    private let _showReview: (TodayReviewSession, [VocabularyEntry]) -> Void
    private let _dismiss: () -> Void
    private let _state: any DetailRouting

    init<T: DetailRouting>(_ base: T) {
        _state = base
        _showWord = { base.showWordDetail($0, allEntries: $1) }
        _showReview = { base.showReview($0, allEntries: $1) }
        _dismiss = { base.dismiss() }
    }

    var hasDetail: Bool { _state.hasDetail }
    var selectedEntry: VocabularyEntry? { _state.selectedEntry }
    var activeReviewSession: TodayReviewSession? { _state.activeReviewSession }
    var contextEntries: [VocabularyEntry] { _state.contextEntries }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) { _showWord(entry, allEntries) }
    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) { _showReview(session, allEntries) }
    func dismiss() { _dismiss() }
}

private struct DetailRouterKey: EnvironmentKey {
    static let defaultValue: AnyDetailRouter? = nil
}

extension EnvironmentValues {
    var detailRouter: AnyDetailRouter? {
        get { self[DetailRouterKey.self] }
        set { self[DetailRouterKey.self] = newValue }
    }
}
```

**注入點**：`NotebookListView` 建立 router 實例並注入 environment。
- macOS：沿用 `MacDetailState()`，conform `DetailRouting`
- iOS：建立 `SheetDetailRouter()`

**消費端統一寫法**（取代各處 `#if os()` 分支）：

```swift
// 之前
#if os(macOS)
@Environment(\.macDetail) private var macDetail
#endif

// 之後
@Environment(\.detailRouter) private var detailRouter

// 之前（5 處各自的 onChange/sheet 分支）
#if os(iOS)
.platformFullScreenCover(item: $activeReviewSession) { ... }
#elseif os(macOS)
.onChange(of: activeReviewSession) { _, session in
    if let session { macDetail.showReview(session, allEntries: allEntries) }
}
#endif

// 之後
Button("開始") {
    detailRouter?.showReview(session, allEntries: allEntries)
}
```

**Detail 呈現層**：集中在 `NotebookListView`，根據平台決定呈現方式：
- macOS：維持 `safeAreaInset(edge: .trailing)` inspector（已有，不動）
- iOS：新增統一的 `.detailSheetPresenter(router:sizeClass:)` modifier，處理 sheet/fullScreenCover
  - **sizeClass 分流**：compact (iPhone) 用 `platformFullScreenCover` 呈現 review；regular (iPad) 用 `toastSheet(.large)` 呈現 review。Word detail 統一用 `toastSheet(.large)`。此邏輯從 `VocabularyListView+Sheets` 搬入集中 modifier。

### 遷移策略

1. 先建立 `DetailRouting` protocol + `SheetDetailRouter` + environment key
2. 讓 `MacDetailState` conform `DetailRouting`
3. 逐一遷移 5 個消費端（每遷一個跑 build 驗證）
4. 刪除 `\.macDetail` environment key（用 `\.detailRouter` 取代）

---

## 影響範圍

### 新增檔案
- `Platform/DetailRouter.swift` — protocol + iOS impl + environment key

### 修改檔案（Part A — View extensions）
- `Platform/PlatformCompatibility.swift` — 新增 8 個 modifier/helper
- `Views/Vocabulary/Scenes/AddLinkSheet.swift` — 用 `.platformTextInputConfig()`
- `Views/Vocabulary/Scenes/KGVocabPresenter.swift` — 用 `.platformTextInputConfig()` + `.platformRefreshable()`
- `Views/Vocabulary/Scenes/NotebookListView.swift` — 用 `.platformListButtonStyle()`
- `Views/Vocabulary/Scenes/TodayReviewPresenter.swift` — 用 `.platformContentMaxWidth()` + `.platformHideNavigationBar()`
- `UIComponents/AppToastCoordinator.swift` — 用 `PlatformAccessibility.announce()`
- `Views/Settings/SubscriptionPaywallSheet.swift` — 用 `PlatformStore.manageSubscriptions()`
- `Views/Vocabulary/VocabularyListView+Sheets.swift` — 用 `PlatformShareView`

### 修改檔案（Part B — DetailRouter）
- `Views/Vocabulary/MacDetailState.swift` — conform `DetailRouting`，移除 `#if os(macOS)` 整檔 guard（改為 protocol 在此定義 + macOS impl）
- `Views/Vocabulary/VocabularyListView+Sheets.swift` — 用 `detailRouter` 取代 macOS 分支
- `Views/Vocabulary/VocabularyListView+State.swift` — 移除 macOS `onEntrySelected` 分支
- `Views/Vocabulary/VocabularyListView.swift` — 用 `@Environment(\.detailRouter)` 取代 `\.macDetail`
- `Views/Vocabulary/KnowledgeGraphView.swift` — 用 `detailRouter` 取代 macOS 分支
- `Views/Vocabulary/Scenes/WordDetailSheet.swift` — 用 `detailRouter` 取代 `macDetail`
- `Views/Vocabulary/Scenes/NotebookListView.swift` — 建立 router + 注入 + detail 呈現

### 不動的檔案
- `ContentView.swift` — tab 結構差異是功能門控，不適合抽象
- `BooksBrowserApp.swift` — iOS-only service 注入，不適合抽象
- `Views/Reader/*` — 整檔 iOS-only
- `TodayReviewView.swift` — macOS keyboard handling 是平台特有功能
- `TodayReviewPresenter+Toolbar.swift` — macOS shortcut rail 是平台特有 UI

## 風險

| 風險 | 緩解 |
|------|------|
| DetailRouter 改變 sheet 呈現時機 | 逐檔遷移，每步 build 驗證 |
| iOS SheetDetailRouter 的 sheet 生命週期與現有 coordinator 衝突 | 遷移時保持 coordinator 的 binding 語義 |
| macOS detail panel 行為改變 | MacDetailState 只加 protocol conformance，內部不動 |
