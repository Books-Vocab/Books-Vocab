<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksBrowser/Platform/
  - ios/BooksBrowser/Views/Reader/ReaderView.swift
  - ios/BooksBrowser/ContentView.swift
verified_against: frozen
-->
# Mac Catalyst Window Chrome Implementation Plan(Workstream A)

> **執行方式:** 使用 `phased-workflow` skill,所有 review agent 皆 `opus` + `run_in_background: true`。每完成一個 Task 立即 dispatch reviewer,PASS 才下一個。**禁批次**(鐵律 4)。

**Goal:** 依 [umbrella spec](../specs/2026-05-31-mac-catalyst-native-feel-design.md) Workstream A,讓 Mac Catalyst 視窗有像樣的最小尺寸 + 首發尺寸,Reader 進入時隱藏 title bar 沉浸、退出復原。iPhone/iPad 零回歸。

**Architecture:**
- 新增 `ios/BooksBrowser/Platform/MacWindowChrome.swift` — 集中所有 Catalyst window scene 操作的單一來源。整檔以 `#if targetEnvironment(macCatalyst)` 分流,非 Catalyst 為 no-op modifier。
- 取 `UIWindowScene` 沿用既有先例 `PlatformCompatibility.swift:115-122`(`connectedScenes.compactMap { $0 as? UIWindowScene }.first`),**不加 SceneDelegate、不動 Info.plist scene manifest**。
- 尺寸主力走 UIKit `sizeRestrictions.minimumSize` + `requestGeometryUpdate(.Mac(...))`;`.defaultSize`/`.windowResizability` 在 Catalyst 靜默無效,不採用。
- Reader 沉浸 title bar **scoped 可逆**:`ReaderView` `.onAppear` 隱藏、`.onDisappear` 復原(Reader 與其他 tab 共用同一 window,不可全域隱藏)。

**Tech Stack:** SwiftUI / UIKit(`UIWindowScene`/`UITitlebar`)/ XCTest。InjectionNext 熱載僅驗 SwiftUI 層,scene 副作用靠 `ops/ios_build.sh` + Mac manual 實測。

**驗證策略(誠實標註):** scene 副作用(尺寸、titlebar)**無法單元測**,以 `./ops/ios_build.sh` 綠 + Mac 實機 manual 為準。可單元測的僅尺寸常數 invariant(min ≤ default、皆 > 0,防未來誤改),以 XCTest 守住。`ios_test.sh` 不主動跑(鐵律/CLAUDE.md),僅使用者要求時跑。

**Doc Sync(commit 強制):** Task 3 收尾更新 `docs/sop/ui-design.md:50-54` 過時 macOS 段 + `docs/reference/tech_index.md`(新 Platform 檔)+ `docs/reference/product_surface.md`(Mac 視窗行為)。

---

## Task 1: `MacWindowChrome` — 視窗尺寸基礎設施

**Files:**
- Create: `ios/BooksBrowser/Platform/MacWindowChrome.swift`
- Create: `ios/BooksBrowserTests/MacWindowChromeTests.swift`(平面結構 — `BooksBrowserTests/` 無子目錄;確認加入 test target membership)
- Modify: `ios/BooksBrowser/ContentView.swift`(掛 `.macWindowChrome()`)

- [ ] **Step 1: 寫 failing test — `MacWindowChromeTests.swift`**
```swift
import XCTest
@testable import BooksBrowser

final class MacWindowChromeTests: XCTestCase {
    /// 尺寸 invariant:最小尺寸不得大於首發尺寸,且皆為正。
    /// 守住未來誤改常數導致「首發即小於最小」的非法狀態。
    func testDefaultSizeNotSmallerThanMinimum() {
        XCTAssertGreaterThan(MacWindowChrome.minimumSize.width, 0)
        XCTAssertGreaterThan(MacWindowChrome.minimumSize.height, 0)
        XCTAssertGreaterThanOrEqual(MacWindowChrome.defaultSize.width, MacWindowChrome.minimumSize.width)
        XCTAssertGreaterThanOrEqual(MacWindowChrome.defaultSize.height, MacWindowChrome.minimumSize.height)
    }

    /// 最小尺寸需足以容納 regular split(LayoutMode.contentMaxWidth 720 + sidebar)。
    /// 防止把視窗縮到 compact 致 Workstream D 的 split 崩成單欄。
    func testMinimumWidthAccommodatesRegularLayout() {
        XCTAssertGreaterThanOrEqual(MacWindowChrome.minimumSize.width, 720)
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_build.sh`(編譯失敗即紅 — `MacWindowChrome` 未定義)
Expected: FAIL — cannot find 'MacWindowChrome' in scope

