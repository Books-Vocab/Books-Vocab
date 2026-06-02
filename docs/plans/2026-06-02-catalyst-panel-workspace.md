<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksBrowser/Platform/PanelWorkspace/
  - ios/BooksBrowser/Views/Podcast/
  - ios/BooksBrowser/Views/Vocabulary/
  - ios/BooksBrowser/Views/Bookshelf/
verified_against: bb5c4b8a
-->

# Catalyst 2D 可堆疊 Block Workspace Implementation Plan

> **執行方式:** 使用 phased-workflow skill，所有 agent 皆 opus、背景執行。逐 task review（鐵律4）PASS 才下一個。

**Goal:** 把 Catalyst/iPad regular 的 master-detail 收斂成一套 2D 可堆疊 block workspace 引擎（水平 Miller columns + 欄內垂直 stack），每 block 可 ✕ 關閉 + 動畫；取代 4 份重複的 `*DetailPresentation`/`*DetailRouter`。iPhone compact 零改動。

**Architecture:** 單一 `PanelWorkspace` @Observable coordinator 持 `columns: [WorkColumn]`（每欄 `blocks: [Block]`）為 SoT。`PanelKind` 封閉 enum 承載 payload，集中 `PanelHost` resolver 解耦 feature view。容器 `PanelWorkspaceContainer` 於 regular 渲染 root + 水平 `ScrollView` of 可拖寬欄，欄內 `VerticalBlockStack` 渲染可拖高 block；axis-generic `ResizableDivider` 雙軸共用。panel 為 root 同層 sibling（非 push）+ 穩定 identity → 根治 `413912b3` remount pop bug。

**Tech Stack:** SwiftUI / Mac Catalyst / 既有 `LayoutMode`/`AppMotion`/`AppSpacing`/`AppRadius`；新 `BlockStackMetrics`/`ResizableDivider`（重寫自 `DraggableDivider`）。

**Spec:** `docs/specs/2026-06-02-catalyst-panel-workspace-design.md`

**測試說明:** coordinator 為純值/狀態邏輯 → 全程 TDD（Swift Testing `@Test`/`#expect`，對齊 `PodcastSeriesActivationTests`）。View 層走 `ios_build.sh` + lint + 實機 Catalyst/iPhone 驗證。新檔置於 synchronized group 自動納入 target（無需改 pbxproj）。每 task 後派 opus code-reviewer。**不主動跑 `ios_test.sh`**（鐵律：含 worktree subagent，需使用者明示）；coordinator 邏輯由 reviewer 靜態確認 + 使用者可選跑 test。

---

## Phase 1 — 引擎 core（純值 + coordinator，TDD）

### Task 1: `PanelKind` + identity 型別

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelKind.swift`
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelModels.swift`

- [ ] **Step 1: 寫 failing test**（`ios/BooksBrowserTests/PanelWorkspace/PanelModelsTests.swift`）
```swift
import Testing
@testable import BooksBrowser

@Suite struct PanelModelsTests {
    @Test func blockIdentityIsStableAndUnique() {
        let a = Block(kind: .podcastEpisode(remoteID: "ep1"))
        let b = Block(kind: .podcastEpisode(remoteID: "ep1"))
        #expect(a.id != b.id)              // 同 kind 不同實例 → 不同身分
        #expect(a.kind == b.kind)
    }
    @Test func columnDefaultsToSingleBlock() {
        let c = WorkColumn(kind: .wordDetail(entryID: "w1"))
        #expect(c.blocks.count == 1)
        #expect(c.blocks[0].kind == .wordDetail(entryID: "w1"))
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**（型別不存在）

- [ ] **Step 3: 寫最小實作**
```swift
// PanelKind.swift
import Foundation

/// 每個 block 承載的 payload。擴展點：加 case 即加一種 block 類型，引擎零改動。
enum PanelKind: Equatable, Hashable {
    case podcastSeries(remoteID: String)
    case podcastEpisode(remoteID: String)
    case wordDetail(entryID: String)
    case reviewSession(id: UUID)
    case linkedWord(entryID: String)   // 垂直軸用例（Phase 4）
}

struct BlockID: Hashable { let raw = UUID() }
struct ColumnID: Hashable { let raw = UUID() }
```
```swift
// PanelModels.swift
import CoreGraphics

