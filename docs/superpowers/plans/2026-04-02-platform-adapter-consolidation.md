# Platform Adapter Consolidation — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 把散落的 ~20 個 inline `#if os()` 收攏進集中式 adapter 層，降低新功能的多平台維護成本。
**Architecture:** Part A 擴充 `Platform/PlatformCompatibility.swift` 加 8 個 modifier/helper；Part B 引入 `DetailRouter` protocol 統一 detail routing。
**Tech Stack:** SwiftUI, Swift Observation, `#if os()` compile-time branching

**Spec:** `docs/superpowers/specs/2026-04-02-platform-adapter-consolidation-design.md`

---

## Task 1: Part A — PlatformCompatibility View Extensions

**Files:**
- Modify: `ios/BooksBrowser/Platform/PlatformCompatibility.swift`

- [ ] **Step 1: 新增 View extensions**

在 `extension View {` 區塊結尾（`macKeyResponder` 之後、`}` 之前）加入：

```swift
    @ViewBuilder
    func platformTextInputConfig() -> some View {
        #if os(iOS)
        self.textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        self.autocorrectionDisabled()
        #endif
    }

    @ViewBuilder
    func platformListButtonStyle() -> some View {
        #if os(iOS)
        self.buttonStyle(.pressable)
        #else
        self.buttonStyle(.plain)
        #endif
    }

    @ViewBuilder
    func platformContentMaxWidth(_ width: CGFloat = 600) -> some View {
        #if os(iOS)
        self.frame(maxWidth: width).frame(maxWidth: .infinity)
        #else
        self.frame(maxWidth: .infinity)
        #endif
    }

    @ViewBuilder
    func platformHideNavigationBar() -> some View {
        #if os(iOS)
        self.toolbar(.hidden, for: .navigationBar)
        #else
        self
        #endif
    }

    @ViewBuilder
    func platformRefreshable(action: @escaping () async -> Void) -> some View {
        #if os(iOS)
        self.refreshable { await action() }
        #else
        self
        #endif
    }
```

- [ ] **Step 2: 新增 PlatformAccessibility**

在 `PlatformClipboard` enum 之後加入：

```swift
enum PlatformAccessibility {
    /// VoiceOver 開啟時發送 announcement，回傳是否已處理。
    @discardableResult
    static func announceIfVoiceOver(_ message: String) -> Bool {
        #if os(iOS)
        guard UIAccessibility.isVoiceOverRunning else { return false }
        UIAccessibility.post(notification: .announcement, argument: message)
        return true
        #elseif os(macOS)
        guard NSWorkspace.shared.isVoiceOverEnabled else { return false }
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [.announcement: message]
        )
        return true
        #endif
    }
}
```

- [ ] **Step 3: 新增 PlatformShareView**

在檔案尾部（`#if os(macOS)` MacKeyResponder 區塊之前）加入：

```swift
struct PlatformShareView: View {
    let url: URL
    var body: some View {
        #if os(iOS)
        PlatformShareSheet(url: url)
        #else
        ShareLink(item: url).padding()
        #endif
    }
}

#if os(iOS)
private struct PlatformShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
#endif
```

- [ ] **Step 4: Build 驗證**
```bash
./ops/ios_build.sh
```
Expected: exit 0

- [ ] **Step 5: Commit**
`ios: add platform adapter view extensions (A1-A7)`

---

## Task 2: Part A — 遷移 call sites (View extensions)

**Files:**
- Modify: `ios/BooksBrowser/UIComponents/AppShellComponents.swift:143-146`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/AddLinkSheet.swift:110-112`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Controls.swift:78-81`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:84-88`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift:157-176`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift:129-133`
- Modify: `ios/BooksBrowser/UIComponents/AppToastCoordinator.swift:46-56`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift:22-28`

- [ ] **Step 1: platformTextInputConfig — 3 處**

`AppShellComponents.swift:143-146` — 替換：
```swift
// before
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .autocorrectionDisabled()
// after
                .platformTextInputConfig()
```

`AddLinkSheet.swift:110-112` — 替換：
```swift
// before
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .autocorrectionDisabled()
// after
                .platformTextInputConfig()
```

`SettingsPresenter+Controls.swift:78-81` — 替換：
```swift
// before
            .autocorrectionDisabled()
            #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
// after
            .platformTextInputConfig()
```

