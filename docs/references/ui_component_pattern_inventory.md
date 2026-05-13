<!-- doc-meta
tier: reference
scope:
  - ios/BooksBrowser/UIComponents
  - ios/BooksBrowser/Views
verified_against: c16321f
-->
# UI Component & Pattern Inventory

Date: 2026-05-13
Scope: `ios/BooksBrowser`

文檔網絡：
- 設計規範主文檔：`docs/dev/ui-design.md`
- 開發與編譯入口：`docs/dev/ios-dev.md`
- App 架構脈絡：`docs/dev/architecture.md`
- Vocabulary 稽核：`docs/references/vocab_design_system_audit.md`

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
- `ios/BooksBrowser/UIComponents/AppShellComponents.swift`
- `ios/BooksBrowser/UIComponents/AppSurface.swift`
- `ios/BooksBrowser/UIComponents/MorandiButtonStyle.swift`

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
- `AppSkeletonLine` / `AppSkeletonCard` — Loading 骨架 primitive；`primaryText.opacity(0.06↔0.14)` pulse（`AppMotion.subtleBreath`）；**目前 zero callsites，dormant**；新 loading state 應改用此元件而非自製 placeholder

#### Toast 子系統

主要檔案：
- `ios/BooksBrowser/UIComponents/AppToast.swift`
- `ios/BooksBrowser/UIComponents/AppToastCoordinator.swift`
- `ios/BooksBrowser/UIComponents/View+ToastSheet.swift`
- `ios/BooksBrowser/Services/ModelContext+SafeSave.swift`

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
- `ios/BooksBrowser/Views/Vocabulary/Skin/VocabSkin.swift`
- `ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift`
- `ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents.swift`

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
- `GraphThumbnailWebView` — 雙平台（iOS `UIViewRepresentable` / macOS `NSViewRepresentable`）小型圖譜預覽，用於 StatsPresenter

責任：
- vocabulary feature 的 card rhythm、toolbar chrome、status hero、overlay shell、timeline row、四態場景殼層、graph thumbnail

### Reader Layer

主要檔案：
- `ios/BooksBrowser/Views/Reader/ReaderContentStyle.swift`
- `ios/BooksBrowser/Views/Reader/TranslationPanel.swift`
- `ios/BooksBrowser/Views/Reader/TranslationPanelPresenter.swift`
- `ios/BooksBrowser/Views/Reader/TranslationVocabPresenter.swift`
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPanel.swift`
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPanelPresenter.swift`
- `ios/BooksBrowser/Views/Reader/ReaderSettingsVocabPresenter.swift`
- `ios/BooksBrowser/Views/Reader/ReaderViewPresenter.swift`

核心元件 / 容器：
- `TranslationPanel`
- `TranslationPanelPresenter`
- `TranslationVocabPresenter`
- `ReaderSettingsPanel`
- `ReaderSettingsPanelPresenter`
- `ReaderSettingsVocabPresenter`
- `ReaderViewPresenter`
- `ReaderSettingsPresenter` — 閱讀器設定的頂層 presenter（vocab 單一模式，glass 分支已移除）
- `PDFReaderView` — PDF 格式閱讀器（iOS only）

責任：
- reader loading / overlay / header / translation / settings panel
- PDF reader 獨立路徑
- 整層以 `#if os(iOS)` 隔離，macOS 暫不啟用

目前狀態：
- motion 已大幅收斂
- state presentation 已透過 shared state message 語法統一
- glass 分支已完全移除，僅保留 vocab 模式

### Settings Layer

主要檔案：
- `ios/BooksBrowser/Views/Settings/SettingsPresenter.swift`
- `ios/BooksBrowser/Views/Settings/SettingsPresentation.swift`

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
- `ios/BooksBrowser/Networking/RetryPolicy.swift`
- `ios/BooksBrowser/Models/AppMetrics.swift` — AppSpacing / AppRadius / AppElevation / AppLayout / AppMotion / AppShadows / AppTransition / AppShellMetrics / AppBookshelfMetrics
- `ios/BooksBrowser/Models/AppFonts.swift` — AppFonts.body/caption/display1/2 + Tracking + LineSpacing
- `ios/BooksBrowser/Models/AppColors.swift` — semantic palette tokens（含 brandHero light/dark）
- `ios/BooksBrowser/Models/AppTheme.swift` — `@Environment(\.appTheme)` 注入點，Palette/Typography 三組（light/dark/highContrast）

