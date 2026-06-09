<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksAndVocab/Views/Vocabulary/
verified_against: frozen
-->
# Notebook Editorial Cover & List Implementation Plan

> **執行方式:** 使用 `phased-workflow` skill,所有 review agent 皆 `opus` + `run_in_background: true`。每完成一個 Phase 立即 dispatch reviewer 審 N-1 phase,PASS 才下一個。**禁批次**(鐵律 4)。

**Goal:** 把 NotebookListView 整頁(cover composition / 底部 metadata / 使用中標識 / 今日複習入口 / 網格平衡 / toolbar)按 [spec](../specs/2026-05-23-notebook-editorial-cover-design.md) 重做為 editorial 風格。

**Architecture:**
- 新增 `EditorialCoverComposition` 私有 view(`NotebookCard.swift` 內)以 `.overlay` 套在既有 `NotebookStackedCoverView`(grid)/ `NotebookCoverView`(hero)之上,不動既有 cover render 內部
- `NotebookPalette` 加 `darken(_:by:)` HSB helper + 對應 unit test
- `NotebookStackMetrics` 加 `patternOpacity` 單一來源 token
- `NotebookListView` 解除 `VocabReviewBanner` 引用,改 page section header + 既有 `VocabReviewCTAPill`
- `NotebookFilterChip` 既有元件不刪,從 banner 移入 toolbar Menu
- Toolbar 加一顆 filter Menu(條件 `notebooks.count >= 2`)

**Tech Stack:** SwiftUI / SwiftData / TipKit / XCTest。InjectionNext 熱載驗證 visual change。

**Doc Sync(commit 強制):** 每個 Phase 末若涉及對應檔變動,同 commit 更新 doc。最終 doc sync Phase 收尾。

---

## Task 1: Foundation — `NotebookPalette.darken(_:by:)` + `patternOpacity` token

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookPalette.swift`
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackMetrics.swift`
- Create: `ios/BooksAndVocabTests/Views/Vocabulary/NotebookPaletteTests.swift`(若已存在則 modify)

- [ ] **Step 1: 寫 failing test — `NotebookPaletteTests.swift`**
```swift
import XCTest
import SwiftUI
@testable import BooksAndVocab

final class NotebookPaletteTests: XCTestCase {
    func testDarkenReducesBrightness() {
        let original = Color(hex: "#AFC2D3")!  // 海洋
        let darkened = NotebookPalette.darken(original, by: 0.3)
        let originalHSB = original.hsbComponents
        let darkenedHSB = darkened.hsbComponents
        XCTAssertEqual(darkenedHSB.brightness, originalHSB.brightness * 0.7, accuracy: 0.01)
        XCTAssertEqual(darkenedHSB.hue, originalHSB.hue, accuracy: 0.01)
        XCTAssertEqual(darkenedHSB.saturation, originalHSB.saturation, accuracy: 0.01)
    }

    func testDarkenZeroIsIdentity() {
        let original = Color(hex: "#DEC69C")!  // 琥珀
        XCTAssertEqual(NotebookPalette.darken(original, by: 0).hsbComponents.brightness,
                       original.hsbComponents.brightness, accuracy: 0.001)
    }
}
```
(若 `Color.hsbComponents` 尚不存在,以 `UIColor(swiftUIColor).getHue(...)` 包裝出來;放 `Color+HSB.swift` test helper 或正式 extension)

- [ ] **Step 2: 跑 test 確認失敗**
Run: 透過 `./ops/ios_test.sh -only-testing:BooksAndVocabTests/NotebookPaletteTests` **(user 明確要求才跑;否則延後到 Phase 末批次)**
Expected: FAIL — `darken(_:by:)` undefined

- [ ] **Step 3: 最小實作 — `NotebookPalette.darken`**
```swift
extension NotebookPalette {
    /// 把 cover color HSB brightness ×(1 - amount),保持 hue/saturation。
    /// amount 範圍 [0, 1];0.3 = brightness ×0.7。
    static func darken(_ color: Color, by amount: Double) -> Color {
        #if canImport(UIKit)
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(color).getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return Color(hue: Double(h), saturation: Double(s), brightness: Double(b) * (1 - amount), opacity: Double(a))
        #else
        // macOS fallback — 同邏輯走 NSColor
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        NSColor(color).usingColorSpace(.sRGB)?.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return Color(hue: Double(h), saturation: Double(s), brightness: Double(b) * (1 - amount), opacity: Double(a))
        #endif
    }
}
```

