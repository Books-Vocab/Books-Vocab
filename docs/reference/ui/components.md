<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/UIComponents/
  - ios/BooksAndVocab/Views/
verified_against: 050f1862
-->
# UI Component & Pattern Inventory

Date: 2026-05-13
Scope: `ios/BooksAndVocab`

文檔網絡：
- 設計規範主文檔：`docs/sop/ui-design.md`
- 開發與編譯入口：`docs/sop/ios.md`
- App 架構脈絡：`docs/sop/architecture.md`
- Vocabulary 範圍對照：`docs/reference/feature_boundary/vocabulary.md`

## 這份文件是幹嘛的

這不是設計理念文件，而是「現況清單」。

用途有三個：
- 查：專案裡已經有哪些可重用元件
- 對：新畫面應該復用哪個 pattern，不要再重做一套
- 補：哪些地方還沒被 design system 完整覆蓋

簡單講：
- `component inventory` = 有哪些 UI 零件
- `pattern inventory` = 這些零件怎麼組成可重複的互動腳本

---

## Component Inventory

### App Shell Layer

主要檔案：
- `ios/BooksAndVocab/ContentView.swift`
- `ios/BooksAndVocab/UIComponents/AppShellComponents.swift`
- `ios/BooksAndVocab/UIComponents/AppSurface.swift`

核心元件：
- `AppSectionCard`
- `AppToolbarGlyph`
- `AppSectionHeader`
- `AppSectionFooter`
- `AppEmptyStateContent`
- `AppEmptyStateCard`
- `AppStateMessageContent`
- `AppStateMessageCard`
- `AppTabSelector`
- `AppSearchField`
- `AppKeyValueRow`
- `AppActionButtonStyle`
- `AppCard`
- `AppTag`
- `AppBanner` — 內嵌狀態橫幅（網路/同步/錯誤），支援 retry + dismiss 按鈕；跨場景持久展示，與 AppStateMessage* 的差異在於 AppBanner 是全畫面頂端固定欄而非 panel 內 transient 訊息
- `AppSheetModifier` — `.appSheet(.large/.medium/.adaptive)` 統一 sheet presentation，取代各畫面散落的 `.sheet` / `.halfSheet` 呼叫
- `AppCompactActionButtonStyle` — inline 小尺寸主行動按鈕（capsule，不撐滿寬度），透過 `.buttonStyle(.appCompactAction(.primary/.neutral/.outline/.destructive))` 套用；取代 4 處 `.borderedProminent.controlSize(.small)`；與 `AppActionButtonStyle`（全寬主按鈕）分工 — banner / card / toolbar 內 inline CTA 用此
- `AppOfflineBanner` — 全 app 持久離線指示；`.appOfflineBanner()` modifier 訂閱 `NetworkMonitor.shared.isConnected`，斷線時頂部插入 24pt 細 banner，進場用 `AnyTransition.bannerReveal` + `AppMotion.emphasizedDecelerate`；現於 `ContentView` 套用一次（**已知 issue：light mode 對比 3.21:1 未達 WCAG AA**）
- `AppSkeletonLine` / `AppSkeletonCard` — Loading 骨架 primitive；`primaryText.opacity(0.06↔0.14)` pulse（`AppMotion.subtleBreath`）；`AppSkeletonCard` 已被 `VocabSceneShell` list 場景採用（1 處），`AppSkeletonLine` 目前僅 def + `AppSkeletonCard` 內部組合 + preview 使用（無外部直接 callsite）；新 loading state 應改用此元件而非自製 placeholder
- `AppSidebarRow` — Catalyst 側邊欄列（`ContentView` `NavigationSplitView` sidebar 用），取代系統 `.listStyle(.sidebar)` 預設樣式（系統半透明材質 + 系統藍選取色與 app Notion 風割裂）。整列可點（`HStack` + `Spacer` 撐滿 + `.contentShape(Rectangle())` 把整矩形納入 hit-test，水平 padding 由元件內 `appSkin` token 控不靠 List inset）；走 appSkin typography/spacing/palette，選取/未選以灰階配色（`secondaryText`→`primaryText`）+ `primaryText.opacity(0.08)` 自繪 `AppRadius.sm` 圓角背景區分（自訂字體 ElmsSans 不響應 `.fontWeight`，故以配色而非字重表達選取）；hover 走既有 `.appHoverRowTint`；a11y icon `accessibilityHidden` + row 掛 `accessibilityLabel` + selected 加 `.isSelected`；selection 由 caller 自管 `@State`，不用 `List(selection:)`

