# macOS Multiplatform Support — Design Spec

## Problem

iOS app 是純 SwiftUI + SwiftData，天然具備跨平台潛力，但目前零 macOS 支援。使用者想在 Mac 上使用單字本、知識圖譜、同步等核心功能。

## Goals

1. 在現有 target 加入 macOS 15.0+ destination，共用 99% 程式碼
2. Reader（Readium）在 macOS 上完整排除，不影響 iOS
3. 書庫 tab 在 macOS 隱藏
4. 其餘功能（單字本、圖譜、總覽、設定、Auth、同步）macOS 可用

## Non-Goals

- 不做 macOS 專屬 UI 優化（sidebar navigation、menu bar、keyboard shortcuts）
- 不重構 NavigationStack → NavigationSplitView
- 不碰 Reader 內部程式碼
- 不做 macOS-only 功能

---

## Design

### A. Platform Compatibility Layer

#### A1. `PlatformCompatibility.swift` — 集中式平台橋接

解決 20+ 處 `.navigationBarTitleDisplayMode` 和 3 處 `.fullScreenCover` 的散彈問題：

```swift
import SwiftUI

// MARK: - View Modifiers

extension View {
    @ViewBuilder
    func inlineNavigationBarTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }

    @ViewBuilder
    func largeNavigationBarTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.large)
        #else
        self
        #endif
    }

    @ViewBuilder
    func platformFullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        #if os(iOS)
        self.fullScreenCover(isPresented: isPresented, onDismiss: onDismiss, content: content)
        #else
        self.sheet(isPresented: isPresented, onDismiss: onDismiss, content: content)
        #endif
    }
}

// MARK: - Keyboard Dismissal

extension View {
    func dismissKeyboard() {
        #if os(iOS)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
        #endif
    }
}
```

#### A2. `PlatformRepresentable.swift` — 跨平台型別橋接

```swift
#if os(iOS)
import UIKit
typealias PlatformView = UIView
typealias PlatformColor = UIColor
typealias PlatformImage = UIImage
typealias PlatformFont = UIFont
typealias PlatformFontDescriptor = UIFontDescriptor
#elseif os(macOS)
import AppKit
typealias PlatformView = NSView
typealias PlatformColor = NSColor
typealias PlatformImage = NSImage
typealias PlatformFont = NSFont
typealias PlatformFontDescriptor = NSFontDescriptor
#endif
```

GraphWebView / GraphThumbnailWebView 改為雙 `#if os` 實作，macOS 用 `NSViewRepresentable`，去掉 `scrollView` 存取。`import UIKit` 改為條件 import。

---

### B. Readium 整體排除

**策略：** `#if os(iOS)` 包整檔內容 + SPM platform filter

受影響檔案：
1. `Services/ReadiumService.swift` — 整檔 guard
2. `Services/ReadiumServing.swift` — 整檔 guard
3. `Services/ReaderPublicationLoader.swift` — 整檔 guard
4. `Services/BookshelfImporting.swift` — 整個 `BookshelfImportService` class guard（init 依賴 ReadiumServing，`importEPUB`/`importPDF` 用 `.jpegData` 等 UIImage API）
5. `Services/AppEnvironment.swift` — `ReadiumServiceEnvironmentKey` + `BookshelfImportServiceEnvironmentKey` 均需 guard
6. `Models/ReaderSettings.swift` — 整檔 guard
7. `Views/Reader/*` (全部 34 files) — 整檔 guard
8. `BooksBrowserApp.swift` — readiumService init、bookshelfImportService init、environment injection、`AppFonts.ensureSerifCJKAvailable()` 呼叫、`configureGlobalAppearance()` 呼叫、`.fullScreenCover` → `platformFullScreenCover`
9. `Services/EPUBConverter.swift` — 純 Foundation + zlib，不需 guard，macOS 可用

macOS 上 `ReadiumServing` 協定不存在，`BookshelfImportService` 也不存在，兩者的 environment key 都要條件化。

---

### C. UIKit Platform Guards

| 檔案 | 改法 |
|------|------|
| `AppFonts.swift` | font builders (`serif`/`sans`/`mono`) 改用 `PlatformFontDescriptor`/`PlatformFont` typealias；`uiSerif`/`uiSans`/`makeNavBarAppearances`/`configureGlobalAppearance` 全部 `#if os(iOS)`；`ensureSerifCJKAvailable` 改用 `PlatformFontDescriptor` |
| `AuthManager+Apple.swift` | `presentationAnchor` 用 `#if os(iOS)` 返回 UIWindow，`#else` 返回 NSWindow |
| `AuthManager+Google.swift` | window lookup 和 VC extension 用 `#if os(iOS)`；macOS 用 `GIDSignIn` 的 AppKit API |
| `KnowledgeGraphPresentation.swift` | `UIColor` → `PlatformColor` |
| `BookshelfView.swift` | `UIImage(data:)` → `PlatformImage(data:)` |
| `VocabularyListPresenter.swift` | keyboard dismissal → 用 A1 的 `dismissKeyboard()` |
| `SubscriptionPaywallSheet.swift` | `UIWindowScene` lookup → `#if os(iOS)` guard |
| `VocabularyListView+Sheets.swift` | `ShareSheet`(UIActivityViewController) → macOS 用 `ShareLink`；`fullScreenCover` → `platformFullScreenCover` |

---

### D. App Structure

**ContentView.swift：**
```swift
TabView {
    #if os(iOS)
    BookshelfView().tabItem { Label("書庫", systemImage: "books.vertical") }
    #endif
    NotebookListView().tabItem { Label("單字本", systemImage: "character.book.closed") }
    OverviewTab().tabItem { Label("總覽", systemImage: "chart.bar") }
}
```

**BooksBrowserApp.swift：**
- readiumService / bookshelfImportService init → `#if os(iOS)`
- `.environment(\.readiumService, ...)` / `.environment(\.bookshelfImportService, ...)` → `#if os(iOS)`
- `.fullScreenCover` → `platformFullScreenCover`

---

### E. Project Configuration (pbxproj)

1. 加 `MACOSX_DEPLOYMENT_TARGET = 15.0`
2. `SUPPORTED_PLATFORMS` 加 `macosx`
3. Readium SPM products 加 `platformFilter = ios`（只在 iOS link）
4. `DERIVE_MACCATALYST_PRODUCT_BUNDLE_IDENTIFIER = NO`（不走 Catalyst）

---

### 不需修改的 API（確認安全）

- `.sensoryFeedback` — macOS 14+ 可用，haptics 在 Mac 上靜默忽略，不影響編譯
- `.presentationDetents` / `.presentationDragIndicator` / `.presentationContentInteraction` — macOS 13+ 可用
- `EPUBConverter.swift` — 純 Foundation + zlib，跨平台無問題

## Risk

| 風險 | 緩解 |
|------|------|
| Readium SPM 拉 macOS 不支援的 dependency | platformFilter 確保只 iOS resolve |
| CloudKit / SwiftData 行為差異 | 共用同一 container，Apple 官方支援 |
| StoreKit 2 subscription macOS 行為 | 需手動測試，但 API 一致 |
| Google Sign-In macOS 展示方式不同 | 用 `#if os` 分支，官方有 macOS 支援 |
