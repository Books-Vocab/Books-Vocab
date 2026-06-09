import Testing
@testable import BooksAndVocab

struct CollocationExplanationStateTests {
    @Test func hasExplanationRequiresNonEmptyTrimmedText() {
        #expect(CardDocumentCollocationState.hasExplanation(for: "petulant child", in: [
            "petulant child": "Often used when describing childish irritability."
        ]))

        #expect(CardDocumentCollocationState.hasExplanation(for: "petulant tone", in: [
            "petulant tone": "   "
        ]) == false)

        #expect(CardDocumentCollocationState.hasExplanation(for: "petulant tone", in: [:]) == false)
    }
}
