# Animation Convenience Modifiers

Branch: `worktree-animation-convenience`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 目標

在 `AppMetrics.swift` 的 AppMotion 區塊新增 View extension convenience methods，替換 28 個檔案 60+ 處的 `.animation(AppMotion.xxx, value:)` 重複呼叫。

## 設計

```swift
extension View {
    func animatePhaseChange<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.phaseChange, value: value)
    }
    func animateSpring<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.standardSpring, value: value)
    }
    func animateContentFade<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.contentFade, value: value)
    }
    func animateControl<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.controlEaseOut, value: value)
    }
}
```

## Tasks

### Task 1: 新增 convenience extension
- 在 `ios/BooksBrowser/Models/AppMetrics.swift` 底部新增上述 extension

### Task 2: 批量替換 phaseChange（~18 處）
- 搜尋 `.animation(AppMotion.phaseChange,` 並替換為 `.animatePhaseChange(`
- 注意保留 `value:` 參數值

### Task 3: 批量替換 standardSpring（~10 處）
- `.animation(AppMotion.standardSpring,` → `.animateSpring(`

### Task 4: 批量替換 contentFade（~7 處）
- `.animation(AppMotion.contentFade,` → `.animateContentFade(`

### Task 5: 批量替換 controlEaseOut（~4 處）
- `.animation(AppMotion.controlEaseOut,` → `.animateControl(`

### Task 6: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 所有 `.animation(AppMotion.xxx, value:)` 替換為 convenience method
- 編譯通過
- AppMotion 原始 token 不變，只是新增 sugar

## Files Modified
- `ios/BooksBrowser/Models/AppMetrics.swift`
- 28 個使用端檔案（批量搜尋替換）
