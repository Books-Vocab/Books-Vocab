<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksBrowser/Platform/PanelWorkspace/
  - ios/BooksBrowser/Views/Podcast/
  - ios/BooksBrowser/Views/Vocabulary/
  - ios/BooksBrowser/Views/Bookshelf/
verified_against: 1d121efc
-->

# Catalyst 2D 可堆疊 Block Workspace

## 問題

Catalyst（與 iPad regular）的 master-detail 目前是**每個 feature 各自重抄一份「單 master + 單 detail」**：

| 重複實作 | 行數 | 內容 |
|---|---|---|
| `NotebookDetailPresentation` | ~140 | `safeAreaInset(.trailing)` + `DraggableDivider` + `drawerReveal` + `@AppStorage` 寬度 + `onGeometryChange` containerWidth |
| `PodcastDetailPresentation` | ~75 | 同上（去 review/edit 分支） |
| `WordDetailPresentation` | ~? | 同構 |
| `BookshelfView.selectedSeriesRemoteId` master-pane | inline | 上次 pop-to-root 修復的權宜 `@State` |

**技術債三宗**：
1. **N 份近乎雷同的 presentation modifier** — 改一個行為要同步改 N 處（DRY 破口）。
2. **只能單層 detail** — 結構上無法「series→episodes→player 全鏈同時可見」，更無法欄內再疊。
3. **close 是 `router.dismiss()` 單層語意** — 無「每個 block 獨立關閉」能力。
4. **歷史 bug 溫床** — `safeAreaInset` 掛在 push-depth-1 child 曾導致 NavigationStack subtree remount → pop-to-root（commit `413912b3` 才修）。每個 feature 各自踩。

## 目標

把上述收斂成**一套 2D 可堆疊 block workspace 引擎**，達成使用者三項要求：

1. **每個 block 可良好堆疊** — 水平（Miller columns）+ 垂直（欄內 stack）雙軸。
2. **一套良好的堆疊模式管理** — 單一 `PanelWorkspace` coordinator 管理 2D 排列（開欄/疊塊/關閉/截斷）。
3. **每個 block 可按叉叉關閉 + 良好動畫** — 每個 block 有 ✕，水平/垂直 insert/remove 皆走 `AppMotion` 既有曲線。

**範圍**：僅 `LayoutMode.regular`（Catalyst / iPad regular）。**iPhone compact 完全不動**，續用既有 `TabView` + `NavigationStack` push / sheet。

## 核心洞見（決定架構）

> **一個 column 本身就是一個垂直 `ResizableStack`；整個 workspace 是水平的 `ResizableStack` of columns。**

同一個「可拖拉調整大小 + 每項可關閉 + insert/remove 過渡」的 primitive，以 `Axis` 參數化後組合兩次。這是「低技術債、最好擴展」的單一抽象：**新增任何 block 類型 = 在 `PanelKind` enum 加一個 case + 在 resolver 加一個分支**，引擎零改動。

既有可複用資產（不重造）：
- `DraggableDivider` / `MacDetailPanelMetrics` / `MacColumnResizeCursor` — 已是泛型拖拉欄，**泛化加 `axis` 參數**即支援垂直。
- `AppMotion.panelState`（= standardSpring）/ `.drawerReveal` transition — 沿用，不新增曲線。
- `PodcastPlayerView.task(id:)` swap 路徑、各 feature 既有 detail view — 作為 block 內容，原樣掛入。

## 架構

### 1. 資料模型（`Platform/PanelWorkspace/`）

```swift
/// 每個 block 承載的 payload。擴展點：加 case 即加一種 block。
enum PanelKind: Equatable, Hashable {
    case podcastSeries(remoteID: String)
    case podcastEpisode(remoteID: String)
    case wordDetail(entryID: String)        // VocabularyEntry.id 字串化
    case reviewSession(id: UUID)
    // 未來：bookDetail / kgNode / linkedWord ...
}

/// 垂直堆疊中的單一 block。
struct Block: Identifiable, Equatable {
    let id: BlockID                 // 穩定身分（供 SwiftUI diff + 精準 close）
    let kind: PanelKind
    var height: CGFloat?            // 欄內垂直尺寸；nil = flexible 均分
}

/// 一欄 = 一個垂直 block stack + 欄寬。
struct WorkColumn: Identifiable, Equatable {
    let id: ColumnID
    var blocks: [Block]             // top→bottom
    var width: CGFloat
}
```

