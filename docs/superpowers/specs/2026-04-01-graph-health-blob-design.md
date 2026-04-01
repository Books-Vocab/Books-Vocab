# Graph Health Blob — Design Spec

> 把總覽頁圖譜縮圖從「結構預覽」改為「色塊健康信號器」。

## 目標

使用者一眼掃過色團主色調即知複習健康度：綠=安全、橘=到期、紫=逾期。下方極簡 bar 補充精確位置。

## 變更範圍

### 1. D3 力參數：密集色團

| 參數 | 現值 | 新值 | 理由 |
|------|------|------|------|
| repel | 40 | 12 | 極弱排斥，允許緊密聚集 |
| linkDistance | 30 | 12 | 短連結拉節點靠攏 |
| linkStrength | 1.2 | 1.8 | 強連結力壓縮結構（保守值避免震盪，實測後可調） |
| centerStrength | 0.04 | 0.2 | 高向心力把散落節點拉回中心 |
| baseNodeRadius | 3 | 4 | 稍大節點增強色塊面積 |
| forceCollide | nodeRadius(d)+2 | 移除 | JS 端 `sim.force('collide', null)`，允許節點重疊 |
| linkThickness | 0.8 | 0.8 | 不變 |

graph.html 調整：
- `opacityForEdge()` 加 `isThumbnail` 分支：thumbnail 時固定回傳 **0.08**（極淡，保留圖譜紋理）
- `initGraph()` 中 thumbnail 模式下 `sim.force('collide', null)` 移除碰撞力
- 移除 `GraphForces.collideRadius` 的傳遞（本就是 dead field，JS 從未讀取）

### 2. 健康度 Bar（純 SwiftUI）

位置：圖譜 WebView 下方，卡片內，graphEntryBody 底部。

**視覺規格：**
- 漸層條高度：**2pt**
- 圓角：**1pt**
- 左右 padding：與 cardBlockPadding 對齊
- 底部 margin：8pt（與卡片底邊的呼吸空間）
- 漸層：透過 `ReviewGradient.color(for:)` 公開 API 取樣 11 個 ratio 點（0, 0.15, 0.30, …, 3.0），組成 `LinearGradient`（不需公開 private stops）
- Marker：小倒三角 ▼，高 5pt 寬 6pt，填色 `vocabSkin.palette.primaryText`
- Marker 位置：`clamp(avgRatio, 0, 3) / 3.0` 映射到 bar 寬度
- 無文字、無標題、無數字

**avgRatio 計算：**
- 來源：`graphThumbnailNodes` 中 `ratio != nil` 的節點
- 公式：`sum(ratios) / count`
- 若無有效 ratio → 隱藏整條 bar

### 3. Bug fix：Signature 比對

現行 signature 只比對 count，顏色變化不觸發重繪。

改為：對 nodes 陣列做 stable hash（id + colorHex + ratio），加入 signature。

## 不做的事

- 不改全圖頁的力參數
- 不新增 design token（bar 用現有 ReviewGradient + vocabSkin）
- 不加動畫到 marker
- 不加文字標註

## 受影響檔案

| 檔案 | 變更 |
|------|------|
| `GraphThumbnailWebView.swift` | 更新 forces 參數、移除 collideRadius field、修 signature hash |
| `graph.html` | `opacityForEdge` 加 thumbnail 分支、`initGraph` 移除 thumbnail collide、thumbnail 後加 `sim.force('collide', null)` |
| `StatsPresenter.swift` | graphEntryBody 加健康度 bar、計算 avgRatio、消除 graphThumbnailNodes 重複計算 |
