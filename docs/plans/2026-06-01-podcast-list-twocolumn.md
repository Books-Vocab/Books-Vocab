<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksAndVocab/Views/Podcast/
  - ios/BooksAndVocab/UIComponents/ListSectionCard.swift
verified_against: frozen
-->

# Podcast 集數列表雙欄 + 對齊單字列表組件 Implementation Plan

> ⚠️ **已撤回（frozen）：** 本計畫的「regular 雙欄 inline player」設計已於後續重構收斂回**單欄 push**（`PodcastDetailRouter` / `PodcastDetailPresentation` 已移除，集數一律 push）。權威現況見 `ios/BooksAndVocab/Views/Podcast/PodcastDetailRouter.swift` 檔頭。此檔僅存歷史。

> **執行方式:** 使用 phased-workflow skill，所有 agent 皆 opus、背景執行。逐 task review（鐵律4）PASS 才下一個。

**Goal:** 集數 row 對齊單字 `WordRow` 視覺契約；Mac/iPad regular 左列表常駐 + 右欄 inline 完整 `PodcastPlayerView`（now-playing，即時換集）；iPhone compact 行為不變。

**Architecture:** 鏡射單字本 master-detail：新 `PodcastDetailRouter`（@Observable，`selectedEpisodeRemoteId`）+ `PodcastDetailPresentation` modifier（regular 走 `safeAreaInset(.trailing)` + 複用 `DraggableDivider`）。右欄掛單一 `PodcastPlayerView`，靠既有 `.task(id: episodeId)` swap，無全域 audio singleton。

**Tech Stack:** SwiftUI / Mac Catalyst / 既有 `LayoutMode`/`DraggableDivider`/`MacDetailPanelMetrics`/`AppMotion`/`AppSpacing`。

**Spec:** `docs/specs/2026-06-01-podcast-list-twocolumn-design.md`

**測試說明:** 雙欄 SwiftUI 行為無法單元測試。可測者（`PodcastDetailRouter` 狀態邏輯）走 TDD；View 層改動以 `ios_build.sh` + lint + 實機 Catalyst/iPhone 驗證。每 task 後派 opus code-reviewer。

---

### Task 1: `PodcastDetailRouter`（純狀態，TDD）

**Files:**
- Create: `ios/BooksAndVocab/Views/Podcast/PodcastDetailRouter.swift`
- Test: `ios/BooksAndVocabTests/Podcast/PodcastDetailRouterTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
@MainActor
func test_router_selection_drives_hasDetail() {
    let r = PodcastDetailRouter()
    XCTAssertFalse(r.hasDetail)
    r.show(episodeRemoteId: "ep-1")
    XCTAssertEqual(r.selectedEpisodeRemoteId, "ep-1")
    XCTAssertTrue(r.hasDetail)
    r.dismiss()
    XCTAssertNil(r.selectedEpisodeRemoteId)
    XCTAssertFalse(r.hasDetail)
}
```

- [ ] **Step 2: 跑 test 確認失敗**（型別不存在）

- [ ] **Step 3: 寫最小實作**
```swift
import SwiftUI

@Observable @MainActor
final class PodcastDetailRouter {
    var selectedEpisodeRemoteId: String?
    var hasDetail: Bool { selectedEpisodeRemoteId != nil }
    func show(episodeRemoteId: String) { selectedEpisodeRemoteId = episodeRemoteId }
    func dismiss() { selectedEpisodeRemoteId = nil }
}

private struct PodcastDetailRouterKey: EnvironmentKey {
    static let defaultValue: PodcastDetailRouter? = nil
}
extension EnvironmentValues {
    var podcastDetailRouter: PodcastDetailRouter? {
        get { self[PodcastDetailRouterKey.self] }
        set { self[PodcastDetailRouterKey.self] = newValue }
    }
}
```

- [ ] **Step 4: 跑 test 確認通過**（用 `ios_test.sh`，需使用者同意；或 reviewer 確認邏輯）

- [ ] **Step 5: Commit** `ios: add PodcastDetailRouter for episode master-detail`

---

### Task 2: `PodcastPlayerView` 支援 inline 呈現

**Files:**
- Modify: `ios/BooksAndVocab/Views/Podcast/PodcastPlayerView.swift`（`episodeId` L8、`body` L97 委派 `fullBody` L102、`Group{...}`+modifier 鏈在 `fullBody` 內 L104-204）

> **架構決策（刻意偏離 vocab）:** 單字本 inline panel 用 `WordDetailSheet(wrapInNavigation:false)` + 自製 `VocabOverlayHeader`，**不**嵌套 NavigationStack。本案右欄為 host 住 player 既有 `ToolbarItem(.topBarTrailing)` 設定鍵（`.topBarTrailing` 需 ambient nav bar，否則靜默消失），改採**嵌套 NavigationStack**。此為 opt-in（預設 false，僅 inline caller 傳 true），且 inline 設定鍵可用性列為 Task 5 實機 hard gate。

