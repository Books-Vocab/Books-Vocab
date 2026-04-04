# macOS Detail Panel Draggable Divider — Design Spec

## Problem

macOS 版單字本頁面採左右兩欄佈局（左欄單字列表、右欄複習/詳情面板），目前中間的分隔線是靜態 `Divider()`，右欄寬度固定在 350–600pt 範圍內（ideal 420pt）。使用者無法拖曳調整兩欄比例。

## Goal

讓使用者可以拖曳分隔線自由調整右欄寬度，並支援雙擊回復預設寬度。行為對齊 macOS 原生應用（Finder、Xcode）。

## Design

### 拖曳行為

| 項目 | 規格 |
|------|------|
| 拖曳方式 | 水平 `DragGesture` 在 divider hit area 上 |
| Hit area | 8pt 寬（視覺線 1pt，左右各 3.5pt 透明區域吃手勢） |
| 游標 | hover 時切換為 `NSCursor.resizeLeftRight`，離開恢復 |
| 拖曳中動畫 | 無（即時跟手，零延遲） |
| 雙擊 | `withAnimation(AppMotion.standardSpring)` 回復預設寬度 420pt |

### 寬度約束

| 參數 | 值 | 說明 |
|------|------|------|
| `defaultWidth` | 420pt | 預設值 / 雙擊 reset 目標 |
| `minWidth` | 280pt | 右欄最小寬度 |
| `maxWidth` | 600pt | 右欄最大寬度 |
| `leftMinWidth` | 300pt | 左欄最小寬度保護 |

拖曳時的實際可用範圍：clamp 在 `minWidth` 到 `min(maxWidth, containerWidth - leftMinWidth)` 之間。

### 視窗縮小保護

當視窗寬度縮小導致 `savedWidth + leftMinWidth > containerWidth` 時：
- 右欄實際顯示寬度 = `containerWidth - leftMinWidth`
- 不覆寫 saved width（使用者放大視窗後恢復原寬度）

### 寬度持久化

- 使用 `@AppStorage("kg_mac_detail_panel_width")` 存 `Double`
- 拖曳結束時（`onEnded`）才寫入，避免頻繁 I/O
- 預設值 420（key 不存在時 fallback）

### 面板出現 / 消失

- `hasDetail == true` → divider + panel 一起從右側滑入（保留現有 `.move(edge: .trailing).combined(with: .opacity)` transition）
- `hasDetail == false` → divider + panel 一起消失
- 寬度記憶保留，下次開啟用 saved width

### 視覺設計

- 分隔線：1pt 寬，使用系統 `Divider()` 的預設顏色
- 無額外裝飾（grip dots 等）— 保持乾淨
- Hover 時游標變化已足夠提供操作提示

## Architecture

### 不用 HSplitView 的原因

現有架構用 `.safeAreaInset(edge: .trailing)` 掛載右欄，與 `NavigationStack`、出場動畫、`MacDetailState` 深度整合。`HSplitView` 無法控制出場動畫且和 `safeAreaInset` 互斥，改動風險大、收益低。

### 修改範圍

| 檔案 | 變動類型 | 說明 |
|------|----------|------|
| `Models/AppMetrics.swift` | 修改 | `AppMetrics` 新增 `macDetailPanel` namespace 常量 |
| `Views/Vocabulary/MacDividerHandle.swift` | **新增** | macOS-only 拖曳手柄 View |
| `Views/Vocabulary/Scenes/NotebookListView.swift` | 修改 | 替換 `Divider()` 為 `MacDividerHandle`，右欄 width 改為動態 |

### MacDividerHandle 元件

```
MacDividerHandle(panelWidth: Binding<CGFloat>, onDoubleClick: () -> Void)
```

- 接收 `panelWidth` binding，拖曳時直接更新
- `onDoubleClick` 回調由外部處理 reset + animation
- 內部管理 hover cursor 切換
- `#if os(macOS)` 隔離

### NotebookListView 改動

```swift
// Before
HStack(spacing: 0) {
    Divider()
    macDetailPanel
        .frame(minWidth: 350, idealWidth: 420, maxWidth: 600)
}

// After
HStack(spacing: 0) {
    MacDividerHandle(panelWidth: $macPanelWidth) {
        withAnimation(AppMotion.standardSpring) {
            macPanelWidth = AppMetrics.MacDetailPanel.defaultWidth
        }
    }
    macDetailPanel
        .frame(width: effectivePanelWidth)
}
```

其中 `effectivePanelWidth` = `min(macPanelWidth, max(containerWidth - leftMinWidth, minWidth))`。

## Scope Exclusions

- 不做左欄寬度拖曳（左欄自動填充剩餘空間）
- 不做拖曳 snap 到檔位
- 不做 collapse（拖到最小自動收起）— 已有 X 按鈕關閉面板
- 不做面板最小化按鈕
- iOS 不受影響（全部 `#if os(macOS)` 隔離）