主導航 pattern：
- `ContentView` 以 `AppPrimarySection` 定義全 app 一級資訊架構（DEBUG：書庫 → 播客 → 單字本 → 總覽；Release：無播客——`AppPrimarySection.visibleCases(podcastEnabled:)` 依 `KGFeatureFlags.podcastEnabled` 過濾，見 `tech_index.md`）。iPhone / iPad 保留 `TabView`；Mac Catalyst 走 `NavigationSplitView` + `.sidebar` list，將主區切換移到左側側欄，避免桌面版沿用手機底部分頁。Catalyst 不用 `List(selection:)`（iOS SDK availability unavailable），改以 sidebar `AppSidebarRow`（見上）+ `selectedSection` 狀態維持選取背景。

#### Toast 子系統

主要檔案：
- `ios/BooksAndVocab/UIComponents/AppToast.swift`
- `ios/BooksAndVocab/UIComponents/AppToastCoordinator.swift`
- `ios/BooksAndVocab/UIComponents/View+ToastSheet.swift`
- `ios/BooksAndVocab/Services/ModelContext+SafeSave.swift`

核心元件：
- `AppToast` — capsule 形狀 toast UI，支援 swipe dismiss
- `AppToastCoordinator` — toast 管理器 + `AppToastItem` 資料模型（style: success/info/warning/error）
- `toastSheet` — 自動在 sheet 內注入 `toastOverlay()` 的 view modifier
- `toastFullScreenCover` — 同上，用於 fullScreenCover
- `safeSaveWithToast()` — `ModelContext` 安全存檔 + toast 回饋

責任：
- app-wide card / empty state / message / tab / search / row / action chrome / banner / sheet presentation / toast notification

不該做的事：
- feature-specific 視覺語言不應直接塞回這層

### Vocabulary Skin Layer

主要檔案：
- `ios/BooksAndVocab/Models/AppSkin.swift`（前身 `Skin/VocabSkin.swift`，已升格為全 app 共用）
- `ios/BooksAndVocab/Views/Vocabulary/Components/VocabComponents.swift`（前身 `VocabSkinComponents.swift`）
- `ios/BooksAndVocab/Views/Vocabulary/Components/VocabShellComponents.swift`

核心元件：
- `VocabCard`
- `VocabToneChip`
- `VocabTierLabel`
- `VocabEmptyStateContent`
- `VocabEmptyStateCard`
- `VocabStateMessageCard`
- `VocabTabSelector`
- `VocabSearchField`
- `VocabToolbarGlyph`
- `VocabChromeIconButton`
- `VocabOverlayHeader`
- `VocabInlineActionButton`
- `VocabSectionHeader`
- `VocabSliderRow`
- `VocabMetricHeroCard`
- `VocabListCard`
- `VocabStatusHero`
- `VocabTimelineRow`
- `VocabActionButtonStyle`
- `VocabSceneShell` — 四態容器（loading/empty/error/content），統一 Vocabulary 場景的狀態管理殼層；各 VocabPresenter 優先透過此殼層組合狀態而非各自手拼
- `GraphThumbnailWebView` — `UIViewRepresentable` 小型圖譜預覽（iOS / Catalyst 共用，無原生 macOS `NSViewRepresentable` 分支），用於 StatsPresenter
- `NotebookStackedCoverView` — Editorial 立體堆卡（**目前由 Bookshelf / Podcast / EditSheet preview 使用,NotebookCard book-row 不再用**）：彩色封面 + cream 紙頁三階 ghost（`paperLight/paperSepia/paperSepiaDeep`）；幾何走 `NotebookStackMetrics`（dy/dx=4pt / rotation ±1.5° / jitter ±1pt / rotationOverhang 8pt / `patternOpacity` 0.12）；每層 0.5pt `cardBorder` hairline；rotation 由 `stableSeed(for:)` djb2 hash 保證跨 launch 同字串同角度；下層 ghost `.appElevation(.z1)`、頂層 `.z2`；按壓走 `NotebookDeckButtonStyle`（press-in `TapFeedback.animation` + release `AppMotion.cardDeckRelease` + haptic `.selection`），Reduce Motion 關 offset/scale 但 **保留 rotation**（靜態 layout 非 motion）；`showsName: Bool = true` opt-in 開關
- `EditorialCoverComposition`(private in `NotebookCard.swift`) — **live**：D1 editorial cover overlay，由 `coverArea` 以 `.overlay` 套在 cover view 之上（grid + hero 兩 style 皆套），跟外層 `rotationEffect` 一起旋轉。內容:serif name 左上(grid 22pt / hero 32pt)+ hairline rule(cover 寬 ×0.25)+ `N 詞` 右下(cardCount > 0)+ 3pt spine(grid && isActive)。cover view 以 `showsName: false` 把 name 渲染交給此 overlay。
- `VocabReviewCTAPill` — 用於 detail 頁(KGVocabPresenter)與 **NotebookListView 頂部 section header**(D4 editorial),brandHero 奶黃 capsule + onBrandHero 前景。Both 同視覺族群,page-level 標題不需卡片框包裹。
- `VocabReviewBanner` — **(已從 NotebookListView 解除引用)** 元件保留於 codebase 作 future use / preview;NotebookListView 現走 page section header `今日複習` + `VocabReviewCTAPill` 取代。