/// 垂直堆疊中的單一 block。
struct Block: Identifiable, Equatable {
    let id = BlockID()
    let kind: PanelKind
    var height: CGFloat? = nil          // nil = flexible 均分
}

/// 一欄 = 一個垂直 block stack + 欄寬。
struct WorkColumn: Identifiable, Equatable {
    let id = ColumnID()
    var blocks: [Block]
    var width: CGFloat = MacDetailPanelMetrics.defaultWidth

    init(blocks: [Block]) { self.blocks = blocks }
    init(kind: PanelKind) { self.blocks = [Block(kind: kind)] }
}
```

- [ ] **Step 4: 跑 test 確認通過**（reviewer 靜態確認 / 使用者可選 `ios_test.sh`）
- [ ] **Step 5: Commit** `ios: add PanelKind + Block/WorkColumn value models`

---

### Task 2: `PanelWorkspace` coordinator（2D 管理，TDD invariant）

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelWorkspace.swift`
- Test: `ios/BooksBrowserTests/PanelWorkspace/PanelWorkspaceTests.swift`

- [ ] **Step 1: 寫 failing test**（涵蓋全部不變式）
```swift
import Testing
@testable import BooksBrowser

@MainActor @Suite struct PanelWorkspaceTests {
    @Test func openColumnFromRootTruncatesAllAndAppends() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        let c2 = ws.openColumn(.podcastEpisode(remoteID: "e1"), after: c1)
        #expect(ws.columns.count == 2)
        // 從 root 再開 → 截斷全部
        let c3 = ws.openColumn(.podcastSeries(remoteID: "s2"), after: nil)
        #expect(ws.columns.count == 1)
        #expect(ws.columns[0].id == c3)
    }
    @Test func openColumnAfterParentTruncatesRightSiblings() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        _ = ws.openColumn(.podcastEpisode(remoteID: "e1"), after: c1)
        // 在 c1 重新 drill → 截斷 e1 欄，換新欄
        let c2b = ws.openColumn(.podcastEpisode(remoteID: "e2"), after: c1)
        #expect(ws.columns.count == 2)
        #expect(ws.columns[1].id == c2b)
    }
    @Test func closeColumnCascadesRight() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        _ = ws.openColumn(.podcastEpisode(remoteID: "e1"), after: c1)
        ws.closeColumn(c1)                 // 關父欄 → 串聯關右側
        #expect(ws.columns.isEmpty)
    }
    @Test func stackAppendsBlockVertically() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: "w1"), after: nil)
        let b2 = ws.stack(.linkedWord(entryID: "w2"), in: c1)
        #expect(ws.columns[0].blocks.count == 2)
        #expect(b2 != nil)
    }
    @Test func closeBlockRemovesIt_AndCollapsesEmptyColumnWithCascade() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: "w1"), after: nil)
        let b2 = ws.stack(.linkedWord(entryID: "w2"), in: c1)!
        let c2 = ws.openColumn(.reviewSession(id: UUID()), after: c1)
        ws.closeBlock(b2)                  // 移除垂直 block，欄不空 → 欄保留
        #expect(ws.columns[0].blocks.count == 1)
        #expect(ws.columns.count == 2)
        let onlyBlock = ws.columns[0].blocks[0].id
        ws.closeBlock(onlyBlock)           // 欄空 → 收欄 + 串聯關右側 c2
        #expect(ws.columns.isEmpty)
        _ = c2
    }
    @Test func resetClearsAll() {
        let ws = PanelWorkspace()
        _ = ws.openColumn(.wordDetail(entryID: "w1"), after: nil)
        ws.reset()
        #expect(ws.columns.isEmpty)
    }
    @Test func invariantNoEmptyColumns() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: "w1"), after: nil)
        ws.closeBlock(ws.columns[0].blocks[0].id)
        #expect(ws.columns.allSatisfy { !$0.blocks.isEmpty })
        _ = c1
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 寫最小實作**
```swift
import SwiftUI

/// 2D block workspace 的堆疊模式管理 — 唯一 SoT。
/// 不變式：無空欄；`columns` 順序即視覺左→右；關欄串聯右側子欄。
@Observable @MainActor
final class PanelWorkspace {
    private(set) var columns: [WorkColumn] = []

