<!-- doc-meta
tier: reference
scope:
  - ios/BooksBrowser/UIComponents
  - ios/BooksBrowser/Views
verified_against: 05acfbf
-->
# UI Component & Pattern Inventory

Date: 2026-04-01
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
- `ios/BooksBrowser/UIComponents/AppMotion.swift`

核心元件 / token：
- `RetryPolicy` — 網路重試策略，實作指數退避（exponential backoff）+ Retry-After header 解析；所有 authenticated request 統一使用，不各自硬編 retry 邏輯
- Animation convenience methods — `View.animatePhaseChange()`、`View.animateFeedback()` 等擴充，將常用 `withAnimation` 組合收斂為語意化呼叫

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
- 但 spacing / padding 仍有 200+ 處直接使用數字
- 主要集中在 UIComponents、ReaderSettings、TranslationVocab、StatsPresenter

影響：
- spacing 不一致，難以全局調整

### Gap 3: 28 個 View 缺少 #Preview

現況：
- 核心場景（KGVocab、Bookshelf、TodayReview、Settings）有 Preview
- 但 AddLinkSheet、WordDetailPresenter、StatsPresenter、NotebookListView 等 28 個 View 缺少

影響：
- 開發時無法快速預覽，UI 變更驗證效率低

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

---

## Next Recommended Step

State matrix 與 preview matrix 已建立（見 `ui_state_matrix.md`）。
新增或修改 UI 前，先跑一遍 `ui_review_checklist.md`。
