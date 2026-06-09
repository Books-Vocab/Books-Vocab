import Foundation
import Testing
@testable import BooksAndVocab

/// Covers `PodcastSubtitleEngine.locateSentence` — the seek-to-sentence resolver
/// behind tapping a transcript bubble. The half-open `[start, end)` interval fixes
/// an off-by-one where tapping a non-first sentence in a speaker group focused the
/// bubble ABOVE it (gap-free SRT boundaries belonged to both neighbours' closed
/// ranges; a zero-tolerance seek landed exactly on the tie).
struct PodcastSubtitleEngineTests {
    private func sentence(
        _ id: Int, _ start: TimeInterval, _ end: TimeInterval, speaker: String = "A"
    ) -> PodcastSentence {
        PodcastSentence(
            id: id, speaker: speaker, text: "s\(id)",
            startTime: start, endTime: end, words: []
        )
    }

    /// THE BUG: gap-free sentences, tap one's start (== previous one's end). Needs
    /// ≥5 sentences so the binary search's first `mid` lands on `i-1` — the exact
    /// path where the old CLOSED interval returned the bubble above. Must resolve
    /// to the TAPPED sentence.
    @Test func seekToGapFreeBoundaryResolvesToThatSentence() {
        // s0[0,2] s1[2,4] s2[4,6] s3[6,8] s4[8,10]
        let s = (0..<5).map { sentence($0, Double($0) * 2, Double($0) * 2 + 2) }
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 2.0)?.id == 1)
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 4.0)?.id == 2)
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 8.0)?.id == 4)
    }

    /// A time strictly inside a sentence resolves to that sentence.
    @Test func midSentenceResolvesToContainingSentence() {
        let s = [sentence(0, 0, 2), sentence(1, 2, 4), sentence(2, 4, 6)]
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 1.0)?.id == 0)
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 5.5)?.id == 2)
    }

    /// Group-first sentences sit behind a speaker-change silence. A time INSIDE the
    /// gap falls back to the previous sentence; arriving at the next start resolves
    /// uniquely to it.
    @Test func silenceGapFallsBackToPreviousSentence() {
        let s = [sentence(0, 0, 2, speaker: "A"), sentence(1, 3, 5, speaker: "B")] // gap 2..3
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 2.5)?.id == 0)
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 3.0)?.id == 1)
    }

    /// Before the first start → nil; past the last end → the last sentence (so a
    /// finished episode keeps showing its closing line, not nothing).
    @Test func beforeFirstAndAfterLast() {
        let s = [sentence(0, 1, 2), sentence(1, 2, 3)]
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 0.0) == nil)
        #expect(PodcastSubtitleEngine.locateSentence(in: s, at: 100.0)?.id == 1)
    }

    @Test func emptyReturnsNil() {
        #expect(PodcastSubtitleEngine.locateSentence(in: [], at: 1.0) == nil)
    }
}