    // MARK: 水平軸（navigate / drill，Miller 截斷語意）
    /// 在 `after` 欄之後開新欄並截斷其右側；`after == nil` 視為 root → 截斷全部。
    @discardableResult
    func openColumn(_ kind: PanelKind, after columnID: ColumnID?) -> ColumnID {
        let keep: Int
        if let columnID, let idx = columns.firstIndex(where: { $0.id == columnID }) {
            keep = idx + 1
        } else {
            keep = 0
        }
        columns = Array(columns.prefix(keep))
        let col = WorkColumn(kind: kind)
        columns.append(col)
        return col.id
    }

    /// 關閉該欄及其右側全部（子欄是父欄選取衍生）。
    func closeColumn(_ id: ColumnID) {
        guard let idx = columns.firstIndex(where: { $0.id == id }) else { return }
        columns = Array(columns.prefix(idx))
    }

    // MARK: 垂直軸（split / pin / reference）
    @discardableResult
    func stack(_ kind: PanelKind, in columnID: ColumnID) -> BlockID? {
        guard let idx = columns.firstIndex(where: { $0.id == columnID }) else { return nil }
        let block = Block(kind: kind)
        columns[idx].blocks.append(block)
        return block.id
    }

    /// 移除 block；欄空 → 收欄並串聯關右側（維持「無空欄」不變式）。
    func closeBlock(_ id: BlockID) {
        guard let cIdx = columns.firstIndex(where: { $0.blocks.contains(where: { $0.id == id }) }) else { return }
        columns[cIdx].blocks.removeAll { $0.id == id }
        if columns[cIdx].blocks.isEmpty {
            columns = Array(columns.prefix(cIdx))
        }
    }

