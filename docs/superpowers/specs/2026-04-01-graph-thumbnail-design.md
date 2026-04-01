# 關聯圖縮圖 — 設計規格

## 目標

在總覽頁的「關聯圖」卡片內嵌入即時迷你圖預覽，讓使用者一眼看到知識網絡全貌，點擊進入完整圖。

## 方案

**簡化版 B** — 復用現有 `graph.html` D3 力模擬，加 `thumbnail` mode。單一渲染來源，零視覺偏差，低維護成本。

## 架構

```
StatsPresenter.task()
  ├─ 既有: buildSummary()
  └─ 新增: kgService.pullGraphLinks() / DemoDataProvider (平行)
           ↓
      KnowledgeGraphPresentation.nodes/edges() (既有函數)
           ↓
      GraphThumbnailWebView (新 UIViewRepresentable)
           ↓
      graph.html initGraph({ ..., thumbnail: true })
```

## 變更清單

### 1. `graph.html` — 加 thumbnail mode

`initGraph()` payload 新增 `thumbnail: Boolean` 欄位。

**thumbnail mode 行為：**

| 面向 | 正常模式 | thumbnail mode |
|------|---------|---------------|
| label | 顯示 | 隱藏 |
| node glow | 顯示 | 隱藏（縮圖太小，glow 變成色塊） |
| drag/click/hover | 啟用 | 全部禁用 |
| alpha decay | 0.0228（D3 預設） | 0.08（~40 次迭代收斂） |
| alpha min | 0.001 | 0.05（更早停止） |
| 背景 | theme background | `transparent` |
| velocity decay | 0.4（D3 預設） | 0.6（更快穩定） |
| 初始 spawn radius | `random * 80 + 20` | `random * 30 + 10`（配合 140pt 視口） |

**JS 實作細節：**

1. **`initGraph()`**：解析 `data.thumbnail` → 存入 module-scope `isThumbnail` flag
2. **`draw()`**：`isThumbnail` 時跳過 glow（radial gradient）和 label 繪製
3. **事件綁定**（module-scope，lines ~189-217）：用 `if (!isThumbnail)` 包裹 `d3.drag()`、`d3.zoom()`、click/hover listeners 的註冊
4. **simulation 參數**：`sim.alphaDecay(0.08).alphaMin(0.05).velocityDecay(0.6)`
5. **初始位置**：`isThumbnail` 時縮小 spawn radius 確保節點在視口內

### 2. `GraphThumbnailWebView.swift` — 新檔案

輕量 `UIViewRepresentable`，職責單一：顯示 thumbnail 模式的 graph。

```swift
struct GraphThumbnailWebView: UIViewRepresentable {
    let nodes: [KnowledgeGraphNode]
    let edges: [KnowledgeGraphEdge]
    let theme: KnowledgeGraphTheme
    @Environment(\.colorScheme) private var colorScheme
}
```

**與 GraphWebView 的差異：**
- 不處理 nodeClick / selection / hover
- 不支援 updateForces（無設定面板）
- `isUserInteractionEnabled = false`
- `isOpaque = false`，背景透明
- Forces 硬編碼為適合縮圖的參數
- Coordinator 只處理 "ready" message，不處理 "nodeClick"

**Payload 建構**：複製 `GraphWebView.buildPayload()` 的結構，簡化為只需 nodes/edges/theme/forces + `thumbnail: true`。不抽共用函數——兩者職責不同，獨立維護更清晰。

**colorScheme 響應**：`updateUIView()` 偵測 `colorScheme` 變化，重新用當前 theme hex 呼叫 `initGraph()`（與 GraphWebView 同策略）。

**Thumbnail 專用 forces：**
```swift
GraphForces(
    repel: 40,              // 較弱排斥（緊湊佈局）
    linkDistance: 30,        // 較短連結（緊湊）
    linkStrength: 1.2,       // 較強連結
    centerStrength: 0.04,    // 較強向心（防飄散）
    baseNodeRadius: 3,       // 較小節點
    collideRadius: 3,        // 未被 JS 使用，與 baseNodeRadius 對齊即可
    linkThickness: 0.8       // 較細連線
)
```

> 注意：`collideRadius` 在 `graph.html` 中被硬編碼為 `nodeRadius(d) + 2`，此欄位僅為滿足 `GraphForces` struct 型別，實際無效果。

### 3. `StatsPresenter.swift` — 替換 graphEntrySection

**新增環境注入：**
```swift
@Environment(\.kgService) private var kgService
@Environment(\.authManager) private var authManager
```

**新增 state：**
```swift
@State private var graphLinks: [KGGraphLink]?  // nil = loading
```

**資料載入（與 buildSummary 平行，含 demo mode 處理）：**
```swift
.task(id: computeKey) {
    async let summaryTask = StatsPresentation.buildSummary(...)
    async let linksTask = loadGraphLinks()
    summary = await summaryTask
    graphLinks = await linksTask
}

private func loadGraphLinks() async -> [KGGraphLink] {
    if authManager.isDemoMode {
        return DemoDataProvider.demoGraphLinks
    }
    guard authManager.isLoggedIn else { return [] }
    return (try? await kgService.pullGraphLinks()) ?? []
}
```

**graphEntrySection 新結構：**

```
┌──────────────────────────────────────┐
│  ⊛ 關聯圖               12 詞 · 8 連結  >  │  ← header（始終顯示）
├──────────────────────────────────────┤
│                                      │
│     ·───·    ·                       │
│    / · · \  / \                      │
│   ·   ·───·   ·        ← WebView    │  ← 140pt
│    \     /              thumbnail    │
│     ·───·                            │
│                                      │
└──────────────────────────────────────┘
```

**三種狀態（140pt body 區域）：**
1. **loading**（`graphLinks == nil`）：居中 `ProgressView().controlSize(.small)`
2. **empty**（links 為空或過濾後無連結節點）：`VocabStateMessageCard` + 「探索單字建立連結」
3. **normal**：`GraphThumbnailWebView`

**Header 行始終顯示：**
- icon + 「關聯圖」+ chevron 始終存在
- 統計文字（「N 詞 · M 連結」）：loading 時不顯示，載入完成後淡入

### 4. `StatsPresentation.swift` — 不修改

Graph nodes/edges 計算已有 `KnowledgeGraphPresentation.nodes()` / `edges()`。Stats Summary 不需要 graph 欄位——thumbnail 的資料路徑獨立於 summary。

## 不做的事

- **不快取 links** — 總覽頁的 `.task` 已有 SwiftUI 生命週期管理，頁面消失自動清理
- **不新增 API** — 復用 `pullGraphLinks()`
- **不做動畫交互** — 縮圖是靜態預覽，互動在全圖頁
- **不抽共用 WebView 基類** — 兩者職責不同（互動 vs 靜態），獨立維護更清晰
- **不修 `collideRadius` dead code** — 既有問題，不在此 scope 內

## 效能

- Links API 呼叫與 stats 計算平行，不增加頁面載入時間
- thumbnail mode alpha decay 0.08 → ~40 次迭代收斂（正常模式 ~300 次）
- WKWebView 記憶體 ~20-30MB（含 web process baseline），頁面切走後 SwiftUI 自動回收
- 從總覽頁 NavigationLink 進入全圖頁時，thumbnail WebView 隨 StatsPresenter 離開 view hierarchy 被釋放，不會與全圖 WebView 共存
- 過濾孤立節點，縮圖只畫有連結的節點（與全圖 showsIsolatedNodes=false 一致）
- 縮小初始 spawn radius（30 vs 80）確保節點在 140pt 視口內，避免首幀飄散
