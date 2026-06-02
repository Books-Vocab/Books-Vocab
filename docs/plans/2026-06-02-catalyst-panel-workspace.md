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
import Foundation
@testable import BooksBrowser

@Suite struct PanelModelsTests {
    @Test func blockIdentityIsStableAndUnique() {
        let a = Block(kind: .podcastEpisode(remoteID: "ep1"))
        let b = Block(kind: .podcastEpisode(remoteID: "ep1"))
        #expect(a.id != b.id)              // 同 kind 不同實例 → 不同身分
        #expect(a.kind == b.kind)
    }
    @Test func columnDefaultsToSingleBlock() {
        let w = UUID()
        let c = WorkColumn(kind: .wordDetail(entryID: w))
        #expect(c.blocks.count == 1)
        #expect(c.blocks[0].kind == .wordDetail(entryID: w))
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**（型別不存在）

- [ ] **Step 3: 寫最小實作**
```swift
// PanelKind.swift
import Foundation

/// 每個 block 承載的 payload。**value-pure**（Equatable/Hashable，無 @Model 物件）
/// → 供 SwiftUI 穩定 diff + coordinator 測試。live model 物件由 PanelHost resolver
/// 經 id 反查（Task 4/10），payload 只帶可重建的 id 快照。
/// 擴展點：加 case 即加一種 block 類型，引擎零改動。
enum PanelKind: Equatable, Hashable {
    case podcastSeries(remoteID: String)     // 經 service 反查（非 SwiftData）
    case podcastEpisode(remoteID: String)
    case wordDetail(entryID: UUID)           // VocabularyEntry.id: UUID
    case reviewSession(entryIDs: [UUID])     // entry-id 快照 → resolver 重建 TodayReviewSession
    case linkedWord(entryID: UUID)           // 垂直軸用例（Phase 4）
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
        let c1 = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        let b2 = ws.stack(.linkedWord(entryID: UUID()), in: c1)
        #expect(ws.columns[0].blocks.count == 2)
        #expect(b2 != nil)
    }
    @Test func closeBlockRemovesIt_AndCollapsesEmptyColumnWithCascade() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        let b2 = ws.stack(.linkedWord(entryID: UUID()), in: c1)!
        let c2 = ws.openColumn(.reviewSession(entryIDs: []), after: c1)
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
        _ = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        ws.reset()
        #expect(ws.columns.isEmpty)
    }
    @Test func invariantNoEmptyColumns() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        ws.closeBlock(ws.columns[0].blocks[0].id)
        #expect(ws.columns.allSatisfy { !$0.blocks.isEmpty })
        _ = c1
    }
    @Test func setWidthMutatesColumnByID() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        ws.setWidth(333, for: c1)
        #expect(ws.columns[0].width == 333)
    }
    @Test func setHeightMutatesBlockByID() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        let b2 = ws.stack(.linkedWord(entryID: UUID()), in: c1)!
        ws.setHeight(222, for: b2)
        #expect(ws.columns[0].blocks[1].height == 222)
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

    // MARK: 尺寸 mutator（container/divider 的 commit 寫回；coordinator 為 SoT）
    /// 兩者皆 by-id 查找（非 index）→ insert/remove 下穩定。供 ResizableDivider onCommit。
    func setWidth(_ width: CGFloat, for columnID: ColumnID) {
        guard let idx = columns.firstIndex(where: { $0.id == columnID }) else { return }
        columns[idx].width = width
    }
    func setHeight(_ height: CGFloat, for blockID: BlockID) {
        guard let cIdx = columns.firstIndex(where: { $0.blocks.contains(where: { $0.id == blockID }) }),
              let bIdx = columns[cIdx].blocks.firstIndex(where: { $0.id == blockID }) else { return }
        columns[cIdx].blocks[bIdx].height = height
    }

    func reset() { columns = [] }
}
```
> **YAGNI 收斂**：spec 曾列 `replaceColumns(after:)` — 與 `openColumn(after:)`（已截斷再 append）語意重複，移除，drill 一律走 `openColumn`。
> **mutator 為何 by-id**：`width`/`height` 寫回不能走 `@Bindable` 雙向綁進 `private(set)` array（編譯不過），由 divider `onCommit` callback 呼叫 by-id mutator（Task 3/5/6）。

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
// callback-based:不持有尺寸 state(coordinator 為 SoT)。parent 用 onDrag 更新
// 即時 transient、onCommit 寫回 coordinator。**無 .constant(nil) hack**。
import SwiftUI

struct ResizableDivider: View {
    let axis: Axis                       // .horizontal → 調寬；.vertical → 調高
    let currentLength: CGFloat           // 已 commit 的尺寸(唯讀,作 drag 起點)
    let bounds: ClosedRange<CGFloat>
    let onDrag: (CGFloat) -> Void        // 拖曳中即時值 → parent 更新 transient
    let onCommit: (CGFloat) -> Void      // 放開最終值 → coordinator setWidth/setHeight
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
            #if targetEnvironment(macCatalyst)
            .onTapGesture(count: 2) { onDoubleClick() }
            .overlay { MacColumnResizeCursor(axis: axis) }   // cursor 加 axis
            #endif
    }

    private func length(from translation: CGSize) -> CGFloat {
        // 水平：欄在右,往左拖變寬 → 減 translation.width(鏡射舊 divider)
        // 垂直：block 在下,往上拖變高 → 減 translation.height
        let delta = axis == .horizontal ? translation.width : translation.height
        return Self.clamp(dragStart - delta, to: bounds)
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 3, coordinateSpace: .global)
            .updating($isActiveDrag) { _, s, _ in s = true }
            .onChanged { v in
                if !isActiveDrag { dragStart = currentLength }   // 首幀記起點
                onDrag(length(from: v.translation))
            }
            .onEnded { v in onCommit(length(from: v.translation)) }
    }
}
```
> `MacColumnResizeCursor` 加 `axis` 參數：horizontal → `.resizeLeftRight`，vertical → `.resizeUpDown`（NSCursor 經 Catalyst）。`dragStart` 於 `onChanged` 首幀（`isActiveDrag` 尚 false）以 `currentLength` 記錄。

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

- [ ] **Step 2:** resolver 資料注入 — **panel 是 root 的 sibling（非 child）**，讀不到 root closure 的 `@Query`。故由 section wrapper 在 **container 層**經 environment 注入 live 資料：
```swift
// PanelDataEnvironment.swift
private struct PanelVocabEntriesKey: EnvironmentKey { static let defaultValue: [VocabularyEntry] = [] }
extension EnvironmentValues {
    var panelVocabEntries: [VocabularyEntry] {
        get { self[PanelVocabEntriesKey.self] }
        set { self[PanelVocabEntriesKey.self] = newValue }
    }
}
```
> currentUserID 經既有 `@Environment(\.authManager).userId`；podcast 經既有 service env（remoteId 反查，無 SwiftData）。

- [ ] **Step 3:** `PanelHost` — 集中 resolver（`PanelKind` 封閉 → 引擎 core 不 import feature view）：
```swift
struct PanelHost: View {
    let kind: PanelKind
    let proxy: PanelProxy
    @Environment(\.panelVocabEntries) private var entries
    @Environment(\.authManager) private var authManager

