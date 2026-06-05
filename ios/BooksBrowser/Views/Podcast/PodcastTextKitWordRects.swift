#if os(iOS)
import UIKit
import CoreGraphics

/// Resolves per-word on-screen rects from a TextKit layout — the rect source for
/// the continuous reading underline once the transcript bubble unifies on a single
/// `UITextView` layout engine (issue ③, 3-A).
///
/// ## Why this exists
///
/// The bubble previously rendered TWO layout engines: a SwiftUI per-word `Text` +
/// a cached flow layout in the normal state and a TextKit `UITextView` in the
/// selecting state. Their kerning + line-break points differ, so swapping engines
/// on long-press reflowed the text (the "選取時排版跳版" bug). 3-A unifies on ONE
/// `UITextView`; the underline then needs word rects from TextKit instead of from
/// SwiftUI anchor preferences. These pure functions are that bridge — and being
/// pure + UIKit-only (no SwiftUI, no live view) they are unit-testable against an
/// in-memory `NSTextStorage`/`NSLayoutManager`/`NSTextContainer` with no simulator.
///
/// The downstream geometry (`PodcastUnderlineGeometry`, `PodcastWordProgress`) is
/// already pure over `[Int: CGRect]`, so 3-A only swaps the rect SOURCE — the bar
/// math and relay regimes are unchanged.
enum PodcastTextKitWordRects {
    /// Maps each word index to its `NSRange` within the sentence's `fullText`.
    ///
    /// `fullText` is exactly `words.joined(separator: " ")` (see
    /// `PodcastSubtitleEngine.makeSentence`), so each range is computed POSITIONALLY
    /// from cumulative lengths — no heuristic tokenize, and no `range(of:)` search
    /// that a repeated word ("the … the") could mis-resolve. Lengths are UTF-16 code
    /// units (`NSString.length`), TextKit's native unit, so the ranges drop straight
    /// into `glyphRange(forCharacterRange:)`. The joining space is one UTF-16 unit,
    /// hence `+1` between words.
    static func wordRanges(for words: [String]) -> [Int: NSRange] {
        var ranges: [Int: NSRange] = [:]
        var location = 0
        for (index, word) in words.enumerated() {
            let length = (word as NSString).length
            ranges[index] = NSRange(location: location, length: length)
            location += length + 1  // +1 for the single joining space
        }
        return ranges
    }

    /// Resolves each word's bounding rect in the text view's OWN coordinate space
    /// (origin top-left), given a laid-out TextKit stack. Requires the container's
    /// `lineFragmentPadding == 0` and the text view's `textContainerInset == .zero`
    /// so the returned rects need no inset compensation to align with
    /// `PodcastUnderlineGeometry`'s expectations.
    ///
    /// Layout is forced per queried glyph range: an entering ("next") bubble can be
    /// realized but not yet laid out, where `boundingRect` would otherwise return
    /// zero. A zero/empty rect maps to nil — `relayBars` already treats a missing
    /// rect gracefully (the underline simply doesn't draw for that word that frame).
    static func resolve(
        layoutManager: NSLayoutManager,
        textContainer: NSTextContainer,
        wordRanges: [Int: NSRange]
    ) -> [Int: CGRect] {
        var rects: [Int: CGRect] = [:]
        let storageLength = layoutManager.textStorage?.length ?? 0
        for (index, charRange) in wordRanges {
            // Defensive: clamp out a stale range past the current storage (mid text
            // swap). `boundingRect(forGlyphRange:)` asserts on an out-of-range GLYPH
            // range, so guard the char range before it maps to glyphs.
            guard NSMaxRange(charRange) <= storageLength, charRange.length > 0 else { continue }
            let glyphRange = layoutManager.glyphRange(
                forCharacterRange: charRange, actualCharacterRange: nil
            )
            guard glyphRange.length > 0 else { continue }
            layoutManager.ensureLayout(forGlyphRange: glyphRange)
            let rect = layoutManager.boundingRect(forGlyphRange: glyphRange, in: textContainer)
            guard rect.width > 0, rect.height > 0 else { continue }
            rects[index] = rect
        }
        return rects
    }

    /// Cache key guarding rect re-resolution: word rects only change when the laid-out
    /// text, the font, or the container width changes. The view caches the resolved
    /// `[Int: CGRect]` against this key and re-resolves ONLY on a miss — re-resolving
    /// (and re-publishing) every display frame is exactly the per-frame cost that
    /// reintroduces the scroll-freeze. Equatable so the view can compare cheaply.
    struct LayoutKey: Equatable {
        let text: String
        let fontName: String
        let pointSize: CGFloat
        let width: CGFloat

        init(text: String, font: UIFont, width: CGFloat) {
            self.text = text
            self.fontName = font.fontName
            self.pointSize = font.pointSize
            // Quantize to whole points so sub-pixel width jitter during layout does
            // not thrash the cache (a 0.0001pt delta is not a real re-layout).
            self.width = width.rounded()
        }
    }
}
#endif