責任：
- vocabulary feature 的 card rhythm、toolbar chrome、status hero、overlay shell、timeline row、四態場景殼層、graph thumbnail

### Reader Layer

主要檔案：
- `ios/BooksAndVocab/Views/Reader/ReaderContentStyle.swift`
- `ios/BooksAndVocab/Views/Reader/TranslationPanel.swift`
- `ios/BooksAndVocab/Views/Reader/TranslationPanelPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/TranslationVocabPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/ReaderSettingsPanel.swift`
- `ios/BooksAndVocab/Views/Reader/VocabHighlightColorPresetPicker.swift`
- `ios/BooksAndVocab/Views/Reader/ReaderSettingsPanelPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/ReaderSettingsVocabPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/ReaderViewPresenter.swift`

核心元件 / 容器：
- `TranslationPanel`
- `TranslationPanelPresenter`
- `TranslationVocabPresenter`
- `ReaderSettingsPanel`
- `ReaderSettingsPanelPresenter`
- `ReaderSettingsVocabPresenter`
- `ReaderViewPresenter`
- `ReaderSettingsPresenter` — 閱讀器設定的頂層 presenter（vocab 單一模式，glass 分支已移除）
- `VocabHighlightColorPresetPicker` — Reader / Podcast 共用詞庫 highlight 顏色 swatch picker，採 `ReaderSelectionTile` 與 `VocabHighlightColorPreset` 色票
- `PDFReaderView` — PDF 格式閱讀器（iOS only）

責任：
- reader loading / overlay / header / translation / settings panel
- reader / podcast 共用 highlight 顏色入口
- PDF reader 獨立路徑
- 整層以 `#if os(iOS)` 隔離 —— Catalyst 下 `os(iOS)` 為 true 仍編譯仍啟用

目前狀態：
- motion 已大幅收斂
- state presentation 已透過 shared state message 語法統一
- glass 分支已完全移除，僅保留 vocab 模式

### Settings Layer

主要檔案：
- `ios/BooksAndVocab/Views/Settings/SettingsPresenter.swift`
- `ios/BooksAndVocab/Views/Settings/SettingsPresentation.swift`

核心元件：
- `SettingsSectionHeader`
- `SettingsSectionFooter`
- `SettingsDivider`
- `SettingsSocialBadge`
- `SettingsAuthButton`
- `SettingsAuthSummary`
- `SettingsRow`
- `SettingsCardModifier`
- `SettingsButtonChromeModifier`

責任：
- settings-only row layout 與 auth/subscription/info section composition

目前狀態：
- 已接入 shared motion
- 狀態訊息開始接入 shared state card 語法

### Models / Tokens Layer

