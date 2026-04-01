# Capsule Toast 通知系統 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增全域 Capsule Toast 元件，為 app 提供輕量瞬態視覺回饋。

**Architecture:** `AppToastCoordinator`（`@Observable @MainActor`）透過 `@Environment` 注入全域。任何 View 呼叫 `toastCoordinator.success("已複製")` 即觸發。Toast 掛載於 `BooksBrowserApp` 最外層 overlay，從頂部滑入，自動消失。

**Tech Stack:** SwiftUI, `@Observable`, `@Environment`, `DragGesture`

**Spec:** `docs/superpowers/specs/2026-03-20-toast-notification-design.md`

**Spec 偏離說明：** 背景同步成功時不彈 toast。Spec 原文列出 `info("背景同步完成，新增 N 個單字")`，但 app 每次前台都觸發同步，頻繁彈 toast 會干擾閱讀。僅在失敗時彈 warning toast。

---

### Task 1: Design System Token

**Files:**
- Modify: `ios/BooksBrowser/Models/AppMetrics.swift` (AppShadows enum)

- [ ] **Step 1: 新增 `AppShadows` toast token**

在 `ios/BooksBrowser/Models/AppMetrics.swift` 的 `AppShadows` enum 尾部新增：

```swift
// MARK: - Toast 微陰影（頂部浮動膠囊）
static let toastOpacity: Double = 0.08
static let toastRadius: CGFloat = 8
static let toastY: CGFloat = 4
```

- [ ] **Step 2: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Models/AppMetrics.swift
git commit -m "ios: add AppShadows toast tokens"
```

---

### Task 2: AppToastItem 資料模型 + AppToastCoordinator

**Files:**
- Create: `ios/BooksBrowser/UIComponents/AppToastCoordinator.swift`

- [ ] **Step 1: 建立 `AppToastItem` 和 `AppToastCoordinator`**

```swift
// ios/BooksBrowser/UIComponents/AppToastCoordinator.swift

import SwiftUI

struct AppToastItem: Identifiable, Equatable {
    let id = UUID()
    let message: String
    let systemImage: String
    let style: Style

    // Equatable 自動合成會比較 id（UUID），因此同訊息的兩次 show 永遠不等。
    // 這是刻意的 — 每次 show 都需要觸發 SwiftUI transition 動畫。

    enum Style {
        case success, info, warning, error

        var defaultImage: String {
            switch self {
            case .success: "checkmark"
            case .info: "info.circle"
            case .warning: "exclamationmark.triangle"
            case .error: "xmark.circle"
            }
        }
    }

    var duration: TimeInterval {
        switch style {
        case .success, .info: 2.5
        case .warning, .error: 4.0
        }
    }

    init(message: String, systemImage: String? = nil, style: Style) {
        self.message = message
        self.systemImage = systemImage ?? style.defaultImage
        self.style = style
    }
}

@Observable @MainActor
final class AppToastCoordinator {
    private(set) var current: AppToastItem?
    private var dismissTask: Task<Void, Never>?

    func show(_ item: AppToastItem) {
        dismissTask?.cancel()
        withAnimation(AppMotion.panelState) {
            current = item
        }
        guard !UIAccessibility.isVoiceOverRunning else { return }
        dismissTask = Task {
            try? await Task.sleep(for: .seconds(item.duration))
            guard !Task.isCancelled else { return }
            dismiss()
        }
    }

    func dismiss() {
        dismissTask?.cancel()
        withAnimation(AppMotion.panelState) {
            current = nil
        }
    }

    func success(_ message: String) {
        show(AppToastItem(message: message, style: .success))
    }

    func info(_ message: String) {
        show(AppToastItem(message: message, style: .info))
    }

    func warning(_ message: String) {
        show(AppToastItem(message: message, style: .warning))
    }

    func error(_ message: String) {
        show(AppToastItem(message: message, style: .error))
    }
}
```

- [ ] **Step 2: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/UIComponents/AppToastCoordinator.swift
git commit -m "ios: add AppToastItem + AppToastCoordinator"
```

---

### Task 3: AppToast View 元件 + Preview

**Files:**
- Create: `ios/BooksBrowser/UIComponents/AppToast.swift`

依賴：Task 1（AppShadows token）、Task 2（AppToastItem）

- [ ] **Step 1: 建立 `AppToast` View**