### 2. 堆疊模式管理 — `PanelWorkspace` coordinator

```swift
@Observable @MainActor
final class PanelWorkspace {
    private(set) var columns: [WorkColumn] = []   // 左→右；不含 root master

    // 水平軸（navigate / drill）
    @discardableResult func openColumn(_ kind: PanelKind, after: ColumnID?) -> ColumnID
    func replaceColumns(after: ColumnID?, with: PanelKind)   // Miller 截斷語意
    func closeColumn(_ id: ColumnID)                          // 串聯關右側

    // 垂直軸（split / pin / reference）
    @discardableResult func stack(_ kind: PanelKind, in: ColumnID) -> BlockID
    func closeBlock(_ id: BlockID)   // 移除該 block；欄空 → 自動收欄（→ 串聯右側）

    func reset()                     // 回到純 root master
    // 不變式：無空欄；columns 順序即視覺左→右
}
```

> root master（section 主視圖，如 BookshelfView / NotebookListView）由 container 以 `content` 渲染，**不**進 `columns`。`columns` 僅 depth≥1 的衍生欄。

### 3. 容器 — `PanelWorkspaceContainer`

`regular`：`ScrollView(.horizontal)`（欄總寬溢出時水平捲，新欄 `scrollTo` 自動帶到視野）內 `HStack`：root + 各 `WorkColumn`，欄間 `DraggableDivider(axis: .horizontal)`；每欄內為 `VerticalBlockStack`（`VStack` + 欄內 block 間 `DraggableDivider(axis: .vertical)`）。
`compact`：只渲染 `content`（root），drill 走既有 NavigationStack push（**零改動**）。

```
ScrollView(.horizontal)            ← 溢出水平捲，push 時 scrollTo 末欄
└ HStack
  ├ root (section master)
  ├ DraggableDivider(.horizontal)
  ├ WorkColumn[0] = VerticalBlockStack
  │   ├ BlockChrome(✕) + resolve(block.kind)     ← 每 block 有 ✕
  │   ├ DraggableDivider(.vertical)
  │   └ BlockChrome(✕) + resolve(...)            ← 欄內垂直疊
  ├ DraggableDivider(.horizontal)
  └ WorkColumn[1] = ...
.animation(AppMotion.panelState, value: columns)
```

### 4. 內容解耦 — resolver

`PanelKind` 為封閉 enum，由單一 `@ViewBuilder func panelContent(for kind:, proxy:) -> some View` 集中解析 → 引擎 core **不 import** 任何 feature view（可獨立測試、無循環依賴）。`proxy: PanelProxy` 知道自身 (column, depth)，提供 `proxy.openColumn(_:)` / `proxy.stack(_:)` / `proxy.close()` 給 block 內容觸發導航與自關。

### 5. 動畫契約（不新增曲線）

| 事件 | 動畫 |
|---|---|
| 水平欄 insert/remove | `.drawerReveal`（move .trailing + opacity）+ `AppMotion.panelState` |
| 垂直 block insert/remove | `.move(.top/.bottom) + opacity`（沿用 `statusRowReveal` 語意，必要時加單一 `blockStackReveal` token）|
| divider 拖拉 | `DraggableDivider`（axis-generic），即時 `dragWidth/dragHeight`，`onEnded` 持久化 |
| 欄寬/塊高持久化 | `@AppStorage` per-`PanelKind`（episode 欄記住自己的寬）|

## 設計決策