- [ ] **Step 1:** 加參數 `var wrapInNavigation: Bool = false`（緊接 `let episodeId: String`）。**預設 false** → 現有 push caller（`BookshelfView.swift:100`，已在 BookshelfView NavigationStack 內）零改動、語意不變，避免雙層 NavigationStack 回歸（L84-86 freeze-fix 註解警告的情境）。

- [ ] **Step 2:** 把 `fullBody`（L102）內的 `Group { ... }` + 所有 modifier 鏈抽成 `private var playerCore: some View`。`fullBody` 改為：
```swift
private var fullBody: some View {
    Group {
        if wrapInNavigation {
            NavigationStack { playerCore }
        } else {
            playerCore
        }
    }
}
```
（`body` L97-100 的 `.enableInjection()` wrapper 不動。）inline caller 傳 `wrapInNavigation: true` → 自帶 NavigationStack host 設定鍵。

- [ ] **Step 3:** `.toolbar(.hidden, for: .tabBar)`（位於 `playerCore` modifier 鏈，原 L131）改條件化——inline/Catalyst 跳過：
```swift
#if !targetEnvironment(macCatalyst)
.toolbar(wrapInNavigation ? .visible : .hidden, for: .tabBar)
#endif
```

- [ ] **Step 4:** `ios_build.sh` exit 0 + `catalyst_lint.sh --strict` 0。確認 `BookshelfView.swift:100` 未改、push 行為不變。

- [ ] **Step 5: Commit** `ios: support inline presentation in PodcastPlayerView`

---

### Task 3: `PodcastDetailPresentation` modifier

**Files:**
- Create: `ios/BooksAndVocab/Views/Podcast/PodcastDetailPresentation.swift`

rebuild 自 `NotebookDetailPresentation`（去 review/edit 分支）。

- [ ] **Step 1:** 實作 ViewModifier：
```swift
struct PodcastDetailPresentation: ViewModifier {
    let router: PodcastDetailRouter
    let layoutMode: LayoutMode

    @AppStorage("kg_podcast_panel_width") private var panelWidth: Double = Double(MacDetailPanelMetrics.defaultWidth)
    @State private var dragWidth: CGFloat?
    @State private var containerWidth: CGFloat = 800

    private var effectivePanelWidth: CGFloat {
        let desired = CGFloat(panelWidth)
        let maxAllowed = containerWidth - MacDetailPanelMetrics.leftMinWidth
        return min(desired, max(maxAllowed, MacDetailPanelMetrics.minWidth))
    }

    func body(content: Content) -> some View {
        Group {
            if layoutMode.usesInlineDetail {
                content
                    .safeAreaInset(edge: .trailing, spacing: 0) {
                        if router.hasDetail, let id = router.selectedEpisodeRemoteId {
                            HStack(spacing: 0) {
                                DraggableDivider(
                                    panelWidth: Binding(get: { CGFloat(panelWidth) }, set: { panelWidth = Double($0) }),
                                    dragWidth: $dragWidth,
                                    containerWidth: containerWidth,
                                    onDoubleClick: {
                                        withAnimation(AppMotion.standardSpring) {
                                            panelWidth = Double(MacDetailPanelMetrics.defaultWidth)
                                        }
                                    }
                                )
                                PodcastPlayerView(episodeId: id, wrapInNavigation: true)  // 唯一傳 true 處
                                    .frame(width: dragWidth ?? effectivePanelWidth)
                            }
                            .transition(.drawerReveal)
                        }
                    }
                    .animation(AppMotion.standardSpring, value: router.hasDetail)
                    .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { containerWidth = $0 }
                    .onAppear { dragWidth = nil }
            } else {
                content  // compact：右欄不掛，沿用 NavigationLink push
            }
        }
        .onChange(of: layoutMode) { _, newMode in
            if !newMode.usesInlineDetail { router.dismiss() }
        }
    }
}

extension View {
    func podcastDetailPresentation(router: PodcastDetailRouter, layoutMode: LayoutMode) -> some View {
        modifier(PodcastDetailPresentation(router: router, layoutMode: layoutMode))
    }
}
```
空選態（`hasDetail == false`）右欄不顯示，左列表佔滿。`PodcastPlayerView` 隨 `id` 變化由既有 `.task(id:)` swap。

- [ ] **Step 2:** `ios_build.sh` exit 0 + `catalyst_lint.sh --strict` 0（確認 player 設定仍是 .sheet，無 toolbar-popover）。

- [ ] **Step 3: Commit** `ios: add PodcastDetailPresentation two-column modifier`

---

### Task 4: 抽 `ListSectionCard` 共用容器

**Files:**
- Create: `ios/BooksAndVocab/Views/Components/ListSectionCard.swift`

骨架 = `VStack(spacing:0) + cardBackground fill + border stroke`（podcast L334-367 與 vocab `VocabListCard` 共同形狀）。**注意現況容器 L334-367 = 背景 fill（L360-363）+ `.overlay` border stroke（L364-367 `skin.palette.cardBorder`）**，兩者都要搬進來，否則 podcast 列表掉邊框。

