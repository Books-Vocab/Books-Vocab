# SettingsRow 內聯移除

Branch: `worktree-settings-row-inline`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 目標

移除冗餘的 `SettingsRow` 包裝層，直接使用 `AppKeyValueRow(style: .settings(vocabSkin))`。

## 現況

`SettingsRow`（定義於 `SettingsPresenter+Components.swift` 第 43-64 行）是 `AppKeyValueRow` 的純透傳包裝，零額外邏輯：

```swift
struct SettingsRow<Content: View>: View {
    var body: some View {
        AppKeyValueRow(icon: icon, label: label, style: .settings(vocabSkin)) {
            content
        }
    }
}
```

## Tasks

### Task 1: 掃描所有 SettingsRow 使用點
- 搜尋 `SettingsRow(` 出現的所有檔案和行號

### Task 2: 批量替換
- 將每個 `SettingsRow(icon:label:) { content }` 替換為 `AppKeyValueRow(icon:label:style:.settings(vocabSkin)) { content }`

### Task 3: 移除 SettingsRow 定義
- 從 `SettingsPresenter+Components.swift` 刪除 SettingsRow struct

### Task 4: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- SettingsRow 完全移除
- 所有呼叫端改用 AppKeyValueRow
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Views/Settings/SettingsPresenter+Components.swift`
- 10+ 個 Settings 相關檔案
