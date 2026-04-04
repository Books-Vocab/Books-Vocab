# macOS Detail Panel Draggable Divider — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 讓 macOS 兩欄佈局的分隔線可拖曳調整右欄寬度，雙擊回復預設。
**Architecture:** 在現有 `safeAreaInset` 架構上，將靜態 `Divider()` 替換為帶 `DragGesture` 的自訂 `MacDividerHandle` view。Parent (NotebookListView) 持有所有寬度 state（`@AppStorage` 持久化寬度 + `@State` 拖曳即時寬度），MacDividerHandle 透過 binding 更新。用 `GeometryReader` 取得容器寬度做 clamp。
**Tech Stack:** SwiftUI, AppKit (NSCursor), macOS only (`#if os(macOS)`)

---

### Task 1: AppMetrics 常量

**Files:**
- Modify: `ios/BooksBrowser/Models/AppMetrics.swift`

- [ ] **Step 1: 新增 MacDetailPanel namespace**

在 `AppMetrics` enum 結尾（`AppTagMetrics` 之前）新增：

```swift
#if os(macOS)
extension AppMetrics {
    enum MacDetailPanel {
        static let defaultWidth: CGFloat = 420
        static let minWidth: CGFloat = 280
        static let maxWidth: CGFloat = 600
        static let leftMinWidth: CGFloat = 300
        static let hitAreaWidth: CGFloat = 8
    }
}
#endif
```

- [ ] **Step 2: 確認編譯**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**
`ios: add MacDetailPanel metrics for draggable divider`

---

### Task 2: MacDividerHandle 元件

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/MacDividerHandle.swift`
- Test: 手動驗證（UI component，靠 Task 4 整合測試）

- [ ] **Step 1: 建立 MacDividerHandle.swift**

Spec signature 為 `(panelWidth: Binding, onDoubleClick: () -> Void)`，實作補充 `dragWidth` binding（parent 持有）和 `containerWidth`（clamp 用）。

**資料流設計：**
- `panelWidth`（`@Binding` → parent 的 `@AppStorage`）：持久化寬度，僅在 `onEnded` 寫入
- `dragWidth`（`@Binding` → parent 的 `@State`）：拖曳中即時寬度，nil = 未拖曳
- Parent 用 `dragWidth ?? effectivePanelWidth` 決定面板 frame

```swift
#if os(macOS)
import SwiftUI
import AppKit

/// macOS 專用可拖曳分隔線。
/// 8pt 透明 hit area，中間 1pt 視覺線，hover 切換 resize 游標。
///
/// 寬度 state 由 parent 持有：
/// - `panelWidth`: 持久化寬度（@AppStorage），僅 onEnded 寫入
/// - `dragWidth`: 拖曳中即時寬度，nil = 未拖曳
struct MacDividerHandle: View {
    @Binding var panelWidth: CGFloat
    @Binding var dragWidth: CGFloat?
    let containerWidth: CGFloat
    var onDoubleClick: () -> Void

    @State private var dragStartWidth: CGFloat = 0

    private var effectiveMax: CGFloat {
        min(
            AppMetrics.MacDetailPanel.maxWidth,
            containerWidth - AppMetrics.MacDetailPanel.leftMinWidth
        )
    }

    var body: some View {
        Rectangle()
            .fill(Color.clear)
            .frame(width: AppMetrics.MacDetailPanel.hitAreaWidth)
            .contentShape(Rectangle())
            .overlay {
                Divider()
            }
            .onHover { hovering in
                if hovering {
                    NSCursor.resizeLeftRight.push()
                } else {
                    NSCursor.pop()
                }
            }
            .gesture(
                DragGesture(minimumDistance: 1, coordinateSpace: .global)
                    .onChanged { value in
                        if dragWidth == nil {
                            dragStartWidth = panelWidth
                        }
                        let newWidth = dragStartWidth - value.translation.width
                        dragWidth = newWidth.clamped(
                            to: AppMetrics.MacDetailPanel.minWidth...effectiveMax
                        )
                    }
                    .onEnded { _ in
                        if let finalWidth = dragWidth {
                            panelWidth = finalWidth
                        }
                        dragWidth = nil
                    }
            )
            .onTapGesture(count: 2) {
                onDoubleClick()
            }
    }
}