- [ ] **Step 1:** 泛型容器（含 border）：
```swift
struct ListSectionCard<Content: View>: View {
    @Environment(\.appSkin) private var skin
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 0) { content }
            .padding(.vertical, skin.spacing.microGap)
            .background(RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous).fill(skin.palette.cardBackground))
            .overlay(RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous).stroke(skin.palette.cardBorder, lineWidth: 1))
    }
}
```
（實作前對照 podcast L364-367 確認 stroke 顏色/寬度，照搬。）
（divider 由 caller 在 ForEach 內插，與兩處現況一致——不強塞進容器避免改變語意。）

- [ ] **Step 2:** `ios_build.sh` exit 0。

- [ ] **Step 3: Commit** `ios: extract ListSectionCard shared list container`

> vocab `VocabListCard` 遷移至 `ListSectionCard` = **獨立後續 task**（D7，限制 blast radius），不在本 plan。

---

### Task 5: 接線 — 集數列表注入 router + regular 改 select、套 presentation、用 ListSectionCard

**Files:**
- Modify: `ios/BooksAndVocab/Views/Podcast/PodcastEpisodeListView.swift`（struct L37、episodesSection L334-363、body 外層）

- [ ] **Step 1:** struct 內加：
```swift
@Environment(\.horizontalSizeClass) private var sizeClass
@State private var detailRouter = PodcastDetailRouter()
private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }
```

- [ ] **Step 2:** episodesSection 的 ForEach row 依 layoutMode 分支：
  - **regular**：改 `Button { detailRouter.show(episodeRemoteId: episode.remoteId); warmConnection(for: episode) }`，並**保留** `.disabled(!episode.audioAvailable)`（無音訊集數不可選；`navigationLocked` 為 push-only 故 regular 可省）。row 加選中高亮（`episode.remoteId == detailRouter.selectedEpisodeRemoteId` → 鏡射 `KGVocabRow` 選中態 `skin.palette.selectionBackground`）。
  - **compact**：維持現有 `NavigationLink(value: PodcastNavRoute.episode(...))` + `.disabled(!episode.audioAvailable || navigationLocked)` + `.simultaneousGesture`（L336-350 不動）。
  - 容器 `VStack(spacing:0){...}.background(...).overlay(...)`（L334-367）改為 `ListSectionCard { ... }`。

- [ ] **Step 3:** body 最外層（ScrollView/VocabSceneShell 之後）套 `.podcastDetailPresentation(router: detailRouter, layoutMode: layoutMode)`，並 `.environment(\.podcastDetailRouter, detailRouter)`。

- [ ] **Step 4:** `ios_build.sh` exit 0 + `i18n_lint.sh` 0 + `catalyst_lint.sh --strict` 0。

- [ ] **Step 5: 實機驗證**（使用者）：
  - Catalyst：點集數 → 右欄載入 player → 點另一集即時換集（無 ducking/閃爍）→ 拖拉分隔線 → player 設定彈 sheet 不崩 → 選中 row 高亮。
  - iPhone：點集數仍 push 全螢幕，行為不變。
  - 視窗縮到 compact → 右欄收起、無殘留 selection。

- [ ] **Step 6: Commit** `ios: wire podcast episode list two-column on regular layout`

---

### Task 6: 集數 row 對齊 `WordRow` 視覺契約

**Files:**
- Modify: `ios/BooksAndVocab/Views/Podcast/PodcastEpisodeRow.swift`

對齊 `WordRow` 的 spacing/typography/tone token（standalone 視覺收斂，獨立於雙欄邏輯，故置後）。

- [ ] **Step 1:** 比對 `WordRow.swift` 與 `PodcastEpisodeRow.swift`，將 row 內 spacing 改用 `wordRowHorizontalGap`/`wordRowVerticalGap`/`metadataGap`、標題用 `rowWord`、metadata 用 `monoLabel`、`compactRowVerticalPadding`，使兩 row 視覺一致。保留集數特有元素（Ep 編號、trailing play/完成圖示、ProgressCapsule）。

- [ ] **Step 2:** `ios_build.sh` exit 0 + `i18n_lint.sh` 0。

- [ ] **Step 3: 實機驗證**：集數 row 與單字 row 並排視覺一致。

- [ ] **Step 4: Commit** `ios: align PodcastEpisodeRow visual contract with WordRow`

---

### Task 7: Doc sync

- [ ] 派 background doc-sync agent：更新 `docs/reference/feature_boundary/podcast.md`（雙欄 master-detail + `PodcastDetailRouter`/`PodcastDetailPresentation`）+ `docs/reference/feature_boundary/bookshelf.md`（如集數列表歸此）+ `product_surface.md`（電腦版雙欄播放）。bump verified_against、跑 `docs_lint.sh`。

---

## 完成準則

- 6 個 code commit + 1 doc commit。
- `ios_build.sh` / `i18n_lint.sh` / `catalyst_lint.sh --strict` 全 0。
- 每 task opus code-review PASS。
- 實機 Catalyst 雙欄換集無撕裂、iPhone 行為不變、無殘留 selection。
