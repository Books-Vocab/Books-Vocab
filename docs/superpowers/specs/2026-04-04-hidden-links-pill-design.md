# Hidden Links Pill Design

## 問題
隱藏的知識連結以淡灰色文字 inline 混在同 category 可見連結之間，視覺雜亂且不直觀。

## 目標
隱藏連結從原位移除，統一收到知識連結區塊最底部，以 capsule pill 標籤顯示。

## 設計

### 資料層
- `CardPresentation` 新增 `hiddenLinks: [KGCardLinkSummary]` computed property
- `linksSection` 改用 `activeLinkGroups`（已存在，只含可見連結）

### UI 層
- 可見連結區：從 `linkGroups` 改為 `activeLinkGroups`
- 隱藏 pill 區：所有隱藏連結以 capsule pill 水平排列（`CollocationFlowLayout`），置於所有 category 下方
- Pill 樣式：`Capsule()` 背景、`quaternaryText` 文字色、`divider.opacity(0.5)` 背景色
- 每個 pill 保留 context menu（恢復連結 / 刪除連結）

### 共用元件
- `CollocationFlowLayout` 從 `private` 改為 `internal`，供 `WordDetailPresenter` 共用

### 條件顯示
- `linksSection` 的顯示條件需同時考慮 `activeLinkGroups` 和 `hiddenLinks`
- 若只有隱藏連結沒有可見連結，仍顯示知識連結區塊（只顯示 pill 區）

## 不做
- 不改資料模型
- 不改 `WordDetailGraphLinkRow`（保留 `hiddenRowContent` 避免影響其他使用處）
- 不新增 design token

## 影響範圍
- `CardPresentation.swift` — 新增 1 computed property
- `CardDocumentView.swift` — `CollocationFlowLayout` visibility 改為 internal
- `WordDetailPresenter.swift` — `linksSection` 重構 + 新增 hidden pill 區
