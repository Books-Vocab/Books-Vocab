#if os(iOS)
import Testing
@testable import BooksAndVocab

/// `ReaderProseTokenizer` assigns highlight emphasis to the marketing prose words
/// (the native book content behind the App Store / website reader shot). It is a
/// pure function so the highlight-assignment logic is verifiable without SwiftUI.
struct ReaderProseTokenizerTests {

    private let paragraph = "What looked barren often proved resilient in the end, waiting for a thaw it trusts."

    @Test func tokenCountMatchesWordCount() {
        let tokens = ReaderProseTokenizer.tokens(paragraph: paragraph, vocab: [], active: [])
        #expect(tokens.count == paragraph.split(separator: " ").count)
    }

    @Test func preservesOriginalGlyphsIncludingPunctuation() {
        let tokens = ReaderProseTokenizer.tokens(paragraph: paragraph, vocab: [], active: [])
        // "end," keeps its comma in the rendered text even though matching trims it.
        #expect(tokens.contains(ProseToken(text: "end,", emphasis: .none)))
        #expect(tokens.allSatisfy { $0.emphasis == .none })
    }

    @Test func assignsVocabAndActiveEmphasis() {
        let tokens = ReaderProseTokenizer.tokens(
            paragraph: paragraph,
            vocab: ["thaw"],
            active: ["resilient"]
        )
        #expect(tokens.first { $0.text == "resilient" }?.emphasis == .active)
        #expect(tokens.first { $0.text == "thaw" }?.emphasis == .vocab)
        // Qualify `.none` — bare `.none` in an optional-chained comparison binds to
        // `Optional.none` (nil), not `ProseToken.Emphasis.none`.
        #expect(tokens.first { $0.text == "barren" }?.emphasis == ProseToken.Emphasis.none)
    }

    @Test func matchingTrimsTrailingPunctuation() {
        // A highlighted word carrying trailing punctuation still matches (trim is
        // match-only), so authors need not hand-strip commas from vocab words.
        let tokens = ReaderProseTokenizer.tokens(
            paragraph: "the day proved resilient, and warm",
            vocab: [],
            active: ["resilient"]
        )
        let token = tokens.first { $0.text == "resilient," }
        #expect(token?.emphasis == .active)
    }

    @Test func activeTakesPrecedenceOverVocab() {
        let tokens = ReaderProseTokenizer.tokens(
            paragraph: "a resilient road",
            vocab: ["resilient"],
            active: ["resilient"]
        )
        #expect(tokens.first { $0.text == "resilient" }?.emphasis == .active)
    }
}
#endif
