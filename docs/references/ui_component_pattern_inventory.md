# UI Component & Pattern Inventory

Date: 2026-03-09
Scope: `booksbrowser_ios/BooksBrowser`

文檔網絡：
- 設計規範主文檔：`docs/ui-design.md`
- 開發與編譯入口：`docs/ios-dev.md`
- App 架構脈絡：`docs/architecture.md`
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
- `booksbrowser_ios/BooksBrowser/UIComponents/AppShellComponents.swift`
- `booksbrowser_ios/BooksBrowser/UIComponents/AppSurface.swift`
- `booksbrowser_ios/BooksBrowser/UIComponents/MorandiButtonStyle.swift`

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

責任：
- app-wide card / empty state / message / tab / search / row / action chrome

不該做的事：
- feature-specific 視覺語言不應直接塞回這層

### Vocabulary Skin Layer

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Skin/VocabSkin.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents.swift`

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

責任：
- vocabulary feature 的 card rhythm、toolbar chrome、status hero、overlay shell、timeline row

### Reader Layer

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderContentStyle.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/TranslationPanel.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/TranslationPanelPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/TranslationVocabPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderSettingsPanel.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderSettingsPanelPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderSettingsVocabPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderViewPresenter.swift`

核心元件 / 容器：
- `TranslationPanel`
- `TranslationPanelPresenter`
- `TranslationVocabPresenter`
- `ReaderSettingsPanel`
- `ReaderSettingsPanelPresenter`
- `ReaderSettingsVocabPresenter`
- `ReaderViewPresenter`

責任：
- reader glass / vocab 兩條 visual branch
- reader loading / overlay / header / translation / settings panel

目前狀態：
- motion 已大幅收斂
- state presentation 已開始透過 shared state message 語法統一

### Settings Layer

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Settings/SettingsPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Settings/SettingsPresentation.swift`

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

### Gap 2: Reader 仍有 glass / vocab 雙 presenter 分支

現況：
- 視覺語言一致度已提高
- 但 presenter 結構仍是雙分支

影響：
- 重用仍高於完全手刻
- 但維護成本仍高於單一 state shell

### Gap 3: Top-level state matrix 仍未成文

現況：
- state message component 已開始形成
- 但每個畫面有哪些狀態還沒做 matrix

影響：
- 未來新增功能時，還是可能漏掉 empty / retry / partial failure

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

最值得接著做的是：

1. 補 state matrix
2. 補 preview matrix

因為 component / pattern inventory 解決的是「該用什麼」。
下一步 state / preview matrix 解決的是「有哪些狀態不能漏」。