    var body: some View {
        switch kind {
        // Phase 3 接 podcast；Phase 4 接 vocab。先放 placeholder 確保編譯。
        default: Color.clear
        }
    }
}
```
> resolver 分支於 Phase 3/4 逐步填入。vocab 分支用 `entries.first { $0.id == entryID }` 反查 live `VocabularyEntry`（找不到 → `Color.clear` fallback）；review 用下方 `ReviewPanel` wrapper。

- [ ] **Step 4:** `ReviewPanel` — 由 entry-id 快照**建 session 一次**（穩定 UUID，避免每 render 重置）：
```swift
struct ReviewPanel: View {
    let entryIDs: [UUID]
    let allEntries: [VocabularyEntry]
    let currentUserID: String?
    let onClose: () -> Void
    @State private var session: TodayReviewSession?
    var body: some View {
        Group {
            if let session {
                TodayReviewPhaseView(session: session, allEntries: allEntries,
                                     currentUserID: currentUserID, onClose: onClose)
            } else { Color.clear }
        }
        .onAppear {
            if session == nil {
                let resolved = entryIDs.compactMap { id in allEntries.first { $0.id == id } }
                session = TodayReviewSession(entries: resolved)   // 建一次,Block.id 穩定故不重建
            }
        }
    }
}
```
> session 建立一次靠 `ReviewPanel` 的 `@State` + 外層 `ForEach(blocks, id: \.id)` 穩定 identity（Block.id 不變 → PanelHost/ReviewPanel 實例延續）。

- [ ] **Step 5:** `ios_build.sh` exit 0。
- [ ] **Step 6: Commit** `ios: add PanelProxy + PanelHost resolver + data injection + ReviewPanel`

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

- [ ] **Step 2:** `VerticalBlockStack` — 欄內垂直堆疊 block + callback `ResizableDivider(.vertical)`。`liveDrag` transient（一次只一條 divider 拖曳）：
```swift
struct VerticalBlockStack: View {
    let workspace: PanelWorkspace
    let column: WorkColumn
    @State private var liveDrag: (id: BlockID, value: CGFloat)?
    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(column.blocks.enumerated()), id: \.element.id) { idx, block in
                if idx > 0 {
                    ResizableDivider(
                        axis: .vertical,
                        currentLength: block.height ?? BlockStackMetrics.defaultHeight,
                        bounds: BlockStackMetrics.minHeight...600,
                        onDrag: { liveDrag = (block.id, $0) },
                        onCommit: { workspace.setHeight($0, for: block.id); liveDrag = nil })
                }
                BlockChrome(onClose: { workspace.closeBlock(block.id) }) {
                    PanelHost(kind: block.kind,
                              proxy: PanelProxy(columnID: column.id, blockID: block.id, workspace: workspace))
                }
                .frame(maxHeight: liveDrag?.id == block.id ? liveDrag!.value
                                  : (block.height ?? .infinity))
                .transition(.statusRowReveal)            // 垂直 insert/remove
            }
        }
        .animation(AppMotion.panelState, value: column.blocks)
    }
}
```
> 拖拉中 frame 讀 `liveDrag.value`（即時跟手）；放開 `onCommit` → `setHeight` 寫回 coordinator（SoT）、`liveDrag` 清空。`workspace` 為 @Observable class，傳值即共享參考。

- [ ] **Step 3:** `ios_build.sh` exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 4: Commit** `ios: add BlockChrome + VerticalBlockStack`

---

### Task 6: `PanelWorkspaceContainer`（水平捲動 + 欄 + 動畫）

**Files:**
- Create: `ios/BooksBrowser/Platform/PanelWorkspace/PanelWorkspaceContainer.swift`

- [ ] **Step 1:** 容器 — regular 渲染 root + 水平欄；compact 只渲染 root：
```swift
struct PanelWorkspaceContainer<Root: View>: View {
    let workspace: PanelWorkspace
    let layoutMode: LayoutMode
    @ViewBuilder var root: () -> Root
    @State private var liveDrag: (id: ColumnID, value: CGFloat)?

