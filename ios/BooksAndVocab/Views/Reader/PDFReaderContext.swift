#if os(iOS)
import Foundation

/// Pure context-window extraction for the PDF reader, kept separate from the
/// `PDFView`/`PDFSelection` plumbing so it can be unit-tested on plain strings.
///
/// Mirrors the two EPUB context shapes:
///   * plain   — surrounding prose (EPUB word path).
///   * marked  — `before**highlight**after` (EPUB phrase/explain path, see
///     `ReadiumNavigatorSupport.buildMarkedContext`), so the LLM receives the
///     same emphasis format regardless of reader.
enum PDFReaderContext {
    /// Characters of context to include on each side of the highlight.
    static let contextRadius = 100

    /// Returns a context window centred on `range` within `pageText`. When
    /// `marked` is true the highlighted span is wrapped in `**…**`. Newlines are
    /// collapsed to spaces and the result is whitespace-trimmed (the markers are
    /// never trimmed because they sit inside the highlighted span).
    static func window(
        around range: Range<String.Index>,
        in pageText: String,
        marked: Bool,
        radius: Int = contextRadius
    ) -> String {
        let start = pageText.index(range.lowerBound, offsetBy: -radius, limitedBy: pageText.startIndex)
            ?? pageText.startIndex
        let end = pageText.index(range.upperBound, offsetBy: radius, limitedBy: pageText.endIndex)
            ?? pageText.endIndex

        let raw: String
        if marked {
            let before = pageText[start..<range.lowerBound]
            let highlight = pageText[range]
            let after = pageText[range.upperBound..<end]
            // Keep whitespace outside the ** markers so emphasis wraps exactly
            // the selected token(s) — matches EPUB, whose highlight arrives
            // pre-trimmed. A raw PDF drag can include leading/trailing spaces.
            let leadingCount = highlight.prefix { $0.isWhitespace }.count
            let trailingCount = highlight.reversed().prefix { $0.isWhitespace }.count
            let leading = highlight.prefix(leadingCount)
            let trailing = highlight.suffix(trailingCount)
            let core = highlight.dropFirst(leadingCount).dropLast(trailingCount)
            raw = "\(before)\(leading)**\(core)**\(trailing)\(after)"
        } else {
            raw = String(pageText[start..<end])
        }

        return raw
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
#endif
