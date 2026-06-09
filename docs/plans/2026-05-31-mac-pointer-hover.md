<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksAndVocab/UIComponents/
  - ios/BooksAndVocab/Views/Bookshelf/
  - ios/BooksAndVocab/Views/Vocabulary/
  - ios/BooksAndVocab/Platform/
verified_against: frozen
-->
# Mac Catalyst Pointer / Hover Implementation Plan(Workstream B)

> **執行方式:** 使用 `phased-workflow` skill,所有 review agent 皆 `opus` + `run_in_background: true`。每完成一個 Task 立即 dispatch reviewer,PASS 才下一個。**禁批次**(鐵律 4)。

**Goal:** 依 [umbrella spec](../specs/2026-05-31-mac-catalyst-native-feel-design.md) Workstream B,為滑鼠/觸控板操作補上 hover 高亮、可拖曳分隔線 resize 游標、右鍵選單補缺。讓 Mac(及 iPad 觸控板)操作有精準指標回饋。

**Architecture:**
- 全 codebase **零 hover 基礎建設**(`.onHover`/`.hoverEffect` 0 命中)→ 新建兩個 hover modifier 放 `ios/BooksAndVocab/UIComponents/HoverHighlight.swift`:
  - `.appHoverLift()` — 卡片用,hover 時輕微 scale 浮起。
  - `.appHoverRowTint(cornerRadius:)` — list row 用,hover 時 bg tint。
- **hover 層不分流**:`.onHover` 在純觸控 iPhone 無指標事件 → 自動 no-op;iPad 觸控板/妙控與 Mac 共益(spec cross-cutting 鐵律 1 的明確例外)。
- divider resize 游標走 UIKit `UIPointerInteraction`(`.pointerStyle` 在 Catalyst 不可用),`MacColumnResizeCursor: UIViewRepresentable` 放 `Platform/`,**Catalyst-only** `#if targetEnvironment(macCatalyst)`。
- contextMenu 在 Catalyst 自動變右鍵選單,既有 7 檔/15 處免費受益;補缺 PodcastSeriesCard。

**Tech Stack:** SwiftUI / UIKit(`UIPointerInteraction`)/ XCTest。視覺改動靠 InjectionNext 熱載 + `ops/ios_build.sh` + Catalyst build + Mac/iPad manual。

**Motion 契約合規(`docs/sop/ui-design.md`):** 卡片是按鈕互動(NavigationLink/Button,既有 `BookshelfCardButtonStyle` 已用 pressed scale),故 `.appHoverLift` 的 scale 合規;list row 走 bg-tint(只動 background/opacity)嚴守「非按鈕互動禁 transform」。hover 動畫一律 `AppMotion.quickEaseOut`。

**Doc Sync(commit 強制):** Task 4 收尾更新 `docs/sop/ui-design.md`(hover modifier 用法 + `UIPointerInteraction` 路徑)+ `docs/reference/ui/components.md`(新增兩個 hover modifier + `MacColumnResizeCursor`)。

**Non-Goals(YAGNI,本 plan 不做):**
- **touch-target 緊縮**(`minHeight: 50` / `iconButtonSize: 52` 的 Catalyst 較密值)——風險最高(改全域尺寸常數)、需大量雙平台 manual 回歸、體感邊際。hover + 游標 + contextMenu 已達 mac 精準回饋核心。列 future,實測 B 後若仍覺鬆散再單獨開。
- 系統 `.hoverEffect`(改用自繪 modifier 保設計一致)。
- 雙擊開啟改單擊選取的 mac list 慣例(spec Non-Goal)。

---

## Task 1: `.appHoverLift()` + 卡片套用

**Files:**
- Create: `ios/BooksAndVocab/UIComponents/HoverHighlight.swift`
- Modify: `ios/BooksAndVocab/Views/Bookshelf/Components/BookCard.swift`(body 最外層 VStack)
- Modify: `ios/BooksAndVocab/Views/Bookshelf/Components/PodcastSeriesCard.swift`(body 最外層 VStack)
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`(card body 最外層)

- [ ] **Step 1: 新建 `HoverHighlight.swift` — `appHoverLift`**
```swift
//
//  HoverHighlight.swift
//  Books & Vocab
//
//  指標 hover 回饋 — 卡片浮起 / row tint。
//  .onHover 在純觸控裝置無指標事件,自動 no-op;iPad 觸控板 + Mac Catalyst 共益。
//

import SwiftUI

// MARK: - Card hover lift

