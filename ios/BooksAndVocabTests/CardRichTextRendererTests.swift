import Testing
@testable import BooksAndVocab

struct CardRichTextRendererTests {
    @Test func truncate_phraseInflectionUsesTailPhraseAnchor() {
        let raw = "My dear Lightsong, I do believe that you’re making sport of me."
        let result = CardRichTextRenderer.truncateAroundMarkedWord(
            raw,
            radiusWords: 3,
            targetWordFallback: "make sport of me"
        )

        #expect(result.contains("**making sport of me**"))
        #expect(result.contains("dear Lightsong") == false)
    }

    @Test func truncate_irregularPhraseInflectionUsesTailPhraseAnchor() {
        let raw = "Idris, it wasn’t that big, and everyone knew her by sight."
        let result = CardRichTextRenderer.truncateAroundMarkedWord(
            raw,
            radiusWords: 3,
            targetWordFallback: "know her by sight"
        )

        #expect(result.contains("**knew her by sight**"))
        #expect(result.contains("Idris") == false)
    }

    @Test func truncate_missingTargetReturnsUnmarkedFullTextInsteadOfMisleadingLead() {
        let raw = "Alpha beta gamma delta epsilon zeta eta theta."
        let result = CardRichTextRenderer.truncateAroundMarkedWord(
            raw,
            radiusWords: 2,
            targetWordFallback: "missing phrase"
        )

        #expect(result == raw)
    }
}
