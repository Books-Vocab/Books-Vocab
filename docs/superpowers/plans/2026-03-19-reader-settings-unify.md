# ReaderSettings 合併 — glass + vocab variant

Branch: `worktree-reader-settings-unify`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 目標

合併 `ReaderSettingsPanelPresenter`（233 行）和 `ReaderSettingsVocabPresenter`（356 行）為統一的 `ReaderSettingsPresenter(variant: .glass | .vocab)`，消除 ~50% 的重複邏輯。

## 現況分析

兩個 Presenter 共用：
- State struct（fontSizeText, canDecrease/IncreaseFontSize）
- Bindings struct（lineHeight, font, theme, underlineOpacity, showHitTestingDebug, translationPanelMode）
- 5 個 action handlers（onDecreaseFontSize, onIncreaseFontSize, onSelectTheme, onSelectUnderlineOpacity, onDismiss）

差異：
- 容器：Form(.grouped) vs VocabCard+ScrollView
- 主題：@Environment(\.appTheme) vs @Environment(\.vocabSkin)
- Vocab 版額外有 fontToneLabel、themeSwatchColor helper

## Tasks

### Task 1: 建立統一 ReaderSettingsPresenter
- 在 `ios/BooksBrowser/Views/Reader/` 新增 `ReaderSettingsPresenter.swift`
- 定義 `enum ReaderSettingsVariant { case glass, vocab }`
- 統一 State 和 Bindings struct
- body 根據 variant 分派到 `glassLayout` / `vocabLayout`
- 共用 section（typography、appearance、highlight、mode、debug）提取為 private computed properties

### Task 2: 提取 ReaderSettingsHelper
- fontToneLabel、opacityOptions 等共用邏輯放入同一檔案的 private extension

### Task 3: 更新呼叫端
- 找到 ReaderSettingsPanelPresenter 和 ReaderSettingsVocabPresenter 的所有使用點
- 替換為 `ReaderSettingsPresenter(variant: .glass/.vocab, ...)`

### Task 4: 移除舊檔案
- 刪除 `ReaderSettingsPanelPresenter.swift`
- 刪除 `ReaderSettingsVocabPresenter.swift`

### Task 5: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 合併後單一檔案 ≤ 350 行
- 零 UI regression
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPresenter.swift` (NEW)
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPanelPresenter.swift` (DELETE)
- `ios/BooksBrowser/Views/Reader/ReaderSettingsVocabPresenter.swift` (DELETE)
- 呼叫端檔案（需掃描確認）
