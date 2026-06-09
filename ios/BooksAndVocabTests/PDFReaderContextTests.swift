#if os(iOS)
import Testing
@testable import BooksAndVocab

/// Context-window extraction parity for the PDF reader.
///
/// EPUB word context is plain prose; EPUB phrase/explain context is marked as
/// `before**highlight**after` (`ReadiumNavigatorSupport.buildMarkedContext`).
/// `PDFReaderContext.window` brings PDF to the same shapes from a page string +
/// selection range, so PDF phrase/explain hand the LLM the same marked format.
struct PDFReaderContextTests {

    private let page = "The quick brown fox jumps over the lazy dog."

    private func range(of sub: String) -> Range<String.Index> {
        page.range(of: sub)!
    }

    @Test func plainWindowHasNoMarkers() {
        let ctx = PDFReaderContext.window(around: range(of: "brown"), in: page, marked: false)
        #expect(ctx.contains("brown"))
        #expect(!ctx.contains("**"))
    }

    @Test func markedWindowWrapsHighlight() {
        let ctx = PDFReaderContext.window(around: range(of: "brown"), in: page, marked: true)
        #expect(ctx.contains("**brown**"))
        // Surrounding prose is preserved on both sides of the marked span.
        #expect(ctx.contains("quick "))
        #expect(ctx.contains(" fox"))
    }

    @Test func markedWindowPreservesMultiWordHighlight() {
        let ctx = PDFReaderContext.window(around: range(of: "brown fox"), in: page, marked: true)
        #expect(ctx.contains("**brown fox**"))
    }

    @Test func windowNormalizesNewlinesToSpaces() {
        let multiline = "line one\nbrown\nline three"
        let ctx = PDFReaderContext.window(around: multiline.range(of: "brown")!, in: multiline, marked: false)
        #expect(!ctx.contains("\n"))
        #expect(ctx.contains("brown"))
    }

    @Test func markedWindowKeepsWhitespaceOutsideMarkers() {
        // A raw drag whose range includes surrounding spaces must still wrap the
        // bare token — no "** brown **" with whitespace inside the markers.
        let p = "x  brown  y"
        let r = p.range(of: "  brown  ")!
        let ctx = PDFReaderContext.window(around: r, in: p, marked: true)
        #expect(ctx.contains("**brown**"))
        // No whitespace *inside* the markers (surrounding prose spaces are fine).
        #expect(!ctx.contains("** brown"))
        #expect(!ctx.contains("brown **"))
    }

    @Test func windowClampsToPageBounds() {
        // Highlight at the very start/end must not crash and must still wrap.
        let startCtx = PDFReaderContext.window(around: range(of: "The"), in: page, marked: true)
        #expect(startCtx.contains("**The**"))
        let endCtx = PDFReaderContext.window(around: range(of: "dog."), in: page, marked: true)
        #expect(endCtx.contains("**dog.**"))
    }
}

/// Word-vs-phrase classification for the PDF edit-menu routing.
struct ReaderSelectionKindTests {
    @Test func singleTokenIsWord() {
        #expect(ReaderWordCapture.isPhraseSelection("invoke") == false)
        #expect(ReaderWordCapture.isPhraseSelection("  invoke  ") == false)
        #expect(ReaderWordCapture.isPhraseSelection("well-known") == false)
    }

    @Test func multipleTokensIsPhrase() {
        #expect(ReaderWordCapture.isPhraseSelection("in due course") == true)
        #expect(ReaderWordCapture.isPhraseSelection("brown fox") == true)
        #expect(ReaderWordCapture.isPhraseSelection("line\nbreak") == true)
    }
}
#endif
