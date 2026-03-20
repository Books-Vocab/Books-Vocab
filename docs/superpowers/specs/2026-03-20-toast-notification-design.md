# Capsule Toast 通知系統設計

## 問題

App 內瞬態回饋全靠 `sensoryFeedback`（觸覺），缺乏視覺文字提示。使用者無法確認操作結果（「真的複製了嗎？」「同步成功了嗎？」）。現有機制各自為政：

- `AppBanner`：inline layout，只有 warning 樣式，無法跨頁面
- `.alert()`：模態阻斷，用於不需要使用者行動的通知太重
- `sensoryFeedback`：無視覺，靜音模式下完全無回饋

## 設計目標

新增全域 Capsule Toast，作為輕量瞬態通知層，與現有機制形成明確層級：

| 層級 | 元件 | 用途 | 生命週期 |
|------|------|------|----------|
| 阻斷確認 | `.alert()` / `.confirmationDialog()` | 破壞性操作確認（刪除帳號、刪除 notebook） | 使用者手動關閉 |
| 持久狀態 | `AppBanner` | 需要使用者行動的狀態（離線、sync error with retry） | 條件消失時移除 |
| **瞬態通知** | **`AppToast`（新增）** | 操作結果回饋、背景事件通知 | 自動消失 |
| 觸覺 | `sensoryFeedback` | 微互動回饋 | 即時 |

## 變更

### 1. AppToast 元件

**新增** `ios/BooksBrowser/UIComponents/AppToast.swift`

膠囊形 toast，水平置中於頂部 safe area 下方。

```
┌─────────────────────────┐
│  ✓  已複製               │  ← cornerRadiusGlass (30)
└─────────────────────────┘
```

4 種語意樣式，對應 `AppTheme.Palette` 現有 token：

| 樣式 | palette token | icon | 自動消失 | 場景 |
|------|--------------|------|---------|------|
| success | `.success` | checkmark | 2.5s | 已複製、已儲存、同步完成 |
| info | `.accent` | info.circle | 2.5s | 背景同步結果 |
| warning | `.warning` | exclamationmark.triangle | 4s | 部分同步失敗 |
| error | `.destructive` | xmark.circle | 4s | 操作失敗 |

Design tokens：
- 背景：`palette.{token}.opacity(0.12)` + `palette.cardBackground`（混色，確保可讀性）
- 文字：`palette.{token}`（直接用語意色）
- 邊框：`palette.{token}.opacity(0.18)`
- 圓角：`AppMetrics.cornerRadiusGlass`（30）
- 字體：`AppFonts.caption(weight: .semibold)`
- icon：`AppFonts.caption()`
- 陰影：`appTheme.palette.shadow`，radius 8
- 內距：H 18, V 10

### 2. AppToastItem 資料模型

**新增** 於 `AppToast.swift` 內

```swift
struct AppToastItem: Identifiable, Equatable {
    let id = UUID()
    let message: String
    let systemImage: String
    let style: Style

    enum Style { case success, info, warning, error }

    var duration: TimeInterval {
        switch style {
        case .success, .info: 2.5
        case .warning, .error: 4.0
        }
    }
}
```

### 3. AppToastCoordinator

**新增** `ios/BooksBrowser/UIComponents/AppToastCoordinator.swift`

`@Observable` class，透過 `@Environment` 注入全域。

```swift
@Observable @MainActor
final class AppToastCoordinator {
    private(set) var current: AppToastItem?

    func show(_ item: AppToastItem) { ... }       // 設定 current，排程 auto-dismiss
    func dismiss() { ... }                         // 清除 current

    // 便捷方法
    func success(_ message: String) { ... }
    func info(_ message: String) { ... }
    func warning(_ message: String) { ... }
    func error(_ message: String) { ... }
}
```

行為規格：
- 同時只顯示 1 個 toast，新的取代舊的（cancel 前一個 dismiss task）
- Auto-dismiss 使用 `Task.sleep`，cancel-safe
- 上滑手勢 dismiss（`DragGesture` + `AppMotion.swipeDismissSpring`）

### 4. 掛載點

**修改** `ios/BooksBrowser/BooksBrowserApp.swift`

在 `AppThemeContainer` 內最外層 overlay 掛載 toast：

```swift
.overlay(alignment: .top) {
    if let toast = toastCoordinator.current {
        AppToast(item: toast)
            .transition(.move(edge: .top).combined(with: .opacity))
            .onTapGesture { toastCoordinator.dismiss() }
    }
}
.environment(toastCoordinator)
```

### 5. Environment Key

**新增** 於 `AppToastCoordinator.swift`

```swift
private struct AppToastCoordinatorKey: EnvironmentKey {
    static let defaultValue = AppToastCoordinator()
}
extension EnvironmentValues {
    var toastCoordinator: AppToastCoordinator { ... }
}
```

### 6. AppMotion / AnyTransition Token

**修改** `ios/BooksBrowser/Models/AppMetrics.swift`

新增：
- `AppMotion.toastReveal` — `standardSpring`（與 panelState 一致）
- `AnyTransition.toastReveal` — `.move(edge: .top).combined(with: .opacity)`

### 7. 首批接入場景

| 現有機制 | 改為 | 檔案 |
|---------|------|------|
| 複製後 `sensoryFeedback` only | + `toastCoordinator.success("已複製")` | `CardDocumentView.swift`、`CardSections.swift` |
| `NotebookListView` `.alert("刪除失敗")` | `toastCoordinator.error("刪除失敗")` | `NotebookListView.swift` |
| 背景同步無視覺回饋 | `toastCoordinator.info("背景同步完成，新增 N 個單字")` | `BooksBrowserApp.swift` |

**不動的**：
- `AppBanner`（離線 / sync error with retry）— 保留，職責不同
- `.alert()`（刪除帳號確認、登入過期）— 保留，需要使用者行動
- `SyncPresenter` 同步全流程 UI — 保留，是獨立功能頁
- Reader `TranslationPanel` 的 `sensoryFeedback(.success)` — 保留，panel 自身已有儲存狀態視覺指示

## 不做的

- Toast 佇列 / 堆疊顯示 — 過度工程，同時 1 個足夠
- Toast 內 action button — 那是 Snackbar 的職責，與 Capsule 風格衝突
- 取代 AppBanner — 兩者職責不同，共存
- 動態高度 / 多行文字 — 膠囊限制單行，強制訊息精簡
