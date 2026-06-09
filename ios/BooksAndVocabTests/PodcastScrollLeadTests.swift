import Foundation
import Testing
@testable import BooksAndVocab

/// Covers `PodcastSubtitleEngine.scrollLeadSentenceId` — the follow-scroll target
/// resolver behind 字幕提前捲動 (issue ⑤). Natural ticks LEAD the playhead by
/// `leadSec` so the next bubble centers ~0.5 s before it's spoken; a seek pins to
/// the current sentence (no lead) so a transcript tap centers the tapped bubble,
/// not its successor (★B1 race).
struct PodcastScrollLeadTests {
    private func sentence(
        _ id: Int, _ start: TimeInterval, _ end: TimeInterval, speaker: String = "A"
    ) -> PodcastSentence {
        PodcastSentence(
            id: id, speaker: speaker, text: "s\(id)",
            startTime: start, endTime: end, words: []
        )
    }

    /// Gap-free sentences, each 2 s long. Within `leadSec` (0.5) of a boundary the
    /// natural-tick lead jumps to the NEXT sentence so its bubble is already gliding
    /// to center; further from the boundary it stays on the current sentence.
    @Test func naturalTickLeadsIntoNextSentenceNearBoundary() {
        // s0[0,2] s1[2,4] s2[4,6]
        let s = [sentence(0, 0, 2), sentence(1, 2, 4), sentence(2, 4, 6)]
        // t=1.4 → lead 1.9 still inside s0.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 1.4, isSeek: false, leadSec: 0.5) == 0)
        // t=1.6 → lead 2.1 crosses into s1 (the lead, the whole point of ⑤).
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 1.6, isSeek: false, leadSec: 0.5) == 1)
        // t=3.6 → lead 4.1 crosses into s2.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 3.6, isSeek: false, leadSec: 0.5) == 2)
    }

    /// ★B1: a seek pins the lead to the CURRENT sentence — same `time` that on a
    /// natural tick would lead into the next sentence must resolve to the current
    /// one when `isSeek`, so a tap lands on the tapped bubble.
    @Test func seekPinsLeadToCurrentSentence() {
        let s = [sentence(0, 0, 2), sentence(1, 2, 4), sentence(2, 4, 6)]
        // Tap s0's tail at t=1.6: natural would lead to s1, seek must stay on s0.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 1.6, isSeek: true, leadSec: 0.5) == 0)
        // Tap s1's head (== s0's end, gap-free) resolves to s1, never s0.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 2.0, isSeek: true, leadSec: 0.5) == 1)
        // Tap s2's head.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 4.0, isSeek: true, leadSec: 0.5) == 2)
    }

    /// Mid-sentence, far from any boundary, the natural lead stays put — no churn.
    @Test func midSentenceLeadStaysPut() {
        let s = [sentence(0, 0, 4), sentence(1, 4, 8)]
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 1.0, isSeek: false, leadSec: 0.5) == 0)
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 5.0, isSeek: false, leadSec: 0.5) == 1)
    }

    /// Lead past the last sentence's end falls back to the last sentence (gap
    /// fallback in `locateSentence`'s `hi`), never nil — so the scroll holds the
    /// final bubble instead of un-centering at the tail of the episode.
    @Test func leadPastEndHoldsLastSentence() {
        let s = [sentence(0, 0, 2), sentence(1, 2, 4)]
        // t=3.9 → lead 4.4, past s1.end=4 → still s1.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 3.9, isSeek: false, leadSec: 0.5) == 1)
    }

    /// Pre-roll: before the first sentence's start the lead is nil until the lead
    /// time reaches it (mirrors `locateSentence` returning nil before `startTime`).
    @Test func preRollLeadIsNilUntilFirstSentence() {
        let s = [sentence(0, 1, 3)]
        // t=0.2 → lead 0.7, still before s0.start=1 → nil.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 0.2, isSeek: false, leadSec: 0.5) == nil)
        // t=0.6 → lead 1.1, now inside s0.
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: s, at: 0.6, isSeek: false, leadSec: 0.5) == 0)
    }

    /// Empty transcript → nil for both paths (no crash, graceful).
    @Test func emptyTranscriptIsNil() {
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: [], at: 1.0, isSeek: false, leadSec: 0.5) == nil)
        #expect(PodcastSubtitleEngine.scrollLeadSentenceId(in: [], at: 1.0, isSeek: true, leadSec: 0.5) == nil)
    }
}
