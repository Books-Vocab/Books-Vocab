import Foundation
import Testing
@testable import BooksBrowser

@Suite("PanelModels")
struct PanelModelsTests {
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