- [ ] **Step 2: platformListButtonStyle — 1 處**

`NotebookListView.swift:84-88` — 替換：
```swift
// before
                            #if os(iOS)
                            .buttonStyle(.pressable)
                            #else
                            .buttonStyle(.plain)
                            #endif
// after
                            .platformListButtonStyle()
```

- [ ] **Step 3: platformContentMaxWidth + platformHideNavigationBar — 1 處**

`TodayReviewPresenter.swift:171-179` — 替換：
```swift
// before
            #if os(iOS)
            .frame(maxWidth: 600)
            .frame(maxWidth: .infinity)
            #else
            .frame(maxWidth: .infinity)
            #endif
            .vocabCanvasBackground()
            #if os(iOS)
            .toolbar(.hidden, for: .navigationBar)
            #endif
// after
            .platformContentMaxWidth()
            .vocabCanvasBackground()
            .platformHideNavigationBar()
```

- [ ] **Step 4: platformRefreshable — 1 處**

`KGVocabPresenter.swift:129-133` — 替換：
```swift
// before
        #if os(iOS)
        .refreshable { [onRefresh] in
            await onRefresh?()
        }
        #endif
// after
        .platformRefreshable { [onRefresh] in
            await onRefresh?()
        }
```

- [ ] **Step 5: PlatformAccessibility — 1 處**

`AppToastCoordinator.swift:46-56` — 替換：
```swift
// before
        #if os(iOS)
        if UIAccessibility.isVoiceOverRunning {
            UIAccessibility.post(notification: .announcement, argument: item.message)
            return
        }
        #elseif os(macOS)
        if NSWorkspace.shared.isVoiceOverEnabled {
            NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested, userInfo: [.announcement: item.message])
            return
        }
        #endif
// after
        PlatformAccessibility.announceIfVoiceOver(item.message)
```

注意：原本 VoiceOver 模式下 `return` 跳過 dismiss timer。改為：
```swift
        guard !PlatformAccessibility.announceIfVoiceOver(item.message) else { return }
```

- [ ] **Step 6: PlatformShareView — 1 處**

`VocabularyListView+Sheets.swift:22-28` — 替換：
```swift
// before
            .toastSheet(item: $coordinator.exportURL) { url in
                #if os(iOS)
                ShareSheet(url: url)
                #elseif os(macOS)
                ShareLink(item: url)
                    .padding()
                #endif
            }
// after
            .toastSheet(item: $coordinator.exportURL) { url in
                PlatformShareView(url: url)
            }
```

同檔刪除底部的 `ShareSheet` struct（已搬入 PlatformCompatibility）：
```swift
// DELETE: lines 65-75
#if os(iOS)
struct ShareSheet: UIViewControllerRepresentable { ... }
#endif
```

- [ ] **Step 7: Build 驗證**
```bash
./ops/ios_build.sh
```
Expected: exit 0

- [ ] **Step 8: Commit**
`ios: migrate call sites to platform adapter extensions`

---

## Task 3: Part A — PlatformStore

**Files:**
- Modify: `ios/BooksBrowser/Platform/PlatformCompatibility.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SubscriptionPaywallSheet.swift:11-17, 131-135`

- [ ] **Step 1: 新增 PlatformStore**

在 `PlatformAccessibility` 之後加入：

```swift
enum PlatformStore {
    @MainActor
    static func manageSubscriptions() async {
        #if os(iOS)
        guard let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene }).first else { return }
        try? await AppStore.showManageSubscriptions(in: scene)
        #elseif os(macOS)
        if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
            NSWorkspace.shared.open(url)
        }
        #endif
    }
}
```

- [ ] **Step 2: 遷移 SubscriptionPaywallSheet**

刪除 `#if os(iOS)` windowScene property（lines 11-17）。

替換 lines 131-135：
```swift
// before
                            #if os(iOS)
                            guard let scene = windowScene else { return }
                            try? await AppStore.showManageSubscriptions(in: scene)
                            #elseif os(macOS)
                            NSWorkspace.shared.open(URL(string: "https://apps.apple.com/account/subscriptions")!)
                            #endif
// after
                            await PlatformStore.manageSubscriptions()
```

- [ ] **Step 3: Build 驗證**
```bash
./ops/ios_build.sh
```
Expected: exit 0