private struct AppHoverLift: ViewModifier {
    var scale: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovered = false

    func body(content: Content) -> some View {
        // Reduce Motion 仍關 scale 動畫(ui-design.md:170);hover 改 no-op,觸控本就無 hover。
        let effectiveScale = reduceMotion ? 1.0 : scale
        content
            .scaleEffect(isHovered ? effectiveScale : 1.0)
            .animation(AppMotion.quickEaseOut, value: isHovered)
            .onHover { isHovered = $0 }
    }
}

extension View {
    /// 指標 hover 時卡片輕微浮起(scale)。卡片屬按鈕互動,scale 合 motion 契約。
    /// 觸控 iPhone 無 hover event → no-op。
    func appHoverLift(scale: CGFloat = 1.02) -> some View {
        modifier(AppHoverLift(scale: scale))
    }
}
```

- [ ] **Step 2: 套 BookCard** — `BookCard.swift` body 最外層 `VStack` 末端(`.enableInjection()` 之前)加 `.appHoverLift()`。

- [ ] **Step 3: 套 PodcastSeriesCard** — `PodcastSeriesCard.swift` 同樣 body `VStack` 末端 `.enableInjection()` 之前加 `.appHoverLift()`。

- [ ] **Step 4: 套 NotebookCard** — `NotebookCard.swift` 的 card body 最外層 view 末端加 `.appHoverLift()`(實作時定位最外層 modifier 鏈;注意 NotebookCard 已有 `NotebookDeckButtonStyle` pressed 效果,hover lift 與之不衝突,一個是 hover、一個是 pressed)。

- [ ] **Step 5: build 驗證**
Run: `./ops/ios_build.sh`(iOS,驗 no-op 路徑編譯)+ Catalyst build(`xcodebuild -project BooksAndVocab.xcodeproj -scheme BooksAndVocab -destination 'platform=macOS,variant=Mac Catalyst' -derivedDataPath /tmp/kg-catalyst-verify build`)。
Expected: 皆綠。

- [ ] **Step 6: Commit**
`ios: add appHoverLift + apply to book/podcast/notebook cards (Workstream B)`

---

## Task 2: `.appHoverRowTint()` + 可點 row + PodcastSeriesCard contextMenu

**Files:**
- Modify: `ios/BooksAndVocab/UIComponents/HoverHighlight.swift`(加 `appHoverRowTint`)
- Modify: `ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift`(PodcastSeriesCard 引用處補 `.contextMenu`)
- Modify: list row 套 hover 的檔(設定 `AppKeyValueRow` / NotebookListView 可點 row / OverviewTab 可點 row,實作時逐一定位)

- [ ] **Step 1: 加 `appHoverRowTint` — `HoverHighlight.swift`**
```swift
// MARK: - List row hover tint

private struct AppHoverRowTint: ViewModifier {
    let cornerRadius: CGFloat
    @Environment(\.appTheme) private var theme
    @State private var isHovered = false

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(theme.palette.primaryText.opacity(isHovered ? 0.05 : 0))
            )
            .animation(AppMotion.quickEaseOut, value: isHovered)
            .onHover { isHovered = $0 }
    }
}

extension View {
    /// list row 指標 hover 時 bg tint(只動 background,合 motion 契約)。
    /// 觸控 iPhone 無 hover event → no-op。
    func appHoverRowTint(cornerRadius: CGFloat = AppRadius.md) -> some View {
        modifier(AppHoverRowTint(cornerRadius: cornerRadius))
    }
}
```
(實作時確認 `AppRadius.md` 存在;若無改用實際 token。)

- [ ] **Step 2: 補 PodcastSeriesCard contextMenu** — `BookshelfView.swift` 的 PodcastSeriesCard 引用處(約 :264-266)補 `.contextMenu { … }`,提供與 BookCard 刪書對等的 series 動作(取消追蹤 / 重新整理等,依現有 PodcastSeries action 能力決定;**新 menu item 字串走 L10n**)。Catalyst 下自動成右鍵選單,iPad 長按受益。

- [ ] **Step 3: 套可點 row hover tint** — 對設定列表 `AppKeyValueRow`、NotebookListView 可點 row、OverviewTab 可點 row 加 `.appHoverRowTint()`(逐一定位;每個 row 的圓角配合既有 `cardBackground`/容器)。

- [ ] **Step 4: build 驗證**(同 Task 1 雙 build)

- [ ] **Step 5: Commit**
`ios: row hover tint + PodcastSeriesCard context menu (Workstream B)`

---

## Task 3: Divider resize 游標(UIPointerInteraction,Catalyst-only)

**Files:**
- Create: `ios/BooksAndVocab/Platform/MacColumnResizeCursor.swift`
- Modify: `ios/BooksAndVocab/Views/Vocabulary/MacDividerHandle.swift`(疊游標到 hit area)

- [ ] **Step 1: 新建 `MacColumnResizeCursor.swift`**
```swift
//
//  MacColumnResizeCursor.swift
//  Books & Vocab
//
//  可拖曳分隔線的欄寬調整游標 — Catalyst 專屬。
//  SwiftUI .pointerStyle(iOS 18+) 在 Mac Catalyst 不可用,故走 UIKit UIPointerInteraction。
//

