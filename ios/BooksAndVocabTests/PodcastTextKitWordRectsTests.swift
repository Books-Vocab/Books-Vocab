#if os(iOS)
import CoreGraphics
import Foundation
import UIKit
import Testing
@testable import BooksAndVocab

/// Covers `PodcastTextKitWordRects.wordRanges` — the positional word→NSRange map.
/// `fullText == words.joined(separator: " ")` (PodcastSubtitleEngine.makeSentence),
/// so every range must round-trip: slicing `fullText` by `ranges[i]` yields exactly
/// `words[i]`. This is the contract the TextKit rect resolution depends on.
struct PodcastWordRangeTests {
    /// Asserts the join + round-trip invariant for an arbitrary word list.
    private func assertRoundTrip(_ words: [String], sourceLocation: SourceLocation = #_sourceLocation) {
        let fullText = words.joined(separator: " ")
        let ns = fullText as NSString
        let ranges = PodcastTextKitWordRects.wordRanges(for: words)
        #expect(ranges.count == words.count, sourceLocation: sourceLocation)
        for (index, word) in words.enumerated() {
            guard let range = ranges[index] else {
                Issue.record("missing range for index \(index)", sourceLocation: sourceLocation)
                continue
            }
            #expect(NSMaxRange(range) <= ns.length, sourceLocation: sourceLocation)
            #expect(ns.substring(with: range) == word, sourceLocation: sourceLocation)
        }
    }

    @Test func asciiWordsRoundTrip() {
        assertRoundTrip(["OK", "so", "here's", "a", "question."])
    }

    @Test func cjkWordsRoundTrip() {
        // Mixed CJK + ASCII; NSString length counts UTF-16 units, which the
        // positional walk uses, so multi-byte glyphs map correctly.
        assertRoundTrip(["我們", "live", "在", "最", "comfortable", "的", "era。"])
    }

    @Test func wordWithInternalSpaceRoundTrips() {
        // A cue word can itself contain a space (a stitched token). The positional
        // walk still works because `fullText` is the exact join and the internal
        // space is counted in that word's length.
        assertRoundTrip(["New York", "City", "is", "big."])
    }

    @Test func punctuationAndContractionsRoundTrip() {
        assertRoundTrip(["\"Wait,\"", "she", "said—", "don't", "go."])
    }

    @Test func singleWordIsWholeRange() {
        let ranges = PodcastTextKitWordRects.wordRanges(for: ["hello"])
        #expect(ranges[0] == NSRange(location: 0, length: 5))
    }

    @Test func emptyWordsIsEmpty() {
        #expect(PodcastTextKitWordRects.wordRanges(for: []).isEmpty)
    }

    @Test func secondWordStartsAfterSeparator() {
        // "OK so" → "OK"=[0,2], "so"=[3,2]: the +1 separator gap is exact.
        let ranges = PodcastTextKitWordRects.wordRanges(for: ["OK", "so"])
        #expect(ranges[0] == NSRange(location: 0, length: 2))
        #expect(ranges[1] == NSRange(location: 3, length: 2))
    }
}

/// Covers `PodcastTextKitWordRects.resolve` + `LayoutKey` against an in-memory
/// TextKit stack (NSTextStorage + NSLayoutManager + NSTextContainer) — no simulator
/// UI, so the rect geometry is testable directly. Mirrors the Phase 3 production
/// config: `lineFragmentPadding == 0` so rects land in the view's own coordinate
/// space with no inset compensation.
struct PodcastTextKitWordRectsResolveTests {
    private let font = UIFont.systemFont(ofSize: 17)

    /// Builds a laid-out TextKit1 stack for `text` at `width`, matching the Phase 3
    /// UITextView config (zero padding/inset).
    private func makeStack(
        text: String,
        width: CGFloat
    ) -> (storage: NSTextStorage, layoutManager: NSLayoutManager, container: NSTextContainer) {
        let storage = NSTextStorage(string: text, attributes: [.font: font])
        let layoutManager = NSLayoutManager()
        storage.addLayoutManager(layoutManager)
        let container = NSTextContainer(size: CGSize(width: width, height: .greatestFiniteMagnitude))
        container.lineFragmentPadding = 0
        container.maximumNumberOfLines = 0
        layoutManager.addTextContainer(container)
        layoutManager.ensureLayout(for: container)
        return (storage, layoutManager, container)
    }

    @Test func resolvesOneRectPerWord() {
        let words = ["OK", "so", "here's", "a", "question."]
        let stack = makeStack(text: words.joined(separator: " "), width: 1000)
        let rects = PodcastTextKitWordRects.resolve(
            layoutManager: stack.layoutManager, textContainer: stack.container,
            wordRanges: PodcastTextKitWordRects.wordRanges(for: words)
        )
        #expect(rects.count == words.count)
    }

    @Test func singleLineMinXStrictlyIncreasing() {
        let words = ["alpha", "beta", "gamma", "delta"]
        // Wide enough that all words sit on one line.
        let stack = makeStack(text: words.joined(separator: " "), width: 1000)
        let rects = PodcastTextKitWordRects.resolve(
            layoutManager: stack.layoutManager, textContainer: stack.container,
            wordRanges: PodcastTextKitWordRects.wordRanges(for: words)
        )
        for i in 1..<words.count {
            guard let prev = rects[i - 1], let cur = rects[i] else {
                Issue.record("missing rect at \(i)"); continue
            }
            #expect(cur.minX > prev.minX)
            // Same line → same vertical position.
            #expect(abs(cur.minY - prev.minY) < 0.5)
        }
    }

    @Test func wrapStepsToNextRow() {
        let words = ["wrapping", "across", "multiple", "narrow", "rows", "here"]
        // Narrow container forces a wrap; at least one word lands on a lower row.
        let stack = makeStack(text: words.joined(separator: " "), width: 80)
        let rects = PodcastTextKitWordRects.resolve(
            layoutManager: stack.layoutManager, textContainer: stack.container,
            wordRanges: PodcastTextKitWordRects.wordRanges(for: words)
        )
        let minYs = rects.values.map(\.minY)
        guard let lo = minYs.min(), let hi = minYs.max() else {
            Issue.record("no rects resolved"); return
        }
        // A real line break → the bottom row's minY is at least ~one line below the top.
        #expect(hi - lo > font.lineHeight * 0.5)
    }

    @Test func layoutKeyEqualityGuardsReResolution() {
        let a = PodcastTextKitWordRects.LayoutKey(text: "hello world", font: font, width: 200)
        let b = PodcastTextKitWordRects.LayoutKey(text: "hello world", font: font, width: 200.3)
        let c = PodcastTextKitWordRects.LayoutKey(text: "hello world", font: font, width: 240)
        let d = PodcastTextKitWordRects.LayoutKey(
            text: "hello world", font: .systemFont(ofSize: 22), width: 200
        )
        // Sub-point width jitter quantizes to the same key (no cache thrash).
        #expect(a == b)
        // A real width change misses the cache.
        #expect(a != c)
        // A font size change misses the cache.
        #expect(a != d)
    }
}
#endif