- [ ] **Step 3: 最小實作 — `MacWindowChrome.swift`**
```swift
//
//  MacWindowChrome.swift
//  Books & Vocab
//
//  Mac Catalyst 視窗 chrome 單一來源 — 尺寸 + title bar。
//  非 Catalyst 平台全為 no-op(modifier 直接回傳 self)。
//

import SwiftUI

enum MacWindowChrome {
    /// 最小視窗尺寸 — 須容納 regular split(sidebar + 720 內容)。
    static let minimumSize = CGSize(width: 900, height: 640)
    /// 首發視窗尺寸 — 僅冷啟動套用一次,之後尊重使用者調整。
    static let defaultSize = CGSize(width: 1100, height: 760)

    #if targetEnvironment(macCatalyst)
    /// 已套用首發 geometry 的旗標 — requestGeometryUpdate 只在冷啟動一次,
    /// 否則每次 onAppear 都會把使用者調過的視窗重設回 defaultSize。
    private static var didApplyInitialGeometry = false

    @MainActor
    private static var currentWindowScene: UIWindowScene? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first
    }

    @MainActor
    static func applyDefaults() {
        guard let scene = currentWindowScene else { return }
        // 最小尺寸每次套用安全(冪等)。
        scene.sizeRestrictions?.minimumSize = minimumSize
        // 首發尺寸只一次。
        guard !didApplyInitialGeometry else { return }
        didApplyInitialGeometry = true
        // origin 置中 best-effort — Mac systemFrame 是 AppKit 全域座標,系統常自行
        // 置中/忽略 origin;算置中值避免落在螢幕角落,實機若仍偏移再校。
        let screen = scene.screen.bounds.size
        let origin = CGPoint(
            x: max(0, (screen.width - defaultSize.width) / 2),
            y: max(0, (screen.height - defaultSize.height) / 2)
        )
        let geometry = UIWindowScene.GeometryPreferences.Mac(
            systemFrame: CGRect(origin: origin, size: defaultSize)
        )
        scene.requestGeometryUpdate(geometry)
    }
    #endif
}

extension View {
    /// 套用 Mac 視窗預設尺寸 + 最小尺寸。非 Catalyst 為 no-op。
    @ViewBuilder
    func macWindowChrome() -> some View {
        #if targetEnvironment(macCatalyst)
        self.onAppear { MacWindowChrome.applyDefaults() }
        #else
        self
        #endif
    }
}
```

- [ ] **Step 4: 掛載 — `ContentView.swift`**
在 `ContentView` body 最外層 `VStack` 末端加 `.macWindowChrome()`(緊接 `.enableInjection()` 之前)。

- [ ] **Step 5: 跑 build + test 確認綠**
Run: `./ops/ios_build.sh`
Expected: 編譯通過;`MacWindowChromeTests` 綠(若使用者要求跑 test)。

- [ ] **Step 6: Commit**
`ios: add MacWindowChrome — Catalyst window min/default size (Workstream A)`

---

## Task 2: Reader 沉浸 title bar(scoped 可逆)

**Files:**
- Modify: `ios/BooksBrowser/Platform/MacWindowChrome.swift`(加 `setTitlebarHidden`)
- Modify: `ios/BooksBrowser/Views/Reader/ReaderView.swift`(body 掛 `.macReaderImmersion()`)

