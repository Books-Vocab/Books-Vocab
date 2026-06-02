import Foundation
import Testing
@testable import BooksBrowser

@MainActor
@Suite("PanelWorkspace")
struct PanelWorkspaceTests {
    @Test func openColumnFromRootTruncatesAllAndAppends() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        _ = ws.openColumn(.podcastEpisode(remoteID: "e1"), after: c1)
        #expect(ws.columns.count == 2)
        let c3 = ws.openColumn(.podcastSeries(remoteID: "s2"), after: nil)   // 從 root 再開 → 截斷全部
        #expect(ws.columns.count == 1)
        #expect(ws.columns[0].id == c3)
    }

    @Test func openColumnAfterParentTruncatesRightSiblings() {
        let ws = PanelWorkspace()
        let c1 = ws.openColumn(.podcastSeries(remoteID: "s1"), after: nil)
        _ = ws.openColumn(.podcastEpisode(remoteID: "e1"), after: c1)
        let c2b = ws.openColumn(.podcastEpisode(remoteID: "e2"), after: c1)   // 在 c1 重新 drill → 截斷 e1 欄
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
        _ = ws.openColumn(.reviewSession(entryIDs: []), after: c1)
        ws.closeBlock(b2)                  // 移除垂直 block，欄不空 → 欄保留
        #expect(ws.columns[0].blocks.count == 1)
        #expect(ws.columns.count == 2)
        let onlyBlock = ws.columns[0].blocks[0].id
        ws.closeBlock(onlyBlock)           // 欄空 → 收欄 + 串聯關右側
        #expect(ws.columns.isEmpty)
    }

    @Test func resetClearsAll() {
        let ws = PanelWorkspace()
        _ = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        ws.reset()
        #expect(ws.columns.isEmpty)
    }

    @Test func invariantNoEmptyColumns() {
        let ws = PanelWorkspace()
        _ = ws.openColumn(.wordDetail(entryID: UUID()), after: nil)
        ws.closeBlock(ws.columns[0].blocks[0].id)
        #expect(ws.columns.allSatisfy { !$0.blocks.isEmpty })
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