/// ContainerWidthKey — 用 PreferenceKey 把容器寬度傳給 parent。
struct ContainerWidthKey: PreferenceKey {
    static let defaultValue: CGFloat = 800
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private extension CGFloat {
    func clamped(to range: ClosedRange<CGFloat>) -> CGFloat {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
#endif
```

- [ ] **Step 2: 確認編譯**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**
`ios: add MacDividerHandle — draggable split divider for macOS`

---

### Task 3: NotebookListView 整合

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:44-46, 236-246`

- [ ] **Step 1: 新增 state 變數**

在 `NotebookListView` 的 `#if os(macOS)` block（line 44）改為：

```swift
#if os(macOS)
@State private var macDetail = MacDetailState()
@State private var isEditingMacDetailEntry = false
@AppStorage("kg_mac_detail_panel_width") private var macPanelWidth: Double = Double(AppMetrics.MacDetailPanel.defaultWidth)
@State private var macDragWidth: CGFloat?
@State private var macContainerWidth: CGFloat = 800
#elseif os(iOS)
```

- [ ] **Step 2: 替換 safeAreaInset 內容**

將 line 236-246 區段：

```swift
#elseif os(macOS)
.environment(\.detailRouter, macDetail)
.safeAreaInset(edge: .trailing, spacing: 0) {
    if macDetail.hasDetail {
        HStack(spacing: 0) {
            Divider()
            macDetailPanel
                .frame(minWidth: 350, idealWidth: 420, maxWidth: 600)
        }
        .transition(.move(edge: .trailing).combined(with: .opacity))
    }
}
.animation(AppMotion.standardSpring, value: macDetail.hasDetail)
```

替換為：

```swift
#elseif os(macOS)
.environment(\.detailRouter, macDetail)
.overlay {
    GeometryReader { geo in
        Color.clear
            .preference(key: ContainerWidthKey.self, value: geo.size.width)
    }
}
.onPreferenceChange(ContainerWidthKey.self) { macContainerWidth = $0 }
.safeAreaInset(edge: .trailing, spacing: 0) {
    if macDetail.hasDetail {
        HStack(spacing: 0) {
            MacDividerHandle(
                panelWidth: Binding(
                    get: { CGFloat(macPanelWidth) },
                    set: { macPanelWidth = Double($0) }
                ),
                dragWidth: $macDragWidth,
                containerWidth: macContainerWidth,
                onDoubleClick: {
                    withAnimation(AppMotion.standardSpring) {
                        macPanelWidth = Double(AppMetrics.MacDetailPanel.defaultWidth)
                    }
                }
            )
            macDetailPanel
                .frame(width: macDragWidth ?? effectiveMacPanelWidth)
        }
        .transition(.move(edge: .trailing).combined(with: .opacity))
    }
}
.animation(AppMotion.standardSpring, value: macDetail.hasDetail)
```

**寬度決策邏輯：**
- 拖曳中 → `macDragWidth`（即時跟手，不寫 UserDefaults）
- 非拖曳 → `effectiveMacPanelWidth`（讀 `@AppStorage`，含視窗縮小 clamp）

- [ ] **Step 3: 新增 computed property**

在 NotebookListView body 下方（`#if os(macOS)` macDetailPanel 附近）新增：

```swift
#if os(macOS)
private var effectiveMacPanelWidth: CGFloat {
    let desired = CGFloat(macPanelWidth)
    let maxAllowed = macContainerWidth - AppMetrics.MacDetailPanel.leftMinWidth
    return min(desired, max(maxAllowed, AppMetrics.MacDetailPanel.minWidth))
}
#endif
```

此 property 處理視窗縮小場景：當 saved width + leftMinWidth > containerWidth 時，自動收窄右欄但不覆寫 saved width。

- [ ] **Step 4: 確認編譯**
Run: `./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 5: Commit**
`ios: integrate draggable divider into macOS two-column layout`

---

### Task 4: 手動驗證 Checklist

- [ ] **Step 1: 驗證拖曳**
  - 開啟單字本，點擊任一單字展開右欄
  - hover 分隔線，確認游標變為 ↔
  - 拖曳分隔線，確認右欄寬度跟手變化
  - 拖曳到極限位置，確認 clamp 生效（左欄不低於 300pt，右欄不低於 280pt / 超過 600pt）

- [ ] **Step 2: 驗證雙擊 reset**
  - 拖曳到非預設寬度
  - 雙擊分隔線，確認以彈簧動畫回到 420pt

- [ ] **Step 3: 驗證持久化**
  - 拖曳到某個寬度
  - 關閉右欄（點 X）再重新開啟，確認保持上次寬度
  - 完全退出 app 再開啟，確認寬度保持

- [ ] **Step 4: 驗證視窗縮放**
  - 將右欄拖到 600pt
  - 縮小視窗寬度，確認右欄自動收窄且左欄維持 ≥ 300pt
  - 放大視窗，確認右欄恢復 saved width（不被覆寫）

- [ ] **Step 5: 驗證面板出場動畫**
  - 點擊單字打開右欄，確認帶動畫從右側滑入
  - 點 X 關閉，確認帶動畫滑出
  - 進入複習模式，確認右欄同樣正常顯示

- [ ] **Step 6: 確認 iOS 無影響**
  - 切換到 iPhone / iPad simulator，確認編譯通過、行為無變化