核心元件 / token：
- `RetryPolicy` — 網路重試策略，實作指數退避（exponential backoff）+ Retry-After header 解析；所有 authenticated request 統一使用，不各自硬編 retry 邏輯
- `AppSpacing` — 8pt grid 語意 token（s0–s7 + `cardOuterPadding/innerGap/sectionGap`），取代 raw padding magic number
- `AppRadius` — 4 主階圓角（`xs/sm/md/lg`）+ `pill`，禁用鄰近半階值
- `AppElevation` — z0–z4 shadow token + `.appElevation(.zN)` modifier；dark mode 自動加強 opacity（**dormant：zero callsites**）
- `AppLayout` — `maxReadableWidth/maxContentWidth` + `.appReadableFrame()` modifier（**dormant：zero callsites**）
- `AppMotion` — 動畫語意層 token（`emphasizedDecelerate/Accelerate`、`subtleBreath`、`panelState`、`feedbackPulse`、`phaseChange`、`shimmer`、`TapFeedback` triplet）
- Animation convenience methods — `View.animatePhaseChange()`、`View.animateFeedback()` 等擴充，將常用 `withAnimation` 組合收斂為語意化呼叫
- `AppFonts.display1/display2` — 56/48pt serif hero typography（**dormant：zero callsites**）
- `AppColors.brandHero(_:scheme)` + `AppTheme.palette.accentHero/accentSubtle/successBg/warningBg/infoBg/destructiveBg/borderStrong` — 品牌 hero + 狀態 bg 色彩 token

責任：
- 跨層共用的網路策略 model
- 動畫呼叫語法糖，確保 motion token 使用一致

不該做的事：
- 不應在此層持有任何 SwiftUI View 或 `@State`

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
- `VocabListCard`
- `VocabTabSelector`
- `VocabSearchField`
- `WordRow`

代表畫面：
- `KGVocabPresenter`
- `PendingVocabPresenter`
- `VocabularyListPresenter`

規則：
- tab + header + list content 優先收斂到同一殼層

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

### Gap 4: Dormant design system surface

現況：
- `AppSkeletonLine/Card`、`AppFonts.display1/2`、`.appReadableFrame()`、`.appElevation()` token 已定義但 zero callsites（約 60% PR #402 新 surface）
- 已有 callsite 的：`AppCompactActionButtonStyle`（4 處）、`AppOfflineBanner`（ContentView 1 處）、`AppMotion.emphasizedDecelerate`（AppOfflineBanner 內部）

影響：
- token 漂移風險 — 定義與消費者語意可能脫節；安排 callsite migration 鎖定語意

### Gap 5: 已知對比缺陷

現況：
- `AppOfflineBanner` light mode 對比 ≈ 3.21:1（destructiveLight 12pt semibold on 10% destructiveLight bg），**fail WCAG AA 4.5:1**
- `accentHero` dark mode (`brandHeroDark`) 配 white text 4.02:1，目前僅 `AppCompactActionButtonStyle.primary` 內部 guard（改用 `brandHeroLight`）
- `AppCompactActionButtonStyle` primary foreground 使用 raw `.white`（應替換為待新增 `onBrandHero` token）

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
- 是 loading list / card？先看 `AppSkeletonLine` / `AppSkeletonCard`（dormant 但已備齊）
- 是離線 / 網路狀態提示？root 層套 `.appOfflineBanner()`；transient 錯誤仍用 `AppBanner` / `AppStateMessage*`
- raw `.shadow(...)`？改用 `.appElevation(.zN)`
- raw spacing 數字？改用 `AppSpacing.sN`

---

## Next Recommended Step

State matrix 與 preview matrix 已建立（見 `ui_state_matrix.md`）。
新增或修改 UI 前，先跑一遍 `ui_review_checklist.md`。