import SwiftUI

#if targetEnvironment(macCatalyst)
struct MacColumnResizeCursor: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let view = UIView()
        view.backgroundColor = .clear
        view.isUserInteractionEnabled = true
        view.addInteraction(UIPointerInteraction(delegate: context.coordinator))
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UIPointerInteractionDelegate {
        func pointerInteraction(
            _ interaction: UIPointerInteraction,
            styleFor region: UIPointerRegion
        ) -> UIPointerStyle? {
            // 垂直 beam = 直立分隔線上的欄寬調整提示(Catalyst 無原生 resize-LR 游標,
            // verticalBeam 為最接近的近似)。length 配 divider 視覺高度。
            UIPointerStyle(shape: .verticalBeam(length: 24))
        }
    }
}
#endif
```

- [ ] **Step 2: 疊到 `DraggableDivider`** — `MacDividerHandle.swift` body,在既有 `#if targetEnvironment(macCatalyst) .onTapGesture(count: 2)` 同區塊加 overlay:
```swift
            #if targetEnvironment(macCatalyst)
            .onTapGesture(count: 2) { onDoubleClick() }
            .overlay { MacColumnResizeCursor() }
            #endif
```
**注意(實作驗證點):** `UIPointerInteraction` 需 view 參與 hit-test 才收到 pointer region。先**不加** `allowsHitTesting(false)`,實機驗證游標生效且 overlay 不吃掉既有 `highPriorityGesture(dragGesture)` 拖曳;若 overlay 攔截拖曳,改用 `.background { MacColumnResizeCursor() }` 或調整 z 次序,確保拖曳仍可用。

- [ ] **Step 3: Catalyst build 驗證**
Run: Catalyst build。
Expected: 編譯通過。

- [ ] **Step 4: Manual 驗證點(交付說明)**
Mac 實機:(a) 滑鼠移到分隔線游標變欄寬調整樣式;(b) 拖曳仍正常改 panel 寬度;(c) 雙擊重置仍有效。

- [ ] **Step 5: Commit**
`ios: column-resize cursor on draggable divider via UIPointerInteraction (Workstream B)`

---

## Task 4: Doc Sync

**Files:**
- Modify: `docs/sop/ui-design.md`(hover 規範)
- Modify: `docs/reference/ui/components.md`(新元件)

- [ ] **Step 1: 更新 `ui-design.md`**
在「Mac Catalyst 平台適配」段補:hover 回饋走 `.appHoverLift()`(卡片 scale)/ `.appHoverRowTint()`(row bg tint),`.onHover` 觸控裝置 no-op 故 iPad+Mac 共益不分流;divider 欄寬游標走 `MacColumnResizeCursor`(`UIPointerInteraction`,因 `.pointerStyle` Catalyst 不可用)。

- [ ] **Step 2: 更新 `components.md`**
新增 `AppHoverLift` / `AppHoverRowTint`(`.appHoverLift()` / `.appHoverRowTint()`)+ `MacColumnResizeCursor`(Catalyst 欄寬游標)條目。

- [ ] **Step 3: docs_lint**
Run: `./ops/docs_lint.sh`
Expected: ERROR 0;改動檔 verified_against 更新至最新 code commit。

- [ ] **Step 4: Commit**
`docs: sync Catalyst hover/pointer (ui-design / components)`

---

## 完成準則

- `./ops/ios_build.sh` + Catalyst build 皆綠。
- 四個 commit 各經 reviewer PASS。
- iPhone 觸控路徑零回歸(hover modifier 在無指標時 no-op;divider 游標 Catalyst-only)。
- Mac/iPad manual 驗證點交付:卡片 hover 浮起、row hover tint、divider 欄寬游標 + 拖曳、PodcastSeriesCard 右鍵選單。