    func reset() { columns = [] }
}
```
> **YAGNI 收斂**：spec 曾列 `replaceColumns(after:)` — 與 `openColumn(after:)`（已截斷再 append）語意重複，移除，drill 一律走 `openColumn`。

- [ ] **Step 4: 跑 test 確認通過**
- [ ] **Step 5: Commit** `ios: add PanelWorkspace 2D stacking coordinator (TDD)`

---

## Phase 2 — Primitives & 容器

### Task 3: `BlockStackMetrics` + `ResizableDivider`（axis-generic，重寫）

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/BlockStackMetrics.swift`
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/ResizableDivider.swift`
- Test: `ios/BooksBrowserTests/PanelWorkspace/ResizableDividerClampTests.swift`

> 舊 `DraggableDivider`（`MacDividerHandle.swift`）**保留不動**（仍被 `NotebookDetailPresentation`/`PodcastDetailPresentation` 使用），待 Phase 6 連同舊 presentation 一併刪除。新 `ResizableDivider` 為雙軸重寫。

- [ ] **Step 1: 寫 failing test**（clamp 純函式）
```swift
import Testing
@testable import BooksBrowser
@Suite struct ResizableDividerClampTests {
    @Test func clampsWithinBounds() {
        #expect(ResizableDivider.clamp(500, to: 280...600) == 500)
        #expect(ResizableDivider.clamp(100, to: 280...600) == 280)
        #expect(ResizableDivider.clamp(999, to: 280...600) == 600)
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 寫最小實作**
```swift
// BlockStackMetrics.swift — 垂直堆疊度量（鏡射 MacDetailPanelMetrics 但 height 語意）
import CoreGraphics
enum BlockStackMetrics {
    static let minHeight: CGFloat = 160
    static let defaultHeight: CGFloat = 320
    static let topMinHeight: CGFloat = 120     // 上方 block 至少保留
    static let hitAreaHeight: CGFloat = 8      // 鏡射 hitAreaWidth=8
}
```
```swift
// ResizableDivider.swift — axis-generic 拖拉欄（重寫自 DraggableDivider）
import SwiftUI

struct ResizableDivider: View {
    let axis: Axis                       // .horizontal → 調寬；.vertical → 調高
    @Binding var length: CGFloat
    @Binding var dragLength: CGFloat?
    let bounds: ClosedRange<CGFloat>
    var onDoubleClick: () -> Void = {}

    @Environment(\.appTheme) private var theme
    @GestureState private var isActiveDrag = false
    @State private var dragStart: CGFloat = 0

    static func clamp(_ v: CGFloat, to r: ClosedRange<CGFloat>) -> CGFloat {
        Swift.min(Swift.max(v, r.lowerBound), r.upperBound)
    }

    var body: some View {
        Rectangle()
            .fill(isActiveDrag ? theme.palette.divider.opacity(MacDetailPanelMetrics.dividerActiveOpacity) : .clear)
            .frame(width: axis == .horizontal ? MacDetailPanelMetrics.hitAreaWidth : nil,
                   height: axis == .vertical ? BlockStackMetrics.hitAreaHeight : nil)
            .contentShape(Rectangle())
            .overlay(alignment: .center) {
                Rectangle()
                    .fill(theme.palette.divider.opacity(isActiveDrag ? MacDetailPanelMetrics.dividerActiveOpacity : MacDetailPanelMetrics.dividerIdleOpacity))
                    .frame(width: axis == .horizontal ? 1 : nil, height: axis == .vertical ? 1 : nil)
            }
            .highPriorityGesture(drag)
            .onChange(of: isActiveDrag) { _, active in
                if !active, let d = dragLength { length = d; dragLength = nil }
            }
            #if targetEnvironment(macCatalyst)
            .onTapGesture(count: 2) { onDoubleClick() }
            .overlay { MacColumnResizeCursor(axis: axis) }   // Task: cursor 加 axis
            #endif
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 3, coordinateSpace: .global)
            .updating($isActiveDrag) { _, s, _ in s = true }
            .onChanged { v in
                if dragLength == nil { dragStart = length }
                // 水平：欄在右，往左拖變寬 → 減 translation.width（鏡射舊 divider）
                // 垂直：block 在下，往上拖變高 → 減 translation.height
                let delta = axis == .horizontal ? v.translation.width : v.translation.height
                dragLength = Self.clamp(dragStart - delta, to: bounds)
            }
            .onEnded { _ in if let d = dragLength { length = d }; dragLength = nil }
    }
}
```
> `MacColumnResizeCursor` 加 `axis` 參數：horizontal → `.resizeLeftRight`，vertical → `.resizeUpDown`（NSCursor 經 Catalyst）。

- [ ] **Step 4:** `ios_build.sh` exit 0（含 `--catalyst`）。test 綠。
- [ ] **Step 5: Commit** `ios: add BlockStackMetrics + axis-generic ResizableDivider (TDD)`

---

### Task 4: `PanelProxy` + `PanelHost` resolver

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelProxy.swift`
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelHost.swift`

- [ ] **Step 1:** `PanelProxy` — block 內容觸發導航/自關的握把（知道自身 column）：
```swift
@MainActor struct PanelProxy {
    let columnID: ColumnID
    let blockID: BlockID
    private let ws: PanelWorkspace
    init(columnID: ColumnID, blockID: BlockID, workspace: PanelWorkspace) {
        self.columnID = columnID; self.blockID = blockID; self.ws = workspace
    }
    func openChildColumn(_ kind: PanelKind) { ws.openColumn(kind, after: columnID) }
    func stackHere(_ kind: PanelKind) { _ = ws.stack(kind, in: columnID) }
    func closeSelf() { ws.closeBlock(blockID) }
}
```

- [ ] **Step 2:** `PanelHost` — 集中 resolver（`PanelKind` 封閉 → 引擎 core 不 import feature view）：
```swift
struct PanelHost: View {
    let kind: PanelKind
    let proxy: PanelProxy
    var body: some View {
        switch kind {
        // Phase 3 接 podcast；Phase 4 接 vocab。先放 placeholder 確保編譯。
        default: Color.clear
        }
    }
}
```
> resolver 分支於 Phase 3/4 逐步填入，避免一次大爆。

- [ ] **Step 3:** `ios_build.sh` exit 0。
- [ ] **Step 4: Commit** `ios: add PanelProxy + PanelHost resolver skeleton`

---

### Task 5: `BlockChrome`（✕）+ `VerticalBlockStack`

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/BlockChrome.swift`
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/VerticalBlockStack.swift`

- [ ] **Step 1:** `BlockChrome` — 每 block 頂部含 ✕（i18n：`L10n.string` label）：
```swift
struct BlockChrome<Content: View>: View {
    let onClose: () -> Void
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button(action: onClose) { Image(systemName: "xmark") }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.string("關閉"))   // 既有字串或新增
            }
            .padding(AppSpacing.s2)
            content
        }
    }
}
```

- [ ] **Step 2:** `VerticalBlockStack` — 一欄內垂直堆疊 block + 欄內 `ResizableDivider(.vertical)`：
```swift
struct VerticalBlockStack: View {
    @Bindable var workspace: PanelWorkspace
    let column: WorkColumn
    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(column.blocks.enumerated()), id: \.element.id) { idx, block in
                if idx > 0 {
                    ResizableDivider(axis: .vertical,
                                     length: bindingHeight(block),
                                     dragLength: .constant(nil),       // 簡化：階段內精修
                                     bounds: BlockStackMetrics.minHeight...600)
                }
                BlockChrome(onClose: { workspace.closeBlock(block.id) }) {
                    PanelHost(kind: block.kind,
                              proxy: PanelProxy(columnID: column.id, blockID: block.id, workspace: workspace))
                }
                .frame(maxHeight: block.height ?? .infinity)
                .transition(.statusRowReveal)            // 垂直 insert/remove
            }
        }
        .animation(AppMotion.panelState, value: column.blocks)
    }
    // height binding：寫回 workspace.columns[col].blocks[block].height
}
```
> block height 持久化於 `Block.height`（coordinator 為 SoT）；binding helper 寫回對應 index。

- [ ] **Step 3:** `ios_build.sh` exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 4: Commit** `ios: add BlockChrome + VerticalBlockStack`

---

### Task 6: `PanelWorkspaceContainer`（水平捲動 + 欄 + 動畫）

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelWorkspaceContainer.swift`

- [ ] **Step 1:** 容器 — regular 渲染 root + 水平欄；compact 只渲染 root：
```swift
struct PanelWorkspaceContainer<Root: View>: View {
    @Bindable var workspace: PanelWorkspace
    let layoutMode: LayoutMode
    @ViewBuilder var root: () -> Root

    var body: some View {
        if layoutMode.usesInlineDetail {
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 0) {
                        root()
                            .frame(minWidth: MacDetailPanelMetrics.leftMinWidth)
                        ForEach(workspace.columns) { column in
                            ResizableDivider(axis: .horizontal,
                                             length: bindingWidth(column),
                                             dragLength: .constant(nil),     // 階段內精修即時拖拉
                                             bounds: MacDetailPanelMetrics.minWidth...MacDetailPanelMetrics.maxWidth,
                                             onDoubleClick: { resetWidth(column) })
                            VerticalBlockStack(workspace: workspace, column: column)
                                .frame(width: column.width)
                                .id(column.id)
                                .transition(.drawerReveal)        // 水平 insert/remove
                        }
                    }
                    .animation(AppMotion.panelState, value: workspace.columns)
                }
                .onChange(of: workspace.columns.last?.id) { _, last in
                    if let last { withAnimation(AppMotion.panelState) { proxy.scrollTo(last, anchor: .trailing) } }
                }
            }
        } else {
            root()           // compact：drill 走既有 NavigationStack push（零改動）
        }
    }
    // bindingWidth：寫回 workspace.columns[idx].width；resetWidth：回 defaultWidth
}
```
> **INV 驗證點（D6×D7）**：`ForEach(workspace.columns)` 以穩定 `column.id` 為 identity；block 內 `NavigationStack`（若有，Task 7 player）深度恆 0。開新欄只 append 末端、不改既存欄 identity/樹位置 → 既存欄不 remount。

- [ ] **Step 2:** `ios_build.sh` exit 0（`--catalyst` 必跑）。
- [ ] **Step 3: Commit** `ios: add PanelWorkspaceContainer horizontal Miller-column shell`

---

## Phase 3 — 遷移 podcast（3 層水平展示 + 刪舊）

### Task 7: PanelHost 接 podcast + episode/series 內容

**Files:**
- Modify: `ios/BooksBrowser/Platform/PanelWorkspace/PanelHost.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastPlayerView.swift`（沿用 `wrapInNavigation`）

- [ ] **Step 1:** `PanelHost` 補 podcast 分支：
  - `.podcastSeries(remoteID)` → 該 series 的集數列表（內部 row 點擊 `proxy.openChildColumn(.podcastEpisode(...))`）。
  - `.podcastEpisode(remoteID)` → `PodcastPlayerView(episodeId: remoteID, wrapInNavigation: true)`（自帶 NavigationStack host 設定鍵，深度恆 0）。
- [ ] **Step 2:** 集數列表 row 在 workspace 模式下用 `proxy.openChildColumn`，取代舊 `PodcastNavRoute` push（compact 仍用舊 push）。
- [ ] **Step 3:** `ios_build.sh --catalyst` exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 4: Commit** `ios: resolve podcast series/episode panels in PanelHost`

---

### Task 8: 接線 BookshelfView/section root + 刪舊 podcast detail

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`
- Modify: `ios/BooksBrowser/ContentView.swift`（bookshelf section 包 `PanelWorkspaceContainer`）
- Delete: `ios/BooksBrowser/Views/Podcast/PodcastDetailPresentation.swift`
- Delete: `ios/BooksBrowser/Views/Podcast/PodcastDetailRouter.swift`