- [ ] **Step 4: 加 `NotebookStackMetrics.patternOpacity` token**
```swift
extension NotebookStackMetrics {
    /// Editorial pattern overlay opacity — D1.1 spec
    static let patternOpacity: Double = 0.18
}
```

- [ ] **Step 5: Build pass**
Run: `./ops/ios_build.sh`
Expected: ✓ build succeeded

- [ ] **Step 6: Commit**
Message: `ios: NotebookPalette.darken helper + patternOpacity token (D1 / D1.1 foundation)`

---

## Task 2: `EditorialCoverComposition` private view + AA 對比測試

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`(加 private struct `EditorialCoverComposition`)
- Create: `ios/BooksAndVocabTests/Views/Vocabulary/NotebookCoverContrastTests.swift`

- [ ] **Step 1: 寫 failing test — `NotebookCoverContrastTests.swift`**
```swift
import XCTest
import SwiftUI
@testable import BooksAndVocab

final class NotebookCoverContrastTests: XCTestCase {
    /// 鎖 Morandi 12 色 cover 對 primaryText light(#37352F)≥ AA 4.5:1
    func testMorandiCoversPassAALight() {
        let textColor = Color(hex: "#37352F")!
        for (name, hex) in NotebookPalette.colors {
            let coverColor = Color(hex: hex)!
            let ratio = WCAGContrast.ratio(textColor, coverColor)
            XCTAssertGreaterThanOrEqual(ratio, 4.5, "\(name) cover (\(hex)) fails AA against #37352F: ratio \(ratio)")
        }
    }

    /// Dark mode 套 .brightness(-0.2) 後對 primaryText dark(#E6E6E3)仍 ≥ AA
    func testMorandiCoversPassAADark() {
        let textColor = Color(hex: "#E6E6E3")!
        for (name, hex) in NotebookPalette.colors {
            let darkenedCover = NotebookPalette.darken(Color(hex: hex)!, by: 0.2)
            let ratio = WCAGContrast.ratio(textColor, darkenedCover)
            XCTAssertGreaterThanOrEqual(ratio, 4.5, "\(name) cover dark-shifted fails AA against #E6E6E3: ratio \(ratio)")
        }
    }
}
```
(`WCAGContrast.ratio(_:_:)` helper — 若 codebase 無,加 test helper `BooksAndVocabTests/Helpers/WCAGContrast.swift`,用標準 sRGB relative luminance 公式)

- [ ] **Step 2: 跑 test 確認失敗**
Expected: FAIL — `WCAGContrast` undefined OR contrast 計算未實作

- [ ] **Step 3: 加 `WCAGContrast` test helper**
```swift
enum WCAGContrast {
    static func ratio(_ a: Color, _ b: Color) -> Double {
        let la = relativeLuminance(a)
        let lb = relativeLuminance(b)
        let lighter = max(la, lb)
        let darker = min(la, lb)
        return (lighter + 0.05) / (darker + 0.05)
    }

    private static func relativeLuminance(_ color: Color) -> Double {
        #if canImport(UIKit)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
        #else
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        NSColor(color).usingColorSpace(.sRGB)?.getRed(&r, green: &g, blue: &b, alpha: &a)
        #endif
        func channel(_ v: CGFloat) -> Double {
            let x = Double(v)
            return x <= 0.03928 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }
}
```

- [ ] **Step 4: 跑 test 確認 light 通過、dark 視結果**
若 dark 通過 = D1 dark fallback `.brightness(-0.2)` 設計成立;若 fail = 回 spec 調 fallback 數字並更新對應 doc

- [ ] **Step 5: 實作 `EditorialCoverComposition` private view**
位置: `NotebookCard.swift` 末端(extension 或 private struct)
```swift
/// D1 editorial composition — overlay 套在既有 cover view 上,跟隨 coverArea rotation。
private struct EditorialCoverComposition: View {
    let name: String
    let cardCount: Int
    let coverColor: Color
    let isActive: Bool
    let style: NotebookCardStyle
    @Environment(\.appSkin) private var skin

