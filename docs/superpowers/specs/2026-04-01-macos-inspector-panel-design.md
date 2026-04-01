# macOS Inspector Panel Design

## Problem

macOS 上 `.platformFullScreenCover` 映射為 `.sheet()`，系統 sheet 有高度上限，導致：
- WordDetailSheet（單字詳情）內容被裁切
- TodayReviewView（複習卡片）底部按鈕區域被裁切

## Solution

macOS 上改用 SwiftUI `.inspector()` modifier 取代 sheet/fullScreenCover，提供無高度限制的右側面板。iOS 行為完全不變。

## 行為規格

### Inspector 觸發

| 觸發事件 | 現有行為 (macOS) | 新行為 (macOS) |
|---------|-----------------|---------------|
| 點擊單字 row | `.toastSheet` → WordDetailSheet | Inspector 顯示 WordDetailSheet |
| 啟動複習 | `.sheet` → TodayReviewView | Inspector 顯示 TodayReviewView |
| 複習中點「查看詳情」 | 複習內的 sheet | Inspector 內部 LinkedCardOverlay（不變） |

### Inspector 內容優先序

Inspector 同時只顯示一種內容：
1. `activeReviewSession != nil` → 顯示 TodayReviewView
2. `selectedEntry != nil` → 顯示 WordDetailSheet
3. 兩者皆 nil → inspector 自動關閉

### Inspector 控制

- **自動開啟**：設定 `selectedEntry` 或 `activeReviewSession` 時自動顯示
- **關閉方式**：
  - 點 inspector 內的 X 按鈕 → 清除對應 state（`selectedEntry = nil` 或 `activeReviewSession = nil`）
  - 複習完成 → `activeReviewSession` 歸 nil → inspector 自動關閉或 fallback 到 selectedEntry

### Inspector 尺寸

- 寬度：系統預設（約 300-400pt），使用者可拖拽調整
- 高度：與主視窗等高，無裁切問題
- 內容：ScrollView 自由滾動

### 影響範圍

| 檔案 | 改動 |
|------|------|
| `VocabularyListView+Sheets.swift` | macOS 分支：移除 selectedEntry 和 activeReviewSession 的 sheet，改由 inspector 處理 |
| `VocabularyListView.swift` | macOS：加 `.inspector(isPresented:)` modifier，內容根據 coordinator state 切換 |
| `NotebookListView.swift` | macOS：跨本複習也改用 inspector |
| `WordDetailSheet.swift` | 無改動，`wrapInNavigation: false` 在 inspector 內使用 |
| `TodayReviewView.swift` | 無改動，直接嵌入 inspector |
| `TodayReviewPresenter.swift` | 可能需調整 `maxWidth: 600` 以適應 inspector 寬度 |

### 不做的事

- 不改 iOS / iPadOS 行為
- 不新增 user preference 記憶 inspector 狀態（首版）
- 不做 inspector 和 sheet 的切換按鈕（首版直接 inspector-only on macOS）