主要檔案：
- `ios/BooksAndVocab/Networking/RetryPolicy.swift`
- `ios/BooksAndVocab/Models/AppMetrics.swift` — AppMetrics / AppSpacing / AppRadius / AppElevation / AppMotion / ElevationDirection（無 AppLayout — readable-width 由 `WordDetailPresenter` local `maxContentWidth=640` 控）
- `ios/BooksAndVocab/Models/AppFonts.swift` — AppFonts.serif/sans/mono + TypeScale(caption2/caption/subhead/body/h2/h1/hero) + Tracking + LineSpacing
- `ios/BooksAndVocab/Models/AppColors.swift` — semantic palette tokens（含 brandHero light/dark）
- `ios/BooksAndVocab/Models/AppTheme.swift` — `@Environment(\.appTheme)` 注入點，Palette/Typography 三組（light/dark/highContrast）

核心元件 / token：
- `RetryPolicy` — 網路重試策略，實作指數退避（exponential backoff）+ Retry-After header 解析；所有 authenticated request 統一使用，不各自硬編 retry 邏輯
- `AppSpacing` — 8pt grid 語意 token（s0–s7 + `cardOuterPadding/innerGap/sectionGap`），取代 raw padding magic number
- `AppRadius` — 4 主階圓角（`xs/sm/md/lg`）+ `pill`，禁用鄰近半階值
- `AppElevation` — z0–z4 shadow token + `.appElevation(.zN)` modifier；dark mode 自動加強 opacity（**live：~24 callsites**，全 app shadow 唯一入口 — AppSurface / AppToast / Card / cover / overlay 等）
- `AppMotion` — 動畫語意層 token（`emphasizedDecelerate/Accelerate`、`subtleBreath`、`panelState`、`feedbackPulse`、`phaseChange`、`shimmer`、`TapFeedback` triplet）
- Animation convenience methods — `View.animatePhaseChange()`、`View.animateFeedback()` 等擴充，將常用 `withAnimation` 組合收斂為語意化呼叫
- `AppFonts.hero(weight:)` / `TypeScale.hero` — 40pt serif hero typography（`TypeScale` 階梯：`caption2/caption/subhead/body/h2/h1/hero`，無 display1/2）
- `AppColors.brandHero(_:scheme)` + `AppTheme.palette.accentHero/accentSubtle/successBg/warningBg/infoBg/destructiveBg/borderStrong` — 品牌 hero + 狀態 bg 色彩 token

責任：
- 跨層共用的網路策略 model
- 動畫呼叫語法糖，確保 motion token 使用一致

不該做的事：
- 不應在此層持有任何 SwiftUI View 或 `@State`

---

### Interaction — Hover / Pointer Layer

主要檔案：
- `ios/BooksAndVocab/UIComponents/HoverHighlight.swift` — 指標 hover 回饋 modifier
- `ios/BooksAndVocab/Platform/MacColumnResizeCursor.swift` — Catalyst 欄寬游標（`UIPointerInteraction`）

核心元件：
- `.appHoverLift(scale:)` — 卡片 hover 輕微 scale 浮起（預設 1.02）；卡片屬按鈕互動故 scale 合 Motion Contract，已 gate `accessibilityReduceMotion`。套用：`BookCard` / `PodcastSeriesCard` / `NotebookCard`。
- `.appHoverRowTint(cornerRadius:)` — 扁平可點 list-row hover bg tint（`primaryText.opacity(0.05)`，只動 background）。套用：`SettingsNavigationRow` / `SettingsCardNavigationRow` / `syncSummaryRow`。卡片型可點走 lift / `.liftable`，不重複 tint。
- `MacColumnResizeCursor`（**Catalyst-only**）— `UIViewRepresentable` 包 `UIPointerInteraction` + `UIPointerStyle(shape: .verticalBeam(length:))`，疊到 `DraggableDivider`；`PassthroughPointerView` 對 `event.type == .touches` 的 hitTest 回 nil 讓拖曳/雙擊穿透，hover 才回 self，故游標與既有 `dragGesture` 並存。

責任 / 邊界：
- `.onHover` 在純觸控 iPhone 無指標事件自動 no-op，iPad 觸控板 + Mac 共益 → hover modifier **不**包 `#if`；唯欄寬游標走 `UIPointerInteraction` 故 `#if targetEnvironment(macCatalyst)`。