- [ ] **Step 4: Commit**
`ios: add PlatformStore and migrate subscription management`

---

## Task 4: Part B — DetailRouting protocol + implementations

**Files:**
- Create: `ios/BooksBrowser/Platform/DetailRouter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/MacDetailState.swift`

- [ ] **Step 1: 建立 DetailRouter.swift**

```swift
//
//  DetailRouter.swift
//  BooksBrowser
//
//  統一 detail 呈現路由 — iOS sheet vs macOS inspector
//

import SwiftUI

@MainActor
protocol DetailRouting: AnyObject, Observable {
    var selectedEntry: VocabularyEntry? { get set }
    var activeReviewSession: TodayReviewSession? { get set }
    var contextEntries: [VocabularyEntry] { get set }
    var hasDetail: Bool { get }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry])
    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry])
    func dismiss()
}

// MARK: - iOS Implementation

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

// MARK: - Environment Key

private struct DetailRouterKey: EnvironmentKey {
    static let defaultValue: (any DetailRouting)? = nil
}

extension EnvironmentValues {
    var detailRouter: (any DetailRouting)? {
        get { self[DetailRouterKey.self] }
        set { self[DetailRouterKey.self] = newValue }
    }
}
```

注意：spec 原本建議 `AnyDetailRouter` type-erasure wrapper 避免 existential 斷 observation。
但經重新評估：消費端讀 `detailRouter` 後轉型為 concrete class 使用（`if let router = detailRouter as? SheetDetailRouter`），
或更好的方式 — **消費端不直接 observe router 的 property，只呼叫 method**。
observation 需求僅在 `NotebookListView` 的 detail panel 呈現，該處直接持有 concrete instance。
Environment 傳遞的 existential 僅用於 method dispatch，不需要 tracking。
因此 **不需要 type-erasure wrapper**，existential 足夠。

- [ ] **Step 2: MacDetailState conform DetailRouting**

`MacDetailState.swift` — 移除 `#if os(macOS)` / `#endif` 整檔 guard，改為：

```swift
import SwiftUI

#if os(macOS)
@Observable @MainActor
final class MacDetailState: DetailRouting {
    // ... 現有程式碼不動 ...
}
#endif
```

只需加 `: DetailRouting` conformance。現有方法簽名已完全匹配 protocol。

移除底部的 `MacDetailStateKey` + `EnvironmentValues.macDetail`（將由 `\.detailRouter` 取代）。

- [ ] **Step 3: Build 驗證**
```bash
./ops/ios_build.sh
```
Expected: FAIL — 移除 `\.macDetail` 後消費端會壞。這是預期的，下一步修。

- [ ] **Step 4: Commit**
暫不 commit，等消費端遷移完一起。

---

## Task 5: Part B — 遷移 NotebookListView（router 注入點 + detail panel）

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`

- [ ] **Step 1: 替換 state 宣告**

```swift
// before (line 44-47)
    #if os(macOS)
    @State private var macDetail = MacDetailState()
    @State private var isEditingMacDetailEntry = false
    #endif

// after
    #if os(macOS)
    @State private var macDetail = MacDetailState()
    @State private var isEditingMacDetailEntry = false
    #elseif os(iOS)
    @State private var sheetRouter = SheetDetailRouter()
    #endif
```

- [ ] **Step 2: 注入 environment**

```swift
// before (line 216-217)
        #if os(macOS)
        .environment(\.macDetail, macDetail)

// after
        #if os(macOS)
        .environment(\.detailRouter, macDetail)
```

加上 iOS 注入（在 NavigationStack 尾部）：
```swift
        #if os(iOS)
        .environment(\.detailRouter, sheetRouter)
        #endif
```

- [ ] **Step 3: 替換 review routing**

```swift
// before (line 160-177)
            #if os(iOS)
            .platformFullScreenCover(item: $activeReviewSession) { session in
                TodayReviewView(...)
                .toastOverlay()
            }
            #elseif os(macOS)
            .onChange(of: activeReviewSession) { _, session in
                if let session {
                    macDetail.showReview(session, allEntries: allEntries)
                    activeReviewSession = nil
                }
            }
            #endif

// after — 統一用 detailRouter
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

- [ ] **Step 4: iOS detail sheet 呈現**