```swift
// ios/BooksBrowser/UIComponents/AppToast.swift

import SwiftUI

struct AppToast: View {
    @Environment(\.appTheme) private var appTheme
    let item: AppToastItem
    let onDismiss: () -> Void

    @State private var dragOffset: CGFloat = 0

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: item.systemImage)
                .font(AppFonts.caption())
                .foregroundStyle(tintColor)

            Text(item.message.localized)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(tintColor)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            Capsule()
                .fill(tintColor.opacity(0.12))
                .overlay(
                    Capsule()
                        .strokeBorder(tintColor.opacity(0.18), lineWidth: AppMetrics.dividerStandard)
                )
        )
        .background(
            Capsule()
                .fill(appTheme.palette.cardBackground)
        )
        .shadow(
            color: .black.opacity(AppShadows.toastOpacity),
            radius: AppShadows.toastRadius,
            y: AppShadows.toastY
        )
        .offset(y: min(dragOffset, 0))
        .gesture(
            DragGesture()
                .onChanged { value in
                    dragOffset = value.translation.height
                }
                .onEnded { value in
                    if value.translation.height < -20
                        || value.predictedEndTranslation.height < -200
                    {
                        onDismiss()
                    } else {
                        withAnimation(AppMotion.swipeSnapBackSpring) {
                            dragOffset = 0
                        }
                    }
                }
        )
        .accessibilityAddTraits(.isStatusUpdate)
        .padding(.top, AppMetrics.spacingSmall)
    }

    private var tintColor: Color {
        switch item.style {
        case .success: appTheme.palette.success
        case .info: appTheme.palette.accent
        case .warning: appTheme.palette.warning
        case .error: appTheme.palette.destructive
        }
    }
}

#Preview("Toast Styles") {
    VStack(spacing: 24) {
        AppToast(
            item: .init(message: "已複製", style: .success),
            onDismiss: {}
        )
        AppToast(
            item: .init(message: "背景同步完成，新增 3 個單字", style: .info),
            onDismiss: {}
        )
        AppToast(
            item: .init(message: "部分同步失敗，2 個單字未上傳", style: .warning),
            onDismiss: {}
        )
        AppToast(
            item: .init(message: "刪除失敗", style: .error),
            onDismiss: {}
        )
    }
    .padding()
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(AppTheme.light.palette.pageBackground)
}
```

- [ ] **Step 2: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/UIComponents/AppToast.swift
git commit -m "ios: add AppToast capsule view + preview"
```

---

### Task 4: Environment Key + 掛載點

**Files:**
- Modify: `ios/BooksBrowser/Services/AppEnvironment.swift`
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift`

依賴：Task 2（AppToastCoordinator）、Task 3（AppToast）

- [ ] **Step 1: 新增 Environment Key**

在 `ios/BooksBrowser/Services/AppEnvironment.swift` 的 `SyncCoordinatorKey` 後新增：

```swift
private struct AppToastCoordinatorKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: AppToastCoordinator = MainActor.assumeIsolated {
        AppToastCoordinator()
    }
}
```

在 `extension EnvironmentValues` 中 `syncCoordinator` 後新增：

```swift
var toastCoordinator: AppToastCoordinator {
    get { self[AppToastCoordinatorKey.self] }
    set { self[AppToastCoordinatorKey.self] = newValue }
}
```

- [ ] **Step 2: 掛載 Toast overlay**

在 `BooksBrowserApp` 的 properties 區域（與 `syncCoordinator` 等同層）新增：

```swift
let toastCoordinator = AppToastCoordinator()
```

注意：用 `let` 而非 `@State`，與 `syncCoordinator` 等其他 `@Observable` coordinator 一致。

找到 `rootView` 的 modifier chain，在 `.environment(\.readerSettings, .shared)` 之後加入：

```swift
.environment(\.toastCoordinator, toastCoordinator)
.overlay(alignment: .top) {
    if let toast = toastCoordinator.current {
        AppToast(item: toast, onDismiss: { toastCoordinator.dismiss() })
            .transition(.bannerReveal)
            .zIndex(999)
    }
}
```

- [ ] **Step 3: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/AppEnvironment.swift \
        ios/BooksBrowser/BooksBrowserApp.swift
git commit -m "ios: add toast environment key + mount overlay at app root"
```

---

### Task 5: 接入場景 — 複製回饋

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CardDocumentView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CardSections.swift`

依賴：Task 4（environment key 已註冊）

保留現有 `sensoryFeedback`，toast 是視覺補充。

- [ ] **Step 1: `CardDocumentView.swift` — 5 個 struct 加 toast**

