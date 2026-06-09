import Testing
@testable import BooksAndVocab

@Suite("PodcastHighlightResolver")
struct PodcastHighlightResolverTests {
    @Test func noCurrentHasNoHighlight() {
        #expect(PodcastHighlightResolver.highlightId(currentId: nil, scrollLeadId: 1) == nil)
    }

    @Test func currentRemainsHighlightedUntilLeadAdvances() {
        #expect(PodcastHighlightResolver.highlightId(currentId: 4, scrollLeadId: nil) == 4)
        #expect(PodcastHighlightResolver.highlightId(currentId: 4, scrollLeadId: 4) == 4)
        #expect(PodcastHighlightResolver.highlightId(currentId: 4, scrollLeadId: 3) == 4)
    }

    @Test func immediateSuccessorTakesOverWhenLeadTargetsIt() {
        #expect(PodcastHighlightResolver.highlightId(currentId: 4, scrollLeadId: 5) == 5)
    }

    @Test func farLeadIsClampedToImmediateSuccessor() {
        #expect(PodcastHighlightResolver.highlightId(currentId: 4, scrollLeadId: 6) == 5)
    }
}