- [ ] **Step 1: 擴充 `MacWindowChrome` — title bar 切換**
在 `#if targetEnvironment(macCatalyst)` 區塊內加:
```swift
    /// Reader 沉浸:隱藏/復原 title bar。Reader 與其他 tab 共用同一 window,
    /// 故只能 per-presentation scoped 切換,不可在 App 啟動時設死。
    @MainActor
    static func setTitlebarHidden(_ hidden: Bool) {
        guard let titlebar = currentWindowScene?.titlebar else { return }
        titlebar.titleVisibility = hidden ? .hidden : .visible
        // 不碰 titlebar.toolbar — KG 從不設 mac toolbar;若 Workstream C 未來
        // 掛 toolbar,此處清空會在 Reader 進出時誤傷,故不動。
    }
```
並在 `extension View` 加:
```swift
    /// Reader 沉浸:進入隱藏 title bar、離開復原。非 Catalyst 為 no-op。
    @ViewBuilder
    func macReaderImmersion() -> some View {
        #if targetEnvironment(macCatalyst)
        self
            .onAppear { MacWindowChrome.setTitlebarHidden(true) }
            .onDisappear { MacWindowChrome.setTitlebarHidden(false) }
        #else
        self
        #endif
    }
```

- [ ] **Step 2: 掛載 — `ReaderView.swift`**
在 `body` 既有 `.toolbar(.hidden, for: .navigationBar)`(`:93`)之後加 `.macReaderImmersion()`。與既有 `ReaderChromeState`(`:49`)無衝突 — chromeState 管 in-content header/overlay,此 modifier 只管 window-level title bar。

- [ ] **Step 3: 跑 build 確認綠**
Run: `./ops/ios_build.sh`
Expected: 編譯通過。

- [ ] **Step 4: Manual 驗證點(寫入 commit message / 交付說明,非自動)**
Mac 實機:(a) 進 Reader title bar 消失、退出書庫頁 title bar 回來;(b) 連續進出 Reader 多次 title bar 狀態正確;(c) Reader 內開 TOC sheet / 設定 panel 後 title bar 不誤現。

- [ ] **Step 5: Commit**
`ios: Reader immersive title bar on Catalyst (scoped, reversible) (Workstream A)`

---

## Task 3: Doc Sync

**Files:**
- Modify: `docs/sop/ui-design.md`(:50-54 過時 macOS 段)
- Modify: `docs/reference/tech_index.md`(新 Platform 檔 `MacWindowChrome`)
- Modify: `docs/reference/product_surface.md`(Mac 視窗行為 bullet)

- [ ] **Step 1: 更新 `ui-design.md:50-54`**
把「Reader 以 `#if os(iOS)` 整檔隔離,macOS 暫不啟用」改為 Catalyst window chrome 規範:`.defaultSize`/`.windowResizability` 在 Catalyst 無效故走 UIKit `sizeRestrictions`/`requestGeometryUpdate`;取 scene 用 `connectedScenes` 先例;Reader 沉浸 title bar scoped 可逆;尺寸常數集中於 `MacWindowChrome`。

- [ ] **Step 2: 更新 `tech_index.md`**
Platform/ 區塊追加 `MacWindowChrome.swift`(Catalyst 視窗尺寸 + title bar 單一來源)。

- [ ] **Step 3: 更新 `product_surface.md`**
Mac Catalyst bullet 追加「原生視窗尺寸(最小/首發)+ Reader 沉浸閱讀(隱藏 title bar)」。

- [ ] **Step 4: 跑 `ops/docs_lint.sh` 確認 frontmatter / verified_against**
Run: `./ops/docs_lint.sh`
Expected: PASS。

- [ ] **Step 5: Commit**
`docs: sync Catalyst window chrome (ui-design / tech_index / product_surface)`

---

## 完成準則

- `./ops/ios_build.sh` 綠;`MacWindowChromeTests` 綠。
- 三個 commit(Task1 / Task2 / Task3)各經 reviewer PASS。
- iPhone/iPad 路徑零改動(全部走 `#if targetEnvironment(macCatalyst)`,非 Catalyst 為 no-op)。
- Mac manual 驗證點交付說明列出(首發尺寸 1100×760、視窗開啟位置置中而非靠角落、縮放下限 900×640、Reader title bar 進出),待使用者實機確認。