在以下 5 個 private struct 中各加入 `@Environment(\.toastCoordinator) private var toastCoordinator`，並在 `copyTrigger.toggle()` 之後加入 `toastCoordinator.success("已複製")`：

1. `CardDocumentHeroBlock`（L97-99）
2. `CardDocumentExampleBlock`（L142-144）
3. `CardDocumentMeaningBlock`（L182-184）
4. `CardDocumentSourceBlock`（L219-221）
5. `CardDocumentCollocationsBlock`（L252-254）

- [ ] **Step 2: `CardSections.swift` — 5 個 section view 加 toast**

在以下 5 個 struct 中做相同處理：

1. `CardHeroSection`
2. `CardExamplesSection`
3. `CardSourceSection`
4. `CardExplanationSection`
5. `CardFormsSection`

每個 struct 加 `@Environment(\.toastCoordinator) private var toastCoordinator`，在 `copyTrigger.toggle()` 後加 `toastCoordinator.success("已複製")`。

- [ ] **Step 3: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/CardDocumentView.swift \
        ios/BooksBrowser/Views/Vocabulary/Components/CardSections.swift
git commit -m "ios: add toast feedback on copy actions"
```

---

### Task 6: 接入場景 — NotebookListView 刪除失敗 + 背景同步

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift`

依賴：Task 4

- [ ] **Step 1: `NotebookListView` — `.alert("刪除失敗")` 改用 toast**

在 `NotebookListView` 加入 `@Environment(\.toastCoordinator) private var toastCoordinator`。

移除 `.alert("刪除失敗"...)` 修飾器（約 L143-150）。

找到設定 `deleteError` 的地方，改為：

```swift
toastCoordinator.error(errorMessage)
```

移除 `@State private var deleteError: String?`（如果不再被其他地方使用）。

- [ ] **Step 2: `BooksBrowserApp` — 背景同步失敗 toast**

在 `onChange(of: scenePhase)` 的 `.active` case 中，`backgroundSync` 完成後，將 `lastBackgroundSyncError` 的處理改為 toast。

注意：`ContentView.swift` L30-34 已有 `AppBanner` 顯示 `lastBackgroundSyncError`。**不要重複處理** — Toast 和 Banner 會同時出現。兩種做法擇一：
- (a) 移除 `ContentView` 的 `AppBanner` 對 `lastBackgroundSyncError` 的處理，改用 toast（推薦：toast 更輕量、auto-dismiss 更適合瞬態錯誤）
- (b) 不在 `BooksBrowserApp` 加 toast，保留現有 `AppBanner`

推薦 (a)：移除 `ContentView.swift` 中 `lastBackgroundSyncError` 的 `AppBanner`（L30-35），在 `BooksBrowserApp` 的 `backgroundSync` 完成後加入：

```swift
if let error = kgService.lastBackgroundSyncError {
    toastCoordinator.warning(error)
    kgService.lastBackgroundSyncError = nil
}
```

- [ ] **Step 3: Build 確認編譯通過**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift \
        ios/BooksBrowser/BooksBrowserApp.swift \
        ios/BooksBrowser/ContentView.swift
git commit -m "ios: integrate toast for delete errors + background sync warnings"
```

---

### Task 7: 開 PR

- [ ] **Step 1: 建立分支並推送**

```bash
git checkout -b feature/capsule-toast
git push -u origin feature/capsule-toast
```

- [ ] **Step 2: 建立 PR**

```bash
gh pr create --title "ios: Capsule Toast 全域通知系統" --body "$(cat <<'EOF'
## Summary
- 新增 `AppToast` 膠囊形瞬態通知元件，4 種語意樣式（success/info/warning/error）
- 新增 `AppToastCoordinator` 全域 coordinator，透過 `@Environment` 注入
- 掛載於 `BooksBrowserApp` overlay，所有頁面可觸發
- 首批接入：複製回饋、notebook 刪除失敗、背景同步錯誤

## Test plan
- [ ] Xcode Preview 確認 4 種樣式渲染正確（light/dark/sepia）
- [ ] 單字詳情頁複製 → toast「已複製」出現 + 2.5s 自動消失
- [ ] 上滑 toast → 立即消失
- [ ] 點擊 toast → 立即消失
- [ ] Dynamic Type XXL → 文字不截斷
- [ ] VoiceOver 啟用 → toast 不自動消失，VoiceOver 唸出內容

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