- [ ] **Step 1:** bookshelf section root 包進 `PanelWorkspaceContainer(workspace:layoutMode:) { BookshelfView() }`。series 卡片點擊 regular → `workspace.openColumn(.podcastSeries(...), after: nil)`；compact → 維持既有 NavigationStack push。
- [ ] **Step 2:** 移除 `BookshelfView.selectedSeriesRemoteId` master-pane hack（`413912b3`）+ `PodcastSeriesActivation`/`PodcastEpisodeActivation`（被 workspace 取代；保留若 compact push 仍需 route enum）。
- [ ] **Step 3:** 刪 `PodcastDetailPresentation` / `PodcastDetailRouter` + 所有 caller（`.podcastDetailPresentation` / `\.podcastDetailRouter` 注入）。grep 確認零殘留。
- [ ] **Step 4:** `ios_build.sh --catalyst` + iPhone sim 雙跑 exit 0 + `i18n_lint.sh` 0 + 同步檢查 `.claude/skills/`、`docs/reference/product_surface.md`、`tech_index.md` 引用（鐵律：改 user-facing 介面同 PR 同步）。
- [ ] **Step 5: Commit** `ios: migrate podcast to PanelWorkspace, remove bespoke detail presentation`

---

### Task 9: 實機驗證 — NAVDBG 無 remount + trackpad 手勢（使用者 gate）

