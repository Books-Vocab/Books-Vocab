#if os(iOS)
import Foundation

/// Selection-layer sanitize for reader word capture, shared-in-spirit with the
/// EPUB Readium JS selection path.
///
/// EPUB extends a tapped word over `[a-zA-Z'\-]`, strips boundary `'`/`-`, and
/// drops `< 2`-char results in JavaScript before handing off to the shared
/// `ReaderTranslationHandler.normalizeWord` capture contract. PDFKit selections
/// arrive raw, so the PDF reader runs this helper to reach the same boundary.
///
/// This is deliberately distinct from `normalizeWord`: sanitize handles the
/// selection-noise concerns (boundary `'`/`-`, min length); `normalizeWord`
/// owns the iOS↔backend capture contract (NFC + trailing `.,;:!?`). They
/// compose — sanitize first, then normalizeWord.
enum ReaderWordCapture {
    /// Mirrors EPUB's `if (word.length < 2) return null` — single-char or
    /// punctuation-only selections are treated as noise and dropped.
    static let minWordLength = 2

    private static let boundaryCharacters = CharacterSet(charactersIn: "'-")

    /// Returns the sanitized single-word selection, or `nil` if it is noise.
    static func sanitizeSelectedWord(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let stripped = trimmed.trimmingCharacters(in: boundaryCharacters)
        guard stripped.count >= minWordLength else { return nil }
        return stripped
    }

    /// Classifies a raw selection as a phrase (multi-token) vs a single word, so
    /// the PDF edit menu can route to `handlePhraseSelected` vs
    /// `handleWordSelected` — matching EPUB, where a tap is a word and a
    /// multi-word selection is a phrase. Any internal whitespace ⇒ phrase.
    static func isPhraseSelection(_ raw: String) -> Bool {
        raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .contains { $0.isWhitespace }
    }
}
#endif