在 NavigationStack 尾部（iOS 區塊）新增：
```swift
        #if os(iOS)
        .toastSheet(item: $sheetRouter.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: sheetRouter.contextEntries)
                .appSheet(.large)
        }
        .platformFullScreenCover(item: Binding(
            get: { sizeClass == .compact ? sheetRouter.activeReviewSession : nil },
            set: { if $0 == nil { sheetRouter.dismiss() } }
        )) { session in
            TodayReviewView(
                entries: session.entries,
                allEntries: sheetRouter.contextEntries.isEmpty ? allEntries : sheetRouter.contextEntries,
                currentUserID: authManager.userId,
                onClose: { sheetRouter.dismiss() }
            )
            .toastOverlay()
        }
        .toastSheet(item: Binding(
            get: { sizeClass == .regular ? sheetRouter.activeReviewSession : nil },
            set: { if $0 == nil { sheetRouter.dismiss() } }
        )) { session in
            TodayReviewView(
                entries: session.entries,
                allEntries: sheetRouter.contextEntries.isEmpty ? allEntries : sheetRouter.contextEntries,
                currentUserID: authManager.userId,
                onClose: { sheetRouter.dismiss() }
            )
            .appSheet(.large)
        }
        #endif
```

- [ ] **Step 5: macOS detail panel — 改讀 macDetail（不動）**

macOS inspector panel 區塊保持不變（直接讀 `macDetail` concrete instance，observation tracking 正常）。

- [ ] **Step 6: Build 驗證**
```bash
./ops/ios_build.sh
```
Expected: 可能仍有其他消費端錯誤，繼續修。

---

## Task 6: Part B — 遷移 VocabularyListView + Sheets

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift:30-31`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift:29-59`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+State.swift:100-106`

- [ ] **Step 1: VocabularyListView — 替換 macDetail 讀取**

```swift
// before (line 30-31)
    #if os(macOS)
    @Environment(\.macDetail) var macDetail
    #endif

// after
    @Environment(\.detailRouter) var detailRouter
```

- [ ] **Step 2: VocabularyListView+State — 替換 macOS 分支**

```swift
// before (line 100-106)
                #if os(macOS)
                KGVocabView(searchText: $debouncedSearchText, notebookId: notebookId) { entry in
                    coordinator.selectedEntry = entry
                }
                #else
                KGVocabView(searchText: $debouncedSearchText, notebookId: notebookId)
                #endif

// after
                KGVocabView(searchText: $debouncedSearchText, notebookId: notebookId) { entry in
                    detailRouter?.showWordDetail(entry, allEntries: allEntries)
                }