- [ ] **Step 1（使用者）:** Catalyst 跑：sidebar→點 series（開欄1）→點集數（開欄2 player）→再點別集（欄2 換）→於欄1 再點別 series（截斷欄2、開新欄）。
- [ ] **Step 2（使用者）:** 觀察 NAVDBG / `onAppear`：**開第 3 欄時欄 1/2 內容不二次 `onAppear`**（INV 不變式，根治 `413912b3`）。
- [ ] **Step 3（使用者）:** 各欄 ✕ → 串聯關右側；drawerReveal 動畫順；拖欄寬跟手；**兩指水平捲動 vs 拖 divider 不誤觸**。
- [ ] **Step 4（使用者）:** iPhone：點 series/集數仍 push 全螢幕，行為不變。
- [ ] **Step 5:** 若 remount 重現 → app-debug 根因（NAVDBG 探針），修正 identity/樹位置後重驗。PASS 才進 Phase 4。

---

## Phase 4 — 遷移 vocab + 證垂直軸

### Task 10: PanelHost 接 vocab（word detail / review）

**Files:**
- Modify: `ios/BooksBrowser/Platform/PanelWorkspace/PanelHost.swift`

- [ ] **Step 1:** 補分支：`.wordDetail(entryID)` → `WordDetailSheet(wrapInNavigation:false, showsInlineChrome:false)`（鏡射 `NotebookDetailPresentation.inlineDetailPanel`）；`.reviewSession(id)` → `TodayReviewPhaseView(...)`；`.linkedWord(entryID)` → linked word detail（Task 12）。entryID→`VocabularyEntry` 查詢經既有 context。
- [ ] **Step 2:** `ios_build.sh --catalyst` exit 0。
- [ ] **Step 3: Commit** `ios: resolve vocab word/review panels in PanelHost`

---