    private var nameFont: Font {
        switch style {
        case .grid: return AppFonts.serif(size: 22, bold: true)
        case .hero: return AppFonts.serif(size: 32, bold: true)
        }
    }

    private var outerPadding: CGFloat {
        switch style {
        case .grid: return AppSpacing.s3
        case .hero: return AppSpacing.s4
        }
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // D3 spine — grid only, isActive
            if style == .grid && isActive {
                HStack(spacing: 0) {
                    Rectangle()
                        .fill(NotebookPalette.darken(coverColor, by: 0.4))
                        .frame(width: 3)
                        .accessibilityHidden(true)
                    Spacer(minLength: 0)
                }
            }

            GeometryReader { geo in
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(name)
                        .font(nameFont)
                        .foregroundStyle(skin.palette.primaryText)
                        .lineLimit(2)
                        .truncationMode(.tail)

                    Rectangle()
                        .fill(NotebookPalette.darken(coverColor, by: 0.3))
                        .frame(width: geo.size.width * 0.25, height: AppMetrics.dividerStandard)
                }
                .padding(outerPadding)
            }

            if cardCount > 0 {
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Text(L10n.format("%@ 詞", "\(cardCount)"))
                            .font(skin.typography.monoLabel)
                            .monospacedDigit()
                            .foregroundStyle(skin.palette.secondaryText)
                    }
                }
                .padding(outerPadding)
            }
        }
    }
}
```
**rule width** 走 `GeometryReader` 動態取 cover 寬 × 0.25,落實 spec D1「cover 寬 × 0.25」要求。

- [ ] **Step 6: Build pass(此 phase composition 尚未掛 cover, build 通過即可)**
Run: `./ops/ios_build.sh`

- [ ] **Step 7: Commit**
Message: `ios: EditorialCoverComposition view + AA contrast tests (D1)`

---

## Task 3: Wire `EditorialCoverComposition` to grid + hero(name text 改 opt-in,不影響其他 callsite)

**重大背景 — `NotebookCoverView` 被 6 處引用,不可直接移除 center name text:**

```
1. ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift:593         — 書架封面縮圖
2. ios/BooksAndVocab/Views/Podcast/PodcastEpisodeListView.swift:226  — 播客集數列表
3. ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookEditSheet.swift:63 — cover picker preview
4. ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift:79 — stacked top layer
5. ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift:191       — hero variant
6. ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift:190 — #Preview
```

**策略:** 加 `showsName: Bool = true` 參數至 `NotebookCoverView`(default 保持既有行為,Bookshelf/Podcast/EditSheet/Preview 全 zero-touch);`NotebookStackedCoverView` 同樣加 `showsName: Bool = true` 並透傳。`NotebookCard.coverArea` 兩條分支(grid + hero)呼叫時傳 `showsName: false`,讓 editorial overlay 不被底下白字穿透。

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift`(`NotebookCoverView` 加 `showsName` param,gate `Text(name)` 渲染)
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift`(加 `showsName` param 並透傳至 `NotebookCoverView`)
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`(`coverArea` 兩處呼叫傳 `showsName: false`,並加 `.overlay { EditorialCoverComposition(...) }`)

- [ ] **Step 1: grep 確認 callsite 不變**
Run: `grep -rn "NotebookCoverView(" /Users/chenliangyu/kg/ios --include="*.swift"`
Expected: 6 callsite 全列出。逐一確認 4 個非 NotebookCard 場景(Bookshelf / Podcast / EditSheet / Preview)的 `Text(name)` 應該繼續顯示。

- [ ] **Step 2: `NotebookCoverView` 加 `showsName: Bool = true`**
參數加在最後一個位置(維持 source-compat;預設 true);內部 `Text(name)` 區塊包 `if showsName { ... }`。`NotebookStackedCoverView` 同樣加 `showsName` 並透傳。