---

## Pattern Inventory

### 1. Empty State Pattern

用途：
- 尚未登入
- 沒有資料
- 搜尋無結果
- 任務完成後無下一步

優先元件：
- `AppEmptyStateContent`
- `AppEmptyStateCard`
- `VocabEmptyStateContent`
- `VocabEmptyStateCard`

代表畫面：
- `BookshelfView`
- `KGVocabView`
- `KnowledgeGraphPresenter`
- `TodayReviewPresenter`

規則：
- title + icon + description 為最小組
- feature 版面優先用 feature wrapper，不直接手拼 icon/text

### 2. State Message Pattern

用途：
- loading
- transient success
- inline warning
- recoverable error
- status + timer

優先元件：
- `AppStateMessageContent`
- `AppStateMessageCard`
- `VocabStateMessageCard`

代表畫面：
- `TranslationPanelPresenter`
- `TranslationVocabPresenter`
- `KGVocabView`
- `SettingsPresenter` paywall 狀態區

規則：
- 若狀態在 panel 內，優先用 `Content`
- 若狀態本身就是一個獨立區塊，優先用 `Card`

### 3. Hero Status Pattern

用途：
- sync ready / running / failed / completed
- login required
- pro required
- graph empty / loading / failed

優先元件：
- `VocabStatusHero`

代表畫面：
- `SyncPresenter`
- `KnowledgeGraphPresenter`

規則：
- 用於大狀態切換
- 不要拿來做小型 inline message

### 4. List Shell Pattern

用途：
- filter / tab / count / row list / divider

優先元件：
- `ListSectionCard`（`ios/BooksAndVocab/UIComponents/ListSectionCard.swift`）— 扁平列表共用卡片容器（`VStack(spacing:0)` + `cardBackground` fill + `cardBorder` stroke + `clipShape` 圓角讓 per-row 選中底色不溢出）。podcast 集數列表與單字列表共同骨架；divider 由 caller 在 `ForEach` 內插（不塞進容器，保語意）
- `VocabListCard`
- `VocabTabSelector`
- `VocabSearchField`
- `WordRow`

代表畫面：
- `KGVocabPresenter`
- `PendingVocabPresenter`
- `VocabularyListPresenter`
- `PodcastEpisodeListView`

規則：
- tab + header + list content 優先收斂到同一殼層
- 扁平 row list 的卡片容器收斂到 `ListSectionCard`

### 5. Overlay / Panel Pattern

用途：
- translation panel
- reader settings
- graph settings
- linked card overlay

優先元件 / token：
- `TranslationPanel`
- `ReaderSettingsPanel`
- `VocabOverlayHeader`
- `AppMotion.panelState`
- `AnyTransition.readerPanelReveal`
- `AnyTransition.overlayFade`

代表畫面：
- `ReaderView`
- `KnowledgeGraphPresenter`
- `LinkedCardOverlayStack`

規則：
- panel 開合用 `panelState`
- 底部浮層進出用 `readerPanelReveal`
- scrim / 暫時遮罩用 `overlayFade`

### 6. Feedback Pattern

用途：
- save success
- review remembered / forgot
- sync numeric progress
- badge confirmation

優先 token：
- `AppMotion.feedbackPulse`
- `AnyTransition.feedbackBadge`

代表畫面：
- `TranslationPanelPresenter`
- `TranslationVocabPresenter`
- `SyncPresenter`
- `TodayReviewPresenter`

規則：
- feedback 必須有語意，不只是一個 bounce
- 成功 feedback 應優先搭配 haptic

### 7. Phase Transition Pattern

用途：
- sync lifecycle
- auth logged in/out swap
- settings status swap

優先 token：
- `AppMotion.phaseChange`
- `AnyTransition.modalSwap`
- `AnyTransition.statusRowReveal`

代表畫面：
- `SyncPresenter`
- `SettingsPresenter`

規則：
- phase 與 row reveal 要分開，不能混用同一動畫

---

## Current Gaps

### Gap 1: Settings 還是偏 feature-local

現況：
- Settings 有自己的 row / button / card composition
- 已經接近 pattern 化，但還沒有再往 shared shell 回收

影響：
- 可用，但長期容易維持兩套語言