    var body: some View {
        if layoutMode.usesInlineDetail {
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 0) {
                        root()
                            .frame(minWidth: MacDetailPanelMetrics.leftMinWidth)
                        ForEach(workspace.columns) { column in
                            ResizableDivider(
                                axis: .horizontal,
                                currentLength: column.width,
                                bounds: MacDetailPanelMetrics.minWidth...MacDetailPanelMetrics.maxWidth,
                                onDrag: { liveDrag = (column.id, $0) },
                                onCommit: { workspace.setWidth($0, for: column.id); liveDrag = nil },
                                onDoubleClick: { workspace.setWidth(MacDetailPanelMetrics.defaultWidth, for: column.id) })
                            VerticalBlockStack(workspace: workspace, column: column)
                                .frame(width: liveDrag?.id == column.id ? liveDrag!.value : column.width)
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
- [ ] **Step 2:** 移除 `BookshelfView.selectedSeriesRemoteId` master-pane hack（`413912b3`）。**activation enum 規則（一次定義，貫穿 Task 8/14）**：compact push 路徑**保留** `PodcastSeriesActivation`/`PodcastEpisodeActivation`（仍驅動 NavigationStack push）；本 Task 只刪 regular 的 `selectedSeriesRemoteId` hack。enum 本身延至 **Task 14** 才刪，且僅在 grep 確認 compact 已不引用時。
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

- [ ] **Step 1:** `PanelHost` 補 vocab 分支（用 Task 4 注入的 `entries` + `authManager`）：
```swift
case .wordDetail(let entryID), .linkedWord(let entryID):
    if let entry = entries.first(where: { $0.id == entryID }) {
        WordDetailSheet(entry: entry, allEntries: entries,
                        wrapInNavigation: false, showsInlineChrome: false,
                        onClose: { proxy.closeSelf() })
    } else { Color.clear }                       // 已刪除 entry → fallback
case .reviewSession(let entryIDs):
    ReviewPanel(entryIDs: entryIDs, allEntries: entries,
                currentUserID: authManager.userId, onClose: { proxy.closeSelf() })
```
> `.wordDetail`/`.linkedWord` 共用同一 detail 呈現（差別僅觸發軸：word=水平開欄、linked=垂直疊，見 Task 12）。`WordDetailSheet` 簽章已驗證：`init(entry:allEntries:wrapInNavigation:showsInlineChrome:onClose:linkedCardStack:)`。

- [ ] **Step 2:** `ios_build.sh --catalyst` exit 0。
- [ ] **Step 3: Commit** `ios: resolve vocab word/review panels in PanelHost`

---

### Task 11: 接線 NotebookListView + 刪舊 vocab detail（regular 分支）

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/VocabWorkspaceSection.swift`（section wrapper）
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Modify: `ios/BooksBrowser/ContentView.swift`（notebooks section 改用 wrapper）
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookDetailPresentation.swift`（移除 regular 分支，僅留 compact sheet）
- Modify: `ios/BooksBrowser/Platform/DetailRouter.swift`（評估是否整體由 workspace 取代）

- [ ] **Step 1:** 新 `VocabWorkspaceSection` wrapper — **在 container 層**持有 workspace + `@Query allEntries`，注入 environment 給 sibling panel（panel 讀不到 root child 的 @Query）：
```swift
struct VocabWorkspaceSection: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Query private var allEntries: [VocabularyEntry]   // 同 NotebookListView predicate
    @State private var workspace = PanelWorkspace()
    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }
    var body: some View {
        PanelWorkspaceContainer(workspace: workspace, layoutMode: layoutMode) {
            NotebookListView()                         // root，經 env 取 workspace 開欄
        }
        .environment(\.panelVocabEntries, allEntries)  // 給 PanelHost resolver
        .environment(\.panelWorkspace, workspace)      // 給 NotebookListView 開欄
    }
}
```
（新增 `EnvironmentValues.panelWorkspace: PanelWorkspace?` key。）`ContentView` notebooks section 改 `VocabWorkspaceSection()`。
- [ ] **Step 2:** `NotebookListView` regular 路徑：word row 點擊 → `panelWorkspace?.openColumn(.wordDetail(entryID: entry.id), after: nil)`；today-review → `panelWorkspace?.openColumn(.reviewSession(entryIDs: entries.map(\.id)), after: nil)`。compact → 維持既有 sheet/fullScreenCover（`NotebookDetailPresentation` else 分支保留）。
- [ ] **Step 3:** 移除 `NotebookDetailPresentation` 的 `usesInlineDetail` 分支（safeAreaInset 那段）；`DetailRouter` 若 regular 已全由 workspace 取代則刪、compact 仍需則保留 compact 用法。grep 確認。
- [ ] **Step 4:** `ios_build.sh --catalyst` + iPhone sim 雙跑 exit 0 + `i18n_lint.sh` 0。
- [ ] **Step 5: Commit** `ios: migrate vocab word/review to PanelWorkspace on regular`

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

> **⛔ BLOCKED until `catalyst-fluidity-audit` workflow 產出落地。** phased-workflow agent 不得在 audit 結果 append 進本 Task 前啟動 Phase 5（否則無清單可做、空轉）。

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
