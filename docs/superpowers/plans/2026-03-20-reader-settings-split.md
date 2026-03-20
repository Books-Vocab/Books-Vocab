# ReaderSettingsPresenter 拆分

Branch: `worktree-reader-settings-split`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 問題

ReaderSettingsPresenter.swift 493 行，glass 和 vocab 兩種完全不同的佈局塞在同一檔案，耦合過高。

## 設計

拆分為 3 個檔案：
1. `ReaderSettingsPresenter.swift` — 保留 State/Bindings struct + variant dispatch（~80 行）
2. `ReaderSettingsPresenter+Glass.swift` — glass 專用佈局（~200 行）
3. `ReaderSettingsPresenter+Vocab.swift` — vocab 專用佈局（~200 行）

共用的 helper（fontToneLabel、opacityOptions 等）放在主檔案。

## Tasks

### Task 1: 讀取現有檔案
完整讀取 `ios/BooksBrowser/Views/Reader/ReaderSettingsPresenter.swift`，標記：
- State/Bindings struct 的位置
- glassLayout 和 vocabLayout 的起止行
- 共用 helper 的位置
- Preview 的位置

### Task 2: 建立 extension 檔案
- `ReaderSettingsPresenter+Glass.swift`：移入 glassLayout 和所有 glass-only section（glassTypographySection、glassAppearanceSection 等）
- `ReaderSettingsPresenter+Vocab.swift`：移入 vocabLayout 和所有 vocab-only section

### Task 3: 精簡主檔案
主檔案只保留：
- ReaderSettingsVariant enum
- State struct
- Bindings struct
- body（switch variant）
- 共用 helper（fontToneLabel、opacityOptions 等）
- Preview

### Task 4: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 主檔案 ≤ 120 行
- 兩個 extension 各 ≤ 250 行
- 功能完全不變
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPresenter.swift`（精簡）
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPresenter+Glass.swift`（NEW）
- `ios/BooksBrowser/Views/Reader/ReaderSettingsPresenter+Vocab.swift`（NEW）
