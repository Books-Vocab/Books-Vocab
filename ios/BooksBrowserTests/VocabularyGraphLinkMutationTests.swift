import Foundation
import Testing
@testable import BooksBrowser

@MainActor
struct VocabularyGraphLinkMutationTests {

    @Test func beginManualLink_insertsPlaceholderAndRejectsDuplicateTarget() {
        let source = makeEntry(cardId: "from-card", word: "source")
        let target = makeEntry(cardId: "to-card", word: "target")

        let pending = VocabularyGraphLinkMutation.beginManualLink(from: source, to: target)

        #expect(pending != nil)
        #expect(source.graphLinksByKind["shares_usage"]?.count == 1)
        #expect(source.graphLinksByKind["shares_usage"]?.first?.isPending == true)
        #expect(VocabularyGraphLinkMutation.beginManualLink(from: source, to: target) == nil)
    }

    @Test func commitManualLink_replacesPlaceholderWithResolvedLink() throws {
        let source = makeEntry(cardId: "from-card", word: "source")
        let target = makeEntry(cardId: "to-card", word: "target")
        let pending = try #require(VocabularyGraphLinkMutation.beginManualLink(from: source, to: target))

        VocabularyGraphLinkMutation.commitManualLink(
            pending,
            result: KGGraphLink(
                id: "link-1",
                fromId: "from-card",
                toId: "to-card",
                kind: "contrasts_with",
                confidence: 0.92,
                reason: "paired by user"
            ),
            on: source
        )

        #expect(source.graphLinksByKind["shares_usage"] == nil)
        let resolved = try #require(source.graphLinksByKind["contrasts_with"]?.first)
        #expect(resolved.id == "link-1")
        #expect(resolved.cardId == "to-card")
        #expect(resolved.word == "target")
        #expect(resolved.label == "對比")
        #expect(resolved.isPending == false)
    }

    @Test func rollbackManualLink_removesPlaceholder() throws {
        let source = makeEntry(cardId: "from-card", word: "source")
        let target = makeEntry(cardId: "to-card", word: "target")
        let pending = try #require(VocabularyGraphLinkMutation.beginManualLink(from: source, to: target))

        VocabularyGraphLinkMutation.rollbackManualLink(pending, on: source)

        #expect(source.graphLinksByKind.isEmpty)
    }

    @Test func removeAndRollbackLink_restoresSourceAndPeer() {
        let source = makeEntry(cardId: "from-card", word: "source")
        let peer = makeEntry(cardId: "to-card", word: "target")
        let link = KGCardLinkSummary(
            id: "link-1",
            cardId: "to-card",
            word: "target",
            kind: "shares_usage",
            label: "相關",
            confidence: 0.7,
            reason: "seed"
        )
        source.insertLink(link, kind: link.kind)
        peer.insertLink(link, kind: link.kind)

        let snapshot = VocabularyGraphLinkMutation.removeLink(link, from: source, peer: peer)

        #expect(source.graphLinksByKind.isEmpty)
        #expect(peer.graphLinksByKind.isEmpty)

        VocabularyGraphLinkMutation.rollbackLinkRemoval(snapshot, source: source, peer: peer)

        #expect(source.graphLinksByKind[link.kind]?.first == link)
        #expect(peer.graphLinksByKind[link.kind]?.first == link)
    }

    @Test func setHidden_updatesSourceAndPeerSymmetrically() {
        let source = makeEntry(cardId: "from-card", word: "source")
        let peer = makeEntry(cardId: "to-card", word: "target")
        let link = KGCardLinkSummary(
            id: "link-1",
            cardId: "to-card",
            word: "target",
            kind: "shares_usage",
            label: "相關",
            confidence: 0.7,
            reason: "seed"
        )
        source.insertLink(link, kind: link.kind)
        peer.insertLink(link, kind: link.kind)

        VocabularyGraphLinkMutation.setHidden(true, for: link, source: source, peer: peer)
        #expect(source.graphLinksByKind[link.kind]?.first?.hidden == true)
        #expect(peer.graphLinksByKind[link.kind]?.first?.hidden == true)

        VocabularyGraphLinkMutation.setHidden(false, for: link, source: source, peer: peer)
        #expect(source.graphLinksByKind[link.kind]?.first?.hidden == false)
        #expect(peer.graphLinksByKind[link.kind]?.first?.hidden == false)
    }

    private func makeEntry(cardId: String, word: String) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: "\(word)-translation",
            context: "\(word) context",
            bookTitle: "Book"
        )
        entry.kgCardId = cardId
        return entry
    }
}