| # | 決策 | 理由 |
|---|------|------|
| D1 | **UX 模型 = 2D Miller columns + 欄內垂直 stack**（使用者選定 + 補充）| 水平=navigate、垂直=reference，最像專業 workspace |
| D2 | **單一 axis-generic `ResizableStack` primitive 組合兩次**（外水平、內垂直）| 一套抽象，DRY 到底，加 block 類型零引擎改動 |
| D3 | **`PanelWorkspace` 取代全部 `*DetailRouter` + `*DetailPresentation`** | 消除 N 份重複；單一 SoT coordinator |
| D4 | drill-in → `replaceColumns(after:)`（Miller 截斷）；split/pin → `stack(in:)` | 水平=深入導航、垂直=並列參照，語意清晰 |
| D5 | 每 block ✕ → `closeBlock`；欄空自動收；關欄串聯右側子欄 | 子欄是父欄選取衍生，孤兒欄無意義；invariant 無空欄 |
| D6 | panel 為 root master 之 **同層 sibling**（HStack 內），**非** push 進 NavigationStack | 結構上根治 `413912b3` 的 remount pop bug；本引擎**正確取代**該權宜 hack |
| D7 | block 需自帶 toolbar 者（player 設定鍵）→ 該 block `wrapInNavigation: true` 自帶 `NavigationStack` | 範圍化 toolbar，沿用 podcast 既有解法 |
| D8 | 複用 `DraggableDivider`/`MacDetailPanelMetrics`/`MacColumnResizeCursor`，泛化加 `axis` | 不重造拖拉欄 |
| D9 | resolver 集中（`PanelKind` 封閉）→ 引擎 core 不依賴 feature view | 可獨立單元測試、無循環依賴、最好擴展 |
| D10 | 範圍僅 `regular`；compact 完全不動 | 縮小 blast radius；iPhone 體驗已穩定 |

## 遷移階段（phased，每階段獨立 commit + review gate）

1. **引擎 core** — `PanelKind` / `Block` / `WorkColumn` / `PanelWorkspace` coordinator，**TDD**（純值型 + coordinator 操作，無 UI）。
2. **`ResizableStack` primitive + `DraggableDivider` 加 axis** — 容器、divider 垂直化、chrome(✕)、水平溢出 scroll。
3. **遷移 podcast**（series→episodes→player 三層水平展示）→ 刪 `PodcastDetailPresentation` / `PodcastDetailRouter` / `BookshelfView.selectedSeriesRemoteId` hack。
4. **遷移 vocab**（word detail + today-review）→ 刪 `DetailRouter` regular 分支 / `NotebookDetailPresentation` regular 分支。**驗證垂直軸**：word detail 的「linked word」→ 欄內垂直 stack（具體 vertical 用例，避免未測能力）。
5. **折入 fluidity audit findings**（背景 workflow 產出）— 引擎須避開 `.id` teardown、layout thrash；逐項對照。
6. **清死碼 + docs sync**（`feature_boundary/{podcast,bookshelf,vocabulary}.md`、`tech_index.md`、`product_surface.md`）。

## 行為界定（明確化，避免被當 bug）

- compact（iPhone）：行為**完全不變**。本引擎只在 `regular` 生效。
- 切 section：workspace 隸屬該 section，切走即 `reset()`（不跨 section 保留欄）。
- 空選態：無欄時 root master 佔滿；開第一欄才出現水平 stack。
- 欄寬/塊高使用者調整後持久化；雙擊 divider 回預設（沿用既有）。

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| 水平 `ScrollView` × `DraggableDivider` global-coord 拖拉手勢衝突 | divider 用 `highPriorityGesture`（既有）；階段 2 實機驗證 Catalyst trackpad |
| 2D 同時調整大小的狀態複雜度 | 尺寸 state 收斂於 `WorkColumn.width` / `Block.height`，coordinator 為 SoT；container 只讀 |
| 大改動破壞已穩定的 vocab 500-row 列表 | 階段化；compact 路徑零改動；每階段 review gate PASS 才下一步 |
| 未測的垂直能力（YAGNI 反向）| 階段 4 強制一個真實 vertical 用例（linked word），TDD 覆蓋 |

## 成功標準

- [ ] 一套引擎取代 ≥4 份重複 presentation/router，淨刪行數 > 新增重複。
- [ ] podcast series→episodes→player 三欄水平同時可見、各欄可拖寬、各欄 ✕ 串聯關閉、drawerReveal 動畫。
- [ ] 至少一個欄內垂直 stack 用例（vocab linked word）可疊、可獨立 ✕、垂直動畫。
- [ ] compact（iPhone）行為與遷移前逐項等價（無迴歸）。
- [ ] Catalyst + iPhone 雙平台 `ios_build.sh` 綠燈；i18n/docs lint 0 error。
- [ ] 使用者實機確認：堆疊/關閉/動畫手感達專業 app 水準。
