#if os(iOS)
import Testing
@testable import BooksAndVocab

/// Selection-layer sanitize parity between PDF and EPUB readers.
///
/// EPUB strips word-boundary apostrophes/hyphens and drops <2-char noise in JS
/// (`ReadiumNavigatorJS+Selection.swift` regex `/^['-]+|['-]+$/` + `length < 2`)
/// *before* the shared `normalizeWord` capture contract runs. PDF had neither.
/// `ReaderWordCapture.sanitizeSelectedWord` brings the PDF selection path to the
/// same boundary, composing with (not replacing) `normalizeWord`.
struct ReaderWordCaptureTests {

    @Test func trimsWhitespace() {
        #expect(ReaderWordCapture.sanitizeSelectedWord("  hi  ") == "hi")
    }

    @Test func stripsLeadingAndTrailingApostropheHyphen() {
        #expect(ReaderWordCapture.sanitizeSelectedWord("'word'") == "word")
        #expect(ReaderWordCapture.sanitizeSelectedWord("well-") == "well")
        #expect(ReaderWordCapture.sanitizeSelectedWord("--co-op--") == "co-op")
    }

    @Test func preservesWordInternalPunctuation() {
        #expect(ReaderWordCapture.sanitizeSelectedWord("it's") == "it's")
        #expect(ReaderWordCapture.sanitizeSelectedWord("hi-fi") == "hi-fi")
    }

    @Test func dropsSubMinimumLengthNoise() {
        // Single-char or punctuation-only selections are noise (matches EPUB <2).
        // NOTE: this also drops the valid English words "I"/"a" — accepted to
        // stay consistent with EPUB's `length < 2`; do not "fix" one-sidedly.
        #expect(ReaderWordCapture.sanitizeSelectedWord("I") == nil)
        #expect(ReaderWordCapture.sanitizeSelectedWord("-") == nil)
        #expect(ReaderWordCapture.sanitizeSelectedWord("'") == nil)
        #expect(ReaderWordCapture.sanitizeSelectedWord("   ") == nil)
        #expect(ReaderWordCapture.sanitizeSelectedWord("") == nil)
    }

    // The selection layer intentionally does NOT strip sentence punctuation —
    // that is normalizeWord's job (the iOS↔backend capture contract). Sanitize
    // only handles boundary '/- and the min-length gate, so trailing "." here
    // survives until normalizeWord runs.
    @Test func leavesSentencePunctuationForNormalizeWord() {
        #expect(ReaderWordCapture.sanitizeSelectedWord("code.") == "code.")
    }
}
#endif