### Task 11: 接線 NotebookListView + 刪舊 vocab detail（regular 分支）

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookDetailPresentation.swift`（移除 regular 分支，僅留 compact sheet）
- Modify: `ios/BooksBrowser/Platform/DetailRouter.swift`（評估是否整體由 workspace 取代）

- [ ] **Step 1:** notebook section root 包 `PanelWorkspaceContainer { NotebookListView() }`。word 點擊 regular → `workspace.openColumn(.wordDetail(...))`；today-review → `workspace.openColumn(.reviewSession(...))`。compact → 維持既有 sheet/fullScreenCover（`NotebookDetailPresentation` else 分支保留）。
- [ ] **Step 2:** 移除 `NotebookDetailPresentation` 的 `usesInlineDetail` 分支（safeAreaInset 那段）；`DetailRouter` 若 regular 已全由 workspace 取代則刪、compact 仍需則保留 compact 用法。grep 確認。
- [ ] **Step 3:** `ios_build.sh --catalyst` + iPhone sim 雙跑 exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 4: Commit** `ios: migrate vocab word/review to PanelWorkspace on regular`

---

### Task 12: 垂直軸用例 — linked word 欄內疊 + 刪舊 linked 呈現

**Files:**
- Modify: `ios/BooksBrowser/Platform/PanelWorkspace/PanelHost.swift`
- Modify: word detail 內 linked word 觸發點（grep `linkedOverlayCard` caller）

- [ ] **Step 1:** word detail 內點 linked word（regular）→ `proxy.stackHere(.linkedWord(entryID:))` → 同欄垂直疊一個 linked word block，可獨立 ✕、`statusRowReveal` 動畫。
- [ ] **Step 2:** **移除舊 linked 呈現**（`linkedOverlayCard` transition + 其 overlay 路徑），避免兩套並存（spec 成功標準）。compact 的 linked 呈現維持既有（若有）。
- [ ] **Step 3:** `ios_build.sh --catalyst` exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 4: 實機驗證（使用者）:** regular 點 linked word → 同欄下方疊出、可獨立關、垂直動畫順；compact 不變。
- [ ] **Step 5: Commit** `ios: stack linked word vertically in PanelWorkspace, remove legacy overlay`

---

## Phase 5 — 折入 fluidity audit findings（perf）

### Task 13: 依 audit 排序逐項處理

**Files:** 依 audit 輸出（背景 workflow `catalyst-fluidity-audit`）。

- [ ] **Step 1:** 讀 workflow 排序結果（confirmed/needs-runtime），逐項對照新引擎是否已順帶解決（如 `ContentView.swift:82 .id(selectedSection)` teardown、layout thrash、image decode）。
- [ ] **Step 2:** 對「新引擎未解決且 confirmed」的 top-rank 項，逐項 TDD/修正 + reviewer PASS + 實機。**逐項**，不批次（鐵律4）。
- [ ] **Step 3:** 每項獨立 commit `ios: perf — <finding>`。
> 具體 task 清單於 audit 完成後 append 至本 plan。

---

## Phase 6 — 清死碼 + docs sync

### Task 14: 刪舊 divider + 死碼

**Files:**
- Delete（若已零 caller）: `ios/BooksBrowser/Views/Vocabulary/MacDividerHandle.swift`（舊 `DraggableDivider`）
- 評估: `WordDetailPresentation.swift` regular 分支、`PodcastSeriesActivation`/`PodcastEpisodeActivation`、`MacDetailPanelMetrics` 未用常數

- [ ] **Step 1:** grep `DraggableDivider`/`podcastDetailRouter`/`selectedSeriesRemoteId` 零殘留才刪。
- [ ] **Step 2:** `ios_build.sh --catalyst` + iPhone 雙跑 exit 0。
- [ ] **Step 3: Commit** `ios: remove legacy DraggableDivider + dead detail-presentation code`

---

### Task 15: Doc sync

- [ ] 派 background doc-sync agent：更新 `feature_boundary/{podcast,bookshelf,vocabulary}.md`（PanelWorkspace 2D 堆疊架構）+ `tech_index.md`（新 `Platform/PanelWorkspace/` 模組）+ `product_surface.md`（Catalyst 可堆疊 block workspace）。bump verified_against、跑 `docs_lint.sh`。

---

## 完成準則

- Phase 1–4 約 12 code commit + Phase 5 perf commits + 1 doc commit。
- `ios_build.sh`（sim + `--catalyst`）/ `i18n_lint.sh` / `docs_lint.sh` 全 0 error。
- coordinator 全 invariant test 綠（Phase 1）。
- 每 task opus code-review PASS。
- **NAVDBG 實機驗證無 remount 迴歸**（Task 9）；trackpad 手勢正確；linked word 垂直疊可獨立關。
- compact（iPhone）行為逐項等價、無迴歸。
- 淨刪行數 > 新增重複（一套引擎取代 ≥4 份）。
- 使用者實機確認：堆疊/關閉/動畫手感達專業 app 水準。
