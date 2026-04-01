# macOS Multiplatform Support Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 在現有 iOS target 加入 macOS 15.0+ destination，排除 Readium/Reader，其餘功能完整可用。
**Architecture:** 平台橋接層（typealias + View extension）+ `#if os(iOS)` 條件編譯隔離不相容程式碼。
**Tech Stack:** SwiftUI multiplatform, CoreText, conditional compilation

---

## Task 1: Platform Foundation（前置，其他 task 依賴此 task）

**Files:**
- Create: `ios/BooksBrowser/Platform/PlatformCompatibility.swift`
- Create: `ios/BooksBrowser/Platform/PlatformRepresentable.swift`

- [ ] **Step 1: 建立 `PlatformRepresentable.swift`**

```swift
//  PlatformRepresentable.swift
//  BooksBrowser
//  跨平台型別橋接

import SwiftUI

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

- [ ] **Step 2: 建立 `PlatformCompatibility.swift`**

```swift
//  PlatformCompatibility.swift
//  BooksBrowser
//  iOS-only SwiftUI modifier 的跨平台 wrapper

import SwiftUI

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

    @ViewBuilder
    func platformFullScreenCover<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        #if os(iOS)
        self.fullScreenCover(item: item, onDismiss: onDismiss, content: content)
        #else
        self.sheet(item: item, onDismiss: onDismiss, content: content)
        #endif
    }

    func dismissKeyboard() {
        #if os(iOS)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
        #endif
    }

    @ViewBuilder
    func platformImage(data: Data) -> some View {
        #if os(iOS)
        if let img = UIImage(data: data) {
            Image(uiImage: img)
        }
        #elseif os(macOS)
        if let img = NSImage(data: data) {
            Image(nsImage: img)
        }
        #endif
    }
}
```

- [ ] **Step 3: 將兩檔加入 Xcode project**

在 pbxproj 中建立 `Platform` group，將兩檔加入 BooksBrowser target。

- [ ] **Step 4: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 2: Project Configuration (pbxproj)

**Files:**
- Modify: `ios/BooksBrowser.xcodeproj/project.pbxproj`

- [ ] **Step 1: 加入 macOS deployment target**

在所有 build configuration（Debug + Release）加入：
```
MACOSX_DEPLOYMENT_TARGET = 15.0;
```

- [ ] **Step 2: 擴充 SUPPORTED_PLATFORMS**

```
SUPPORTED_PLATFORMS = "iphoneos iphonesimulator macosx";
```

同時設定：
```
SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD = NO;
DERIVE_MACCATALYST_PRODUCT_BUNDLE_IDENTIFIER = NO;
```

- [ ] **Step 3: Readium SPM products 加 platformFilter**

找到所有 Readium package product dependency（ReadiumShared, ReadiumStreamer, ReadiumNavigator, ReadiumAdapterGCDWebServer），加入：
```
platformFilter = ios;
```

這確保 Readium 只在 iOS build 時 link。

- [ ] **Step 4: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 3: Reader & Readium 整體排除

**Files:**
- Modify: `ios/BooksBrowser/Views/Reader/*.swift` (34 files)
- Modify: `ios/BooksBrowser/Services/ReadiumService.swift`
- Modify: `ios/BooksBrowser/Services/ReadiumServing.swift`
- Modify: `ios/BooksBrowser/Services/ReaderPublicationLoader.swift`
- Modify: `ios/BooksBrowser/Services/BookshelfImporting.swift`
- Modify: `ios/BooksBrowser/Models/ReaderSettings.swift`

- [ ] **Step 1: Reader 目錄 34 檔全部加 `#if os(iOS)` guard**

每個檔案：在 `import` 之前加 `#if os(iOS)`，檔案最後一行加 `#endif`。

34 files:
```
Views/Reader/ReadiumNavigatorCoordinator+Messages.swift
Views/Reader/ReadiumNavigatorSupport.swift
Views/Reader/ReaderDOMExecutor.swift
Views/Reader/ReadiumNavigatorCoordinator+Commands.swift
Views/Reader/ReaderView+Handlers.swift
Views/Reader/ReaderTranslationHandler.swift
Views/Reader/ReaderViewState.swift
Views/Reader/ReaderNotebookPicker.swift
Views/Reader/ReaderSelectionTile.swift
Views/Reader/ReaderStepControlButton.swift
Views/Reader/QuotaBar.swift
Views/Reader/ReaderChromeState.swift
Views/Reader/ReaderContentStyle.swift
Views/Reader/ReaderSettingsPresenter+Vocab.swift
Views/Reader/ReaderSettingsPresenter.swift
Views/Reader/ReaderViewPresenter+Headers.swift
Views/Reader/ReaderViewPresenter+Preview.swift
Views/Reader/ReadiumNavigatorCoordinator+Planner.swift
Views/Reader/TranslationPanelPresenter+State.swift
Views/Reader/TranslationVocabPresenter.swift
Views/Reader/ReaderTranslationHandler+Flows.swift
Views/Reader/ReaderView+Panels.swift
Views/Reader/ReaderViewPresenter+Overlays.swift
Views/Reader/ReaderViewPresenter.swift
Views/Reader/ReaderTranslationHandler+Persistence.swift
Views/Reader/ReaderView.swift
Views/Reader/ReaderVocabularyContext.swift
Views/Reader/ReaderSettingsPanel.swift
Views/Reader/TOCView.swift
Views/Reader/ReadiumNavigatorCoordinator+Highlighting.swift
Views/Reader/ReadiumNavigatorView.swift
Views/Reader/TranslationPanel.swift
Views/Reader/PDFReaderView.swift
Views/Reader/ReadiumNavigatorJS.swift
```

- [ ] **Step 2: Readium service 檔案加 guard**

同樣模式（整檔 `#if os(iOS)` ... `#endif`）：
- `Services/ReadiumService.swift`
- `Services/ReadiumServing.swift`
- `Services/ReaderPublicationLoader.swift`
- `Models/ReaderSettings.swift`

- [ ] **Step 3: BookshelfImporting.swift — 整個 class guard**

`BookshelfImportService` 和 `BookshelfImporting` protocol 整體用 `#if os(iOS)` 包裹。`EPUBConverter` 不動（純 Foundation）。

- [ ] **Step 4: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 4: AppFonts 平台適配

**Files:**
- Modify: `ios/BooksBrowser/Models/AppFonts.swift`

- [ ] **Step 1: 替換 import 和 cascadeListKey**

```swift
// Before:
import UIKit

// After:
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
```

```swift
// Before:
private static let cascadeListKey = UIFontDescriptor.AttributeName(
    rawValue: "NSCTFontCascadeListAttribute"
)

// After:
private static let cascadeListKey = PlatformFontDescriptor.AttributeName(
    rawValue: "NSCTFontCascadeListAttribute"
)
```

- [ ] **Step 2: font builders 替換 UIFontDescriptor/UIFont → PlatformFontDescriptor/PlatformFont**

`serif()`, `sans()`, `mono()` 三個函式：
- `UIFontDescriptor(fontAttributes:)` → `PlatformFontDescriptor(fontAttributes:)`
- `UIFont(descriptor:size:)` → `PlatformFont(descriptor:size:)` 
- `UIFont.monospacedSystemFont(...)` → `PlatformFont.monospacedSystemFont(...)`

- [ ] **Step 3: UIKit-only 函式加 `#if os(iOS)`**

```swift
#if os(iOS)
static func uiSerif(size: CGFloat, bold: Bool = false) -> UIFont { ... }
static func uiSans(size: CGFloat, bold: Bool = false) -> UIFont { ... }
static func makeNavBarAppearances() -> (...) { ... }
static func configureGlobalAppearance() { ... }
#endif
```

- [ ] **Step 4: ensureSerifCJKAvailable 替換 UIFontDescriptor**

```swift
// Before:
let desc = UIFontDescriptor(fontAttributes: [.name: name])
// After:
let desc = PlatformFontDescriptor(fontAttributes: [.name: name])
```

其餘 CoreText API（`CTFontDescriptor`, `CTFontDescriptorMatchFontDescriptorsWithProgressHandler`）不變。

- [ ] **Step 5: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 5: Auth 平台守衛

**Files:**
- Modify: `ios/BooksBrowser/Services/AuthManager+Apple.swift`
- Modify: `ios/BooksBrowser/Services/AuthManager+Google.swift`

- [ ] **Step 1: AuthManager+Apple.swift**

`import UIKit` → 條件 import：
```swift
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
```

`presentationAnchor(for:)` 方法用 `#if os` 分支：
```swift
func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
    #if os(iOS)
    // 現有 UIApplication.shared.connectedScenes 邏輯
    ...
    #elseif os(macOS)
    return NSApplication.shared.keyWindow ?? NSWindow()
    #endif
}
```

- [ ] **Step 2: AuthManager+Google.swift**

`import UIKit` → 條件 import。

window/VC lookup（line 9-15）用 `#if os(iOS)` 分支：
```swift
#if os(iOS)
let window = UIApplication.shared.connectedScenes
    .flatMap { ($0 as? UIWindowScene)?.windows ?? [] }
    .first { $0.isKeyWindow }
guard let presentingViewController = window?.rootViewController?.topMostPresentedViewController else { ... }
try await GIDSignIn.sharedInstance.signIn(withPresenting: presentingViewController)
#elseif os(macOS)
guard let window = NSApplication.shared.keyWindow else { ... }
try await GIDSignIn.sharedInstance.signIn(withPresenting: window)
#endif
```

`UIViewController` extension（line 62-75）整段 `#if os(iOS)` guard。

- [ ] **Step 3: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 6: 散落 UIKit API 守衛

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/VocabularyListPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SubscriptionPaywallSheet.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift`

- [ ] **Step 1: KnowledgeGraphPresentation.swift**

`import UIKit` → 條件 import（或移除，改用 PlatformColor）。
Line 155: `UIColor(color).getRed(...)` → `PlatformColor(color).getRed(...)`

- [ ] **Step 2: BookshelfView.swift**

`UIImage(data:)` → 使用 `platformImage(data:)` View helper（Task 1 建立），或用 `#if os(iOS)` / `#else` 分支處理 `Image(uiImage:)` vs `Image(nsImage:)`。確認 `import UIKit` 改為條件 import。

- [ ] **Step 3: VocabularyListPresenter.swift**

keyboard dismissal 改用 `dismissKeyboard()` helper（Task 1 建立）。

- [ ] **Step 4: SubscriptionPaywallSheet.swift**

`UIWindowScene` lookup 用 `#if os(iOS)` guard。macOS 不需要 `windowScene`（StoreKit 2 的 `manageSubscriptions` 在 macOS 上用環境 API 或直接開 App Store）：
```swift
#if os(iOS)
private var windowScene: UIWindowScene? {
    UIApplication.shared.connectedScenes
        .first { $0.activationState == .foregroundActive } as? UIWindowScene
}
#endif
```
呼叫處同樣 `#if os(iOS)` guard。

- [ ] **Step 5: VocabularyListView+Sheets.swift**

`ShareSheet`（UIActivityViewController wrapper）整個 struct 加 `#if os(iOS)` guard。
呼叫處改為：
```swift
#if os(iOS)
ShareSheet(items: [...])
#else
// macOS: 用 ShareLink 或 NSSharingServicePicker
#endif
```

`.fullScreenCover` → `.platformFullScreenCover`

- [ ] **Step 6: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 7: 跨平台 WebView Representables

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/GraphThumbnailWebView.swift`

- [ ] **Step 1: GraphWebView.swift — 雙平台實作**

```swift
#if os(iOS)
import UIKit

struct GraphWebView: UIViewRepresentable {
    // 現有 iOS 實作（makeUIView, updateUIView, dismantleUIView）
    // 保留 scrollView 存取
}
#elseif os(macOS)
import AppKit

struct GraphWebView: NSViewRepresentable {
    // 相同屬性和 Coordinator
    
    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero, configuration: ...)
        // 不存取 scrollView（macOS WKWebView 無此屬性）
        return webView
    }
    
    func updateNSView(_ webView: WKWebView, context: Context) {
        // 同 updateUIView 邏輯
    }
    
    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        // 同 dismantleUIView 邏輯
    }
}
#endif
```

保持 Coordinator 共用（用 `#if os` 處理差異點）。

- [ ] **Step 2: GraphThumbnailWebView.swift — 同樣模式**

結構較簡單，同樣拆 `UIViewRepresentable` / `NSViewRepresentable`。

- [ ] **Step 3: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 8: App 結構 & 進入點

**Files:**
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift`
- Modify: `ios/BooksBrowser/ContentView.swift`
- Modify: `ios/BooksBrowser/Services/AppEnvironment.swift`

- [ ] **Step 1: AppEnvironment.swift — guard Readium + Bookshelf env keys**

```swift
#if os(iOS)
private struct ReadiumServiceEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any ReadiumServing = MainActor.assumeIsolated {
        ReadiumService.shared
    }
}

private struct BookshelfImportServiceEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue = MainActor.assumeIsolated {
        BookshelfImportService(readiumService: ReadiumService.shared)
    }
}

private struct ReaderSettingsKey: EnvironmentKey {
    static let defaultValue = ReaderSettings.shared
}
#endif
```

對應的 `EnvironmentValues` extension 也要 guard：
```swift
#if os(iOS)
var readiumService: any ReadiumServing { ... }
var bookshelfImportService: BookshelfImportService { ... }
var readerSettings: ReaderSettings { ... }
#endif
```

- [ ] **Step 2: BooksBrowserApp.swift — 條件化 iOS-only 程式碼**

```swift
// readiumService & bookshelfImportService init
#if os(iOS)
let readiumService: any ReadiumServing = ReadiumService.shared
let bookshelfImportService: BookshelfImportService
#endif

// init 中：
#if os(iOS)
bookshelfImportService = BookshelfImportService(readiumService: readiumService)
AppFonts.ensureSerifCJKAvailable()
AppFonts.configureGlobalAppearance()
#endif

// environment injection：
#if os(iOS)
.environment(\.readiumService, readiumService)
.environment(\.bookshelfImportService, bookshelfImportService)
.environment(\.readerSettings, .shared)
#endif

// fontObserver static property（calls configureGlobalAppearance）：
#if os(iOS)
static let fontObserver = ... // 現有邏輯
#endif

// fullScreenCover → platformFullScreenCover
.platformFullScreenCover(isPresented: $showWelcome) { WelcomeView(...) }
```

- [ ] **Step 3: ContentView.swift — macOS 隱藏書庫 tab**

```swift
TabView {
    #if os(iOS)
    BookshelfView()
        .tabItem { Label("書庫", systemImage: "books.vertical") }
    #endif
    NotebookListView()
        .tabItem { Label("單字本", systemImage: "character.book.closed") }
    OverviewTab()
        .tabItem { Label("總覽", systemImage: "chart.bar") }
}
```

- [ ] **Step 4: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 9: SwiftUI Modifier 批量遷移

**Files (18 non-Reader files, 21 occurrences):**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift:58` — `.large` → `.largeNavigationBarTitle()`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift:54` — `.large` → `.largeNavigationBarTitle()`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter.swift:66,105` — `.inline` → `.inlineNavigationBarTitle()`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsReviewSection.swift:20` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/ReviewCalendarPresenter.swift:76` — `.inline`
- Modify: `ios/BooksBrowser/Views/Settings/SubscriptionPaywallSheet.swift:74` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookEditSheet.swift:67` — `.inline`
- Modify: `ios/BooksBrowser/Views/Startup/AppStartupRecoveryView.swift:81` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordEditSheet.swift:42` — `.inline`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsAccountDetailView.swift:44` — `.inline`
- Modify: `ios/BooksBrowser/Views/Settings/TranslationLanguageSettingsView.swift:57` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/ArchivedVocabSheet.swift:66` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift:67` — `.inline`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Sheet.swift:61` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookPickerSheet.swift:70` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:115` — `.large`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookFilterChip.swift:105` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/AddLinkSheet.swift:90` — `.inline`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/OverviewTab.swift:28,49` — `.large`

- [ ] **Step 1: 批量替換 `.navigationBarTitleDisplayMode(.inline)` → `.inlineNavigationBarTitle()`**

18 occurrences across 15 files。

- [ ] **Step 2: 批量替換 `.navigationBarTitleDisplayMode(.large)` → `.largeNavigationBarTitle()`**

5 occurrences across 4 files（VocabularyListView, BookshelfView, NotebookListView, OverviewTab）。

- [ ] **Step 3: `.fullScreenCover` 替換**

2 non-Reader files：
- `VocabularyListView+Sheets.swift:28` → `.platformFullScreenCover`
- `NotebookListView.swift:151` → `.platformFullScreenCover`

（BooksBrowserApp.swift 已在 Task 8 處理）

- [ ] **Step 4: iOS build 確認不破壞**
Run: `./ops/ios_build.sh`
Expected: Exit 0

---

## Task 10: macOS Build & Fix

**依賴：** Task 1-9 全部完成

- [ ] **Step 1: macOS build**
Run: `xcodebuild -project ios/BooksBrowser.xcodeproj -scheme BooksBrowser -destination 'platform=macOS' build 2>&1 | tail -50`

- [ ] **Step 2: 修復所有編譯錯誤**

預期可能的殘留問題：
- `import UIKit` 散落在其他檔案
- 遺漏的 iOS-only API
- SPM resolution 問題

逐一修復直到 macOS build 成功。

- [ ] **Step 3: iOS build 最終確認**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**
