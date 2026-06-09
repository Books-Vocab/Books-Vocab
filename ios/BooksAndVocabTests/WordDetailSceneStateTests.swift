import Testing
@testable import BooksAndVocab

@MainActor
struct WordDetailSceneStateTests {

    @Test func refreshPresentation_buildsPresenterState() {
        let entry = makeEntry(cardId: "root-card", word: "meticulous")
        let peer = makeEntry(cardId: "peer-card", word: "precise")
        entry.insertLink(
            KGCardLinkSummary(
                id: "link-1",
                cardId: "peer-card",
                word: "precise",
                kind: "shares_usage",
                label: "相關",
                confidence: 0.8,
                reason: "seed"
            ),
            kind: "shares_usage"
        )

        let state = WordDetailSceneState()
        state.refreshPresentation(for: entry, in: [entry, peer])

        #expect(state.presenterState?.title == "meticulous")
        #expect(state.presenterState?.navigableLinkCardIDs == ["peer-card"])
    }

    @Test func linkedEntry_resolvesPeerFromAllEntries() {
        let entry = makeEntry(cardId: "root-card", word: "meticulous")
        let peer = makeEntry(cardId: "peer-card", word: "precise")
        let link = KGCardLinkSummary(
            id: "link-1",
            cardId: "peer-card",
            word: "precise",
            kind: "shares_usage",
            label: "相關",
            confidence: 0.8,
            reason: "seed"
        )

        let state = WordDetailSceneState()
        let resolved = state.linkedEntry(for: link, from: entry, in: [entry, peer])

        #expect(resolved === peer)
    }

    @Test func dismissLinkError_clearsBannerState() {
        let state = WordDetailSceneState()
        state.linkError = "error"

        state.dismissLinkError()

        #expect(state.linkError == nil)
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