- [ ] **Step 3: 在 `NotebookCard.coverArea` 兩處呼叫加 `showsName: false` + overlay**
```swift
@ViewBuilder
private var coverArea: some View {
    Group {
        switch style {
        case .grid:
            NotebookStackedCoverView(
                color: coverColor,
                pattern: pattern,
                coverImagePath: data.coverImagePath,
                name: data.name,
                layerCount: NotebookStackMetrics.layerCount(forCardCount: data.cardCount),
                aspectRatio: coverAspectRatio,
                seed: NotebookStackMetrics.stableSeed(for: data.name),
                showsName: false  // ← 新增,editorial overlay 接管
            )
        case .hero:
            NotebookCoverView(
                color: coverColor,
                pattern: pattern,
                coverImagePath: data.coverImagePath,
                name: data.name,
                showsName: false  // ← 新增
            )
            .aspectRatio(coverAspectRatio, contentMode: .fill)
            .clipShape(UnevenRoundedRectangle(
                topLeadingRadius: skin.radii.card,
                topTrailingRadius: skin.radii.card
            ))
        }
    }
    .overlay {
        EditorialCoverComposition(
            name: data.name,
            cardCount: data.cardCount,
            coverColor: coverColor,
            isActive: data.isActive,
            style: style
        )
    }
    // 舊 .overlay(alignment: .topTrailing) { 使用中 pill } 整段移除
    .rotationEffect(coverRotation, anchor: .bottom)
}
```

- [ ] **Step 4: 移除舊 `showsActivePill` / `Text("使用中")` 區塊**
`NotebookCard.swift` 內既有 `.overlay(alignment: .topTrailing) { if showsActivePill { ... } }` 刪除。`showsActivePill` computed 也一併移除。

- [ ] **Step 5: Build pass + InjectionNext 熱載驗證 simulator**
Run: `./ops/ios_build.sh`
打開 NotebookListView → 看到 serif name 左上 / rule / `N 詞` 右下 / active 本左側 3pt spine。

- [ ] **Step 6: Commit**
Message: `ios: wire EditorialCoverComposition to NotebookCard cover (D1 + D3)`

---

## Task 4: D2 — 底部 metadata 收斂

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`(`metadataArea`)

- [ ] **Step 1: 重寫 `metadataArea`**
```swift
@ViewBuilder
private var metadataArea: some View {
    HStack(spacing: AppSpacing.s2) {
        ProgressCapsule(
            progress: totalSynced > 0 ? reviewProgress : 0,
            label: nil,
            fillColor: coverColor,
            trackColor: skin.palette.progressBarBackground,
            height: 5
        )
        .frame(maxWidth: .infinity)

        if data.dueCount > 0 {
            Label(L10n.format("%@ 到期", "\(data.dueCount)"), systemImage: "clock.badge")
                .font(skin.typography.monoLabel)
                .monospacedDigit()
                .foregroundStyle(skin.palette.warning)
                .fixedSize(horizontal: true, vertical: false)
        }
    }
    .padding(.horizontal, AppSpacing.s3)
    .padding(.vertical, AppSpacing.s2)
}
```
(ProgressCapsule fillColor 從 `skin.palette.accent` 改 `coverColor` — editorial「閱讀進度條跟書同色」族群感;due chip 用 `L10n.format` 過 i18n lint)

- [ ] **Step 2: Build + InjectionNext 驗證 simulator**
看到底部只有 ProgressCapsule + 條件 due chip;無 cardCount / pending / unlearned。

- [ ] **Step 3: Commit**
Message: `ios: collapse NotebookCard bottom metadata to progress + due chip (D2)`

---

## Task 5: D4 — Top section header + `VocabReviewCTAPill`,解除 `VocabReviewBanner` 引用

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift`(`body` 內 banner 區塊)

- [ ] **Step 1: 刪除 `VocabReviewBanner` 兩處引用**(line 79-101),改為:
```swift
if totalDueCount > 0 || totalUnlearnedCount > 0 {
    HStack {
        Text("今日複習".localized)
            .font(skin.typography.sectionTitle)
            .foregroundStyle(skin.palette.primaryText)

        Spacer(minLength: 8)

        VocabReviewCTAPill(
            dueCount: filteredDueEntries.count,
            unlearnedCount: filteredUnlearnedEntries.count,
            onStartDue: { startReview(with: filteredDueEntries) },
            onStartUnlearned: { startReview(with: filteredUnlearnedEntries) },
            onStartMixed: { startReview(with: filteredDueEntries + filteredUnlearnedEntries) }
        )
    }
    .padding(.horizontal, skin.metrics.pageHorizontalInset)
}
```

