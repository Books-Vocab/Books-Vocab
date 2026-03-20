# AppBanner 統一 — 3 banners → 1

Branch: `worktree-banner-unify`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 目標

合併 `ErrorBannerView`、`SyncErrorBanner`、`OfflineBanner` 為統一的 `AppBanner` 元件。

## 現況

| 元件 | 按鈕 | 位置 |
|------|------|------|
| ErrorBannerView | retry + dismiss | Views/Components/ |
| SyncErrorBanner | dismiss only | UIComponents/ |
| OfflineBanner | none | UIComponents/ |

三者結構完全相同：`HStack(icon + text + Spacer + buttons)`，用 `appTheme.palette.warning`、`AppBannerMetrics`、`.transition(.bannerReveal)`。

## Tasks

### Task 1: 建立統一 AppBanner
- 在 `ios/BooksBrowser/UIComponents/AppBanner.swift` 新增
- 參數：`message: String`, `onRetry: (() -> Void)?`, `onDismiss: (() -> Void)?`
- 按鈕根據 closure 是否為 nil 自動顯示/隱藏

### Task 2: 替換所有使用點
- 搜尋 `ErrorBannerView`、`SyncErrorBanner`、`OfflineBanner` 的所有呼叫
- 替換為 `AppBanner(...)`

### Task 3: 移除舊檔案
- 刪除 `Views/Components/ErrorBannerView.swift`
- 刪除 `UIComponents/SyncErrorBanner.swift`
- 刪除 `UIComponents/OfflineBanner.swift`

### Task 4: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 單一 AppBanner 取代 3 個元件
- 編譯通過

## Files Modified
- `ios/BooksBrowser/UIComponents/AppBanner.swift` (NEW)
- `ios/BooksBrowser/Views/Components/ErrorBannerView.swift` (DELETE)
- `ios/BooksBrowser/UIComponents/SyncErrorBanner.swift` (DELETE)
- `ios/BooksBrowser/UIComponents/OfflineBanner.swift` (DELETE)
- 呼叫端檔案
