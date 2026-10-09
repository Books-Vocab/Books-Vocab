import Testing
@testable import BooksAndVocab

/// #2737 — the source-context block is hidden when it merely repeats the first
/// example; the comparison must ignore surrounding whitespace on both sides.
@MainActor
struct CardPresentationSourceContextTests {
    private static func presentation(context: String, example: String, bookTitle: String = "Knowledge Graph") -> CardPresentation {
        let entry = VocabularyEntry(word: "w", translation: "t", context: context, bookTitle: bookTitle)
        entry.reviewExamples = [example]
        return CardPresentation(entry: entry, pendingLinks: [])
    }

    @Test func trailingNewlineExampleDoesNotDuplicateContext() {
        #expect(Self.presentation(context: "She ran.", example: "She ran.\n").showsSourceContext == false)
    }

    @Test func paddedContextMatchesTrimmedExample() {
        #expect(Self.presentation(context: "  She ran. ", example: "She ran.").showsSourceContext == false)
    }

    @Test func differentContextStillShows() {
        #expect(Self.presentation(context: "He sat.", example: "She ran.\n").showsSourceContext)
    }

    @Test func realBookTitleStillShows() {
        #expect(Self.presentation(context: "She ran.", example: "She ran.\n", bookTitle: "Emma").showsSourceContext)
    }
}