- [ ] **Step 2: Build + 熱載驗證**
頂部不再是卡片框;`今日複習` serif heading + 右側奶黃 pill `▶ 539`。

- [ ] **Step 3: Commit**
Message: `ios: replace top banner with section header + VocabReviewCTAPill (D4)`

---

## Task 6: D5 + D6 + D7 — Grid 移除 add card / Filter 進 toolbar / Toolbar 終態

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift`(grid loop + toolbar)

- [ ] **Step 1: 刪除 grid 內 `NotebookAddCard` 區塊**
```swift
// Before (line 134-139)
if authManager.isLoggedIn {
    Button { showCreateSheet = true } label: { NotebookAddCard() }
        .buttonStyle(.plain)
}
// After: 整段刪除
```

- [ ] **Step 2: Toolbar 加 filter button → 復用 `NotebookFilterPickerSheet`(D6)**

**驗證的事實:** `NotebookFilter` 是 struct(`selectedIds: Set<String>` + `.isFiltered` computed),**不是 enum**;filter UI 是 `NotebookFilterChip`(Button → `NotebookFilterPickerSheet`)。所以不能用 `Picker(selection:)` + `.allCases`。正確做法 = toolbar button 直接觸發 `NotebookFilterPickerSheet`,跟既有 chip 一樣。

在 toolbar 第一個位置加:
```swift
ToolbarItem(placement: .confirmationAction) {
    if notebooks.count >= 2 {
        Button {
            showFilterSheet = true
        } label: {
            Image(systemName: reviewFilter.isFiltered
                ? "line.3.horizontal.decrease.circle.fill"
                : "line.3.horizontal.decrease.circle")
                .foregroundStyle(reviewFilter.isFiltered ? skin.palette.accent : skin.palette.tintMuted)
        }
        .accessibilityLabel("篩選單字本".localized)
    }
}
```
搭配 `@State private var showFilterSheet = false` + `.toastSheet(isPresented: $showFilterSheet) { NotebookFilterPickerSheet(filter: $reviewFilter, notebooks: notebooks.filter { !$0.isDeleted }) }`。

效果:跟既有 chip 完全一樣,只是入口從 banner 內 chip 移到 toolbar icon。

- [ ] **Step 3: Build + 熱載驗證**
2+ notebook 時 grid 永遠對稱(無 + 卡);toolbar 左多一顆 funnel;單 notebook 時 funnel 不顯示。

- [ ] **Step 4: Commit**
Message: `ios: remove inline NotebookAddCard + filter moves to toolbar Menu (D5/D6/D7)`

---

## Task 7: D1.1 — Pattern overlay opacity 0.18 migration

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift`

- [ ] **Step 1: grep 全部 pattern Canvas `.opacity(...)` callsite**
```bash
grep -n "opacity" ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift
```

- [ ] **Step 2: 統一替換為 `NotebookStackMetrics.patternOpacity`**
原本各 pattern 內 `.fill(...).opacity(0.3)` → `.fill(...).opacity(NotebookStackMetrics.patternOpacity)`

- [ ] **Step 3: Build + 熱載驗證**
有 pattern 的 notebook 視覺上 pattern 變淡(0.3 → 0.18),serif name 為視覺主角。

- [ ] **Step 4: Commit**
Message: `ios: pattern overlay opacity 0.3 → 0.18 via patternOpacity token (D1.1)`

---

## Task 8: Debug Scenarios 補測 — Notebook stress cases

**Files:**
- Modify: `ios/BooksAndVocab/Debug/Scenarios/NotebookListScenarios.swift`

- [ ] **Step 1: 加 stress scenarios**
依 UI Design SOP 鐵律(5 種 stress case):happy / long-name / large-numbers / narrow-width / dynamicTypeSize(.accessibility3)
- 長 name(中文 30 字 + 英文 50 字)→ 確保 `lineLimit(2) + truncationMode(.tail)` 不破
- 大 cardCount(99999 詞)→ monoLabel 字寬不抖
- 大 dueCount(9999 到期)
- 窄 grid cell(iPhone SE 寬)
- accessibility3 dynamicType