```

注意：`KGVocabView.onEntrySelected` callback 現在兩平台都走，iOS 的 `SheetDetailRouter` 會設 `selectedEntry`，
由 `NotebookListView` 的 `.toastSheet(item: $sheetRouter.selectedEntry)` 呈現。

- [ ] **Step 3: VocabularyListView — 遷移 macOS onChange 路由**

`VocabularyListView.swift:107-120` — 替換：
```swift
// before
        #if os(macOS)
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let macDetail {
                macDetail.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .onChange(of: coordinator.activeReviewSession) { _, session in
            if let session, let macDetail {
                macDetail.showReview(session, allEntries: allEntries)
                coordinator.activeReviewSession = nil
            }
        }
        #endif

// after — 跨平台統一走 detailRouter
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let detailRouter {
                detailRouter.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .onChange(of: coordinator.activeReviewSession) { _, session in
            if let session, let detailRouter {
                detailRouter.showReview(session, allEntries: allEntries)
                coordinator.activeReviewSession = nil
            }
        }
```

- [ ] **Step 4: VocabularyListView+Sheets — 移除 iOS-only detail/review sheets**

```swift
// before (line 29-59) — 移除整段 #if os(iOS) word detail + review sheets
            // macOS: selectedEntry/review 透過 onChange → macInspector 上浮到 NotebookListView 的 inspector
            #if os(iOS)
            .toastSheet(item: $coordinator.selectedEntry) { entry in ... }
            .platformFullScreenCover(...) { ... }
            .toastSheet(...) { ... }
            #endif

// after — 全部刪除（已搬到 NotebookListView 的集中 sheet 呈現）
```

- [ ] **Step 5: Build 驗證**
```bash
./ops/ios_build.sh
```

---

## Task 7: Part B — 遷移 KnowledgeGraphView

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/KnowledgeGraphView.swift`

- [ ] **Step 1: 替換整段**

```swift
// before (line 8-10)
    #if os(macOS)
    @Environment(\.macDetail) private var macDetail
    #endif

// after
    @Environment(\.detailRouter) private var detailRouter
```

```swift
// before (line 31-50)
        #if os(macOS)
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let macDetail {
                macDetail.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .toastSheet(item: Binding(
            get: { macDetail == nil ? coordinator.selectedEntry : nil },
            set: { coordinator.selectedEntry = $0 }
        )) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
        #else
        .toastSheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
        #endif

// after
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, detailRouter != nil {
                detailRouter?.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .toastSheet(item: Binding(
            get: { detailRouter == nil ? coordinator.selectedEntry : nil },
            set: { coordinator.selectedEntry = $0 }
        )) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
```

- [ ] **Step 2: Build 驗證**
```bash
./ops/ios_build.sh
```

---

## Task 8: Part B — 遷移 WordDetailSheet

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`

- [ ] **Step 1: 替換 macDetail 讀取**

```swift
// before (line 7-9)
    #if os(macOS)
    @Environment(\.macDetail) private var macDetail
    #endif

// after
    @Environment(\.detailRouter) private var detailRouter
```

- [ ] **Step 2: 替換 shouldUseLinkedOverlayStack**

```swift
// before (line 108-113)
        #if os(macOS)
        return wrapInNavigation || macDetail == nil
        #else
        return wrapInNavigation
        #endif

// after
        return wrapInNavigation || detailRouter == nil
```

- [ ] **Step 3: 替換 handleLinkTap**

```swift
// before (line 126-131)
        #if os(macOS)
        if !wrapInNavigation, let macDetail {
            macDetail.showWordDetail(target, allEntries: allEntries)
            return
        }
        #endif

// after
        if !wrapInNavigation, let detailRouter {
            detailRouter.showWordDetail(target, allEntries: allEntries)
            return
        }
```

- [ ] **Step 4: Build 驗證**
```bash
./ops/ios_build.sh
```

---

## Task 9: 最終清理 + 全量驗證

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/MacDetailState.swift` — 確認 `\.macDetail` 已無消費端後刪除 environment key

- [ ] **Step 1: 搜尋殘留的 `\.macDetail` 引用**
```bash
grep -r "macDetail" ios/BooksBrowser/ --include="*.swift" -l
```
Expected: 只剩 `MacDetailState.swift` 和 `NotebookListView.swift`（後者直接持有 concrete instance）。

- [ ] **Step 2: 刪除 MacDetailState.swift 中的舊 environment key**

```swift
// DELETE: MacDetailStateKey + EnvironmentValues.macDetail
private struct MacDetailStateKey: EnvironmentKey { ... }
extension EnvironmentValues { var macDetail: ... }
```

- [ ] **Step 3: NotebookListView 中 macOS 區塊的 `.environment(\.macDetail, macDetail)` 已替換為 `.environment(\.detailRouter, macDetail)`**

確認無殘留。

- [ ] **Step 4: 搜尋殘留的 `#if os` 確認數量下降**
```bash
grep -c "#if os(" ios/BooksBrowser/Views/ ios/BooksBrowser/UIComponents/ ios/BooksBrowser/Models/ --include="*.swift" -r
```

- [ ] **Step 5: Full build**
```bash
./ops/ios_build.sh
```
Expected: exit 0

- [ ] **Step 6: Commit**
`ios: consolidate platform adapter layer — DetailRouter + view extensions`

---

## 執行順序摘要

| Task | 內容 | 依賴 |
|------|------|------|
| 1 | PlatformCompatibility extensions | 無 |
| 2 | 遷移 Part A call sites | Task 1 |
| 3 | PlatformStore | Task 1 |
| 4 | DetailRouting protocol + impls | 無 |
| 5 | 遷移 NotebookListView | Task 4 |
| 6 | 遷移 VocabularyListView + Sheets | Task 5 |
| 7 | 遷移 KnowledgeGraphView | Task 4 |
| 8 | 遷移 WordDetailSheet | Task 4 |
| 9 | 清理 + 驗證 | Task 5-8 |

**可平行**：Task 1+4（Part A extensions 和 Part B protocol 互不依賴）
**可平行**：Task 7+8（兩個獨立 View 遷移）