### Gap 2: Raw spacing magic numbers 大量存在

現況：
- Color / Font / Animation token 覆蓋率良好
- `AppSpacing` 8pt grid 已建立，但採用率低 — ReaderSettings、TranslationVocab、StatsPresenter 仍大量 raw 數字
- 新增 UI 須優先採用 `AppSpacing.sN`

影響：
- spacing 不一致，難以全局調整

### Gap 3: 28 個 View 缺少 #Preview

現況：
- 核心場景（KGVocab、Bookshelf、TodayReview、Settings）有 Preview
- 但 AddLinkSheet、WordDetailPresenter、StatsPresenter、NotebookListView 等 28 個 View 缺少

影響：
- 開發時無法快速預覽，UI 變更驗證效率低

### Gap 4: 低採用率 design system surface

現況：
- `AppSkeletonLine` 目前無外部直接 callsite（僅 def + `AppSkeletonCard` 內部 + preview）；`AppSkeletonCard` 已被 `VocabSceneShell` 採用（1 處）
- `AppElevation` 已是全 app shadow 唯一入口（~24 callsites）；`AppCompactActionButtonStyle`（4 處）、`AppOfflineBanner`（ContentView 1 處）、`AppMotion.emphasizedDecelerate`（AppOfflineBanner 內部）皆已落地
- PR #402 曾規劃的 `AppLayout` / `AppFonts.display1/2` token **從未進入 codebase**（doc 舊版誤記為已定義）；readable-width 實際由 `WordDetailPresenter` local `maxContentWidth=640` 控

影響：
- 仍有 primitive（如 `AppSkeletonLine`）採用率低，token 漂移風險 — 安排 callsite migration 鎖定語意

### Gap 5: 已知對比缺陷

現況：
- `AppOfflineBanner` light mode 對比 ≈ 3.21:1（destructiveLight 12pt semibold on 10% destructiveLight bg），**fail WCAG AA 4.5:1**
- ~~`accentHero` dark mode 4.02:1~~ — 已解除：Phase 1b 起 brandHero 從 Morandi 藍改奶黃 `#B5894B/#C9A968`，前景採 `onBrandHero` deep charcoal `#1C1A17`，light/dark 對比 5.11/7.05:1 ✓ AA/AAA（BooksAndVocabTests/WCAGContrastTests.swift 鎖住）
- ~~`AppCompactActionButtonStyle` primary foreground raw `.white`~~ — 已解除：改走 `AppColors.onBrandHero`；奶黃 + 白字 fail AA → onBrandHero 強制 deep charcoal 是 token-level 保證

影響：
- 視覺品牌一致性 + a11y 合規邊界；polish pass PR 處理

---

## Reuse Order

新增 UI 時，優先順序如下：

1. 先看有沒有現成 pattern
2. 再選對應 component
3. 最後才補 token
4. 真的沒有才新增新元件

簡單決策：
- 是空狀態？先看 `AppEmptyState*` / `VocabEmptyState*`
- 是 loading / success / error 訊息？先看 `AppStateMessage*` / `VocabStateMessageCard`
- 是大狀態切換？先看 `VocabStatusHero`
- 是 list + tabs + search？先看 `VocabListCard` + `VocabTabSelector` + `VocabSearchField`
- 是 panel / drawer / overlay？先看 `TranslationPanel` / `ReaderSettingsPanel` / `VocabOverlayHeader` + motion tokens
- 是 inline 小型主 CTA？先看 `.buttonStyle(.appCompactAction(...))`，不直接 `.borderedProminent`
- 是 loading list / card？先看 `AppSkeletonLine` / `AppSkeletonCard`（`AppSkeletonCard` 已用於 `VocabSceneShell`）
- 是離線 / 網路狀態提示？root 層套 `.appOfflineBanner()`；transient 錯誤仍用 `AppBanner` / `AppStateMessage*`
- raw `.shadow(...)`？改用 `.appElevation(.zN)`
- raw spacing 數字？改用 `AppSpacing.sN`

---

## Next Recommended Step

State matrix 與 preview matrix 已建立（見 `ui_state_matrix.md`）。
新增或修改 UI 前，先跑一遍 `ui_review_checklist.md`。