- [ ] **Step 2: Run scenarios in simulator + 存 screenshot artifact**
透過 `Debug/Scenarios/NotebookListScenarios.swift` 在 SwiftUI Preview / Debug menu 開啟 5 種 stress case;每個 case 在 simulator 截圖存至 `docs/assets/screenshots/notebook-editorial/<case>.png`(per 鐵律 2「驗證先於宣稱」— 不只人眼看過,留下視覺 artifact 入 PR);PR 描述附 thumbnail 五張

- [ ] **Step 3: Commit**
Message: `ios(debug): stress scenarios for editorial NotebookCard`

---

## Task 9: Doc Sync — 4 份 reference doc 更新

**Files:**
- Modify: `docs/reference/feature_boundary/notebook.md`
- Modify: `docs/reference/ui/state_matrix.md`
- Modify: `docs/reference/ui/components.md`
- Modify: `docs/reference/product_surface.md`

- [ ] **Step 1: `notebook.md`** — 改寫 line 24(`NotebookListView` 描述去除「`≥2` → `LazyVGrid + NotebookAddCard`」,改「`≥2` → `LazyVGrid` 純 notebook 卡;`+` 走 toolbar」);line 32(`NotebookCard` 行數 + 新增 `EditorialCoverComposition` private struct);`NotebookAddCard` 註記「kept for future onboarding empty state use,not used by NotebookListView grid」;`NotebookCoverView` / `NotebookStackedCoverView` 加 `showsName` param 說明;**verified_against** 更新為 merge 後 HEAD commit hash(commit 時 `git rev-parse --short HEAD` 取最新)

- [ ] **Step 2: `state_matrix.md`** — 加 Notebook list 狀態覆蓋表(對齊 spec State Matrix 6 列)

- [ ] **Step 3: `components.md`** — 移除 `VocabReviewBanner` 在 NotebookListView 的引用標記;`VocabReviewCTAPill` 補「亦用於 NotebookListView top section」

- [ ] **Step 4: `product_surface.md`** — Notebook bookshelf 段補:editorial cover composition / spine active indicator / page section header review entry

- [ ] **Step 5: 跑 `ops/docs_lint.sh`**
Run: `./ops/docs_lint.sh`
Expected: ✓ frontmatter 完整、verified_against 未落後

- [ ] **Step 6: Commit**
Message: `docs: sync notebook editorial cover redesign across reference docs`

---

## Task 10: Final 全套 build + test + sanity pass

- [ ] **Step 1: 整套 build**
Run: `./ops/ios_build.sh`
Expected: ✓ 0 warning 0 error

- [ ] **Step 2: 整套 test**(user 明確要求才跑,否則交給 phased-workflow 收尾)
Run: `./ops/ios_test.sh -only-testing:BooksAndVocabTests/NotebookPaletteTests -only-testing:BooksAndVocabTests/NotebookCoverContrastTests`
Expected: ✓ all pass

- [ ] **Step 3: simulator 走 happy path**
- 多 notebook → 看到 editorial cover / spine / section header / pill
- 單 notebook → hero 套 D1+D2、無 spine
- 沒 due → 底部只有 progress、無 chip、頂部無 section header
- pending entry > 0 → TipView 出現

- [ ] **Step 4: 開 PR**
PR 標題: `ios: Notebook editorial cover & list redesign (D1-D8)`
PR body 引 spec + plan,Doc-Sync 段勾選齊全

---

## 規則重申

- **每個 Task 完成立刻 dispatch opus review agent 審 N-1 Task**(鐵律 4)。Reviewer prompt 模板用 `.claude/skills/design/spec-document-reviewer-prompt.md` 的精神 — 改成「task 對齊 spec / token 正確 / TDD 紅綠循環 / commit 訊息合 CLAUDE.md / iOS UI hard rules 遵守」。
- **`./ops/ios_test.sh` 不主動跑**(CLAUDE.md scope 規則)— 除非 user 要求 / Task 10 收尾。`./ops/ios_build.sh` 可主動。
- **i18n lint**:Task 5 / 6 / 7 凡新加 user-facing 字串需走 `L10n.string` / `.localized`,跑 `ops/i18n_lint.sh` 檢查。
- **InjectionNext 熱載**驗證 visual:不每次 rebuild。但 token / struct shape 改 → cold restart。
