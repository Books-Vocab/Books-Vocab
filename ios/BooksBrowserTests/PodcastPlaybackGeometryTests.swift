import CoreGraphics
import Foundation
import Testing
@testable import BooksBrowser

struct PodcastPlaybackClockTests {
    @Test func projectsLinearlyAtRate() {
        let a = PodcastPlaybackClock.makeAnchor(mediaTime: 10, now: 1000, rate: 1)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a, now: 1002, duration: 120) == 12)
        let a2 = PodcastPlaybackClock.makeAnchor(mediaTime: 10, now: 1000, rate: 2)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a2, now: 1003, duration: 120) == 16)
    }

    @Test func pausedRateHoldsStill() {
        let a = PodcastPlaybackClock.makeAnchor(mediaTime: 42, now: 1000, rate: 0)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a, now: 1099, duration: 120) == 42)
    }

    @Test func clampsToBounds() {
        let a = PodcastPlaybackClock.makeAnchor(mediaTime: 119, now: 1000, rate: 1)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a, now: 1010, duration: 120) == 120)
        let back = PodcastPlaybackClock.makeAnchor(mediaTime: 1, now: 1000, rate: -10)
        #expect(PodcastPlaybackClock.projectedTime(anchor: back, now: 1001, duration: 120) == 0)
    }

    @Test func nowEqualsAnchorReturnsMediaTime() {
        let a = PodcastPlaybackClock.makeAnchor(mediaTime: 33, now: 1000, rate: 1.5)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a, now: 1000, duration: 120) == 33)
    }

    @Test func unknownDurationSkipsUpperClamp() {
        // duration <= 0 (not yet loaded): lower-bound at 0 only, no upper clamp.
        let a = PodcastPlaybackClock.makeAnchor(mediaTime: 10, now: 1000, rate: 1)
        #expect(PodcastPlaybackClock.projectedTime(anchor: a, now: 1100, duration: 0) == 110)
    }

    @Test func rateChangeWhilePausedHoldsPosition() {
        // cycleRate while paused → newRate 0: position frozen at the projected media time.
        let old = PodcastPlaybackClock.makeAnchor(mediaTime: 20, now: 1000, rate: 0)
        let new = PodcastPlaybackClock.anchorAfterRateChange(old: old, now: 1005, newRate: 0, duration: 120)
        #expect(new.mediaTime == 20)
        #expect(PodcastPlaybackClock.projectedTime(anchor: new, now: 1099, duration: 120) == 20)
    }

    @Test func rateChangeReanchorsWithoutJump() {
        // Position at switch instant must be continuous: projecting just-before
        // and just-after the rate change yields the same media time.
        let old = PodcastPlaybackClock.makeAnchor(mediaTime: 10, now: 1000, rate: 1)
        let before = PodcastPlaybackClock.projectedTime(anchor: old, now: 1004, duration: 120) // 14
        let new = PodcastPlaybackClock.anchorAfterRateChange(old: old, now: 1004, newRate: 2, duration: 120)
        let after = PodcastPlaybackClock.projectedTime(anchor: new, now: 1004, duration: 120)
        #expect(before == 14)
        #expect(after == 14)
        // ...and the new rate takes effect going forward.
        #expect(PodcastPlaybackClock.projectedTime(anchor: new, now: 1005, duration: 120) == 16)
    }
}

struct PodcastWordProgressTests {
    // 0.2s words at 60fps must each resolve to a valid index+fraction (no skipped
    // word) — this is the strobe bug the continuous underline kills.
    private let words = [
        PodcastSubtitleCue(id: 1, startTime: 0.0, endTime: 0.2, speaker: "A", word: "a"),
        PodcastSubtitleCue(id: 2, startTime: 0.2, endTime: 0.4, speaker: "A", word: "the"),
        PodcastSubtitleCue(id: 3, startTime: 0.4, endTime: 0.6, speaker: "A", word: "cat"),
    ]

    @Test func beforeFirstWordIsInactive() {
        let r = PodcastWordProgress.locate(time: -0.1, words: words)
        #expect(r.index == -1)
    }

    @Test func emptyInputIsInactive() {
        let r = PodcastWordProgress.locate(time: 5, words: [])
        #expect(r.index == -1)
    }

    @Test func fractionRampsWithinWord() {
        let mid = PodcastWordProgress.locate(time: 0.1, words: words)
        #expect(mid.index == 0)
        #expect(abs(mid.fraction - 0.5) < 1e-9)
        let start = PodcastWordProgress.locate(time: 0.2, words: words)
        #expect(start.index == 1)
        #expect(start.fraction == 0)
    }

    @Test func shortWordsNeverSkippedAcross60fpsSampling() {
        // Sample every 1/60s across all three 0.2s words; every sample must land
        // on a real index with fraction in [0,1].
        var t = 0.0
        while t < 0.6 {
            let r = PodcastWordProgress.locate(time: t, words: words)
            let expected = min(Int(t / 0.2), words.count - 1)
            #expect(r.index == expected, "t=\(t) should resolve to word \(expected), got \(r.index)")
            #expect(r.fraction >= 0 && r.fraction <= 1)
            t += 1.0 / 60.0
        }
    }

    @Test func silenceGapHoldsPreviousWord() {
        // Gap: word ends 0.2 but next starts 0.5. time 0.35 in the gap holds word 0 at f=1.
        let gapped = [
            PodcastSubtitleCue(id: 1, startTime: 0.0, endTime: 0.2, speaker: "A", word: "a"),
            PodcastSubtitleCue(id: 2, startTime: 0.5, endTime: 0.7, speaker: "A", word: "cat"),
        ]
        let r = PodcastWordProgress.locate(time: 0.35, words: gapped)
        #expect(r.index == 0)
        #expect(r.fraction == 1)
    }

    // Cross-assert against the engine's currentCue gap fallback so the continuous
    // underline never diverges from the discrete sentence highlight at a gap.
    @Test func gapAttributionMatchesEngineCurrentCue() {
        let gapped = [
            PodcastSubtitleCue(id: 10, startTime: 0.0, endTime: 0.2, speaker: "A", word: "a"),
            PodcastSubtitleCue(id: 11, startTime: 0.5, endTime: 0.7, speaker: "A", word: "cat"),
        ]
        let engine = PodcastSubtitleEngine()
        let srt = """
        10
        00:00:00,000 --> 00:00:00,200
        [A] a

        11
        00:00:00,500 --> 00:00:00,700
        [A] cat
        """
        engine.load(srtContent: srt)
        for t in [0.1, 0.35, 0.55] {
            let located = PodcastWordProgress.locate(time: t, words: gapped)
            let engineCue = engine.currentCue(at: t)
            #expect(gapped[located.index].id == engineCue?.id)
        }
    }
}

struct PodcastUnderlineGeometryTests {
    @Test func emptyWhenNoActiveWord() {
        #expect(PodcastUnderlineGeometry.segments(
            wordRects: [0: CGRect(x: 0, y: 0, width: 10, height: 4)], activeIndex: -1, fraction: 0
        ).isEmpty)
    }

    @Test func emptyWhenRectMissing() {
        #expect(PodcastUnderlineGeometry.segments(wordRects: [:], activeIndex: 0, fraction: 0.5).isEmpty)
    }

    @Test func singleSegmentAtActiveWordWhenNoNext() {
        // Last word of a sentence: no next cue → one bar under the active word.
        let rects = [0: CGRect(x: 5, y: 0, width: 20, height: 18)]
        let segs = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0.7)
        #expect(segs.count == 1)
        #expect(segs[0].minX == 5)
        #expect(segs[0].width == 20)
        #expect(segs[0].bottomY == 18)
    }

    @Test func glidesAsOneSegmentOnSameRow() {
        let rects = [
            0: CGRect(x: 0, y: 0, width: 20, height: 18),
            1: CGRect(x: 30, y: 0, width: 40, height: 18),
        ]
        let start = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0)
        #expect(start.count == 1)
        #expect(start[0].minX == 0)
        #expect(start[0].width == 20)
        let mid = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0.5)
        #expect(mid.count == 1)
        #expect(mid[0].minX == 15)   // lerp 0→30
        #expect(mid[0].width == 30)  // lerp 20→40
        let end = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 1)
        #expect(end.count == 1)
        #expect(end[0].minX == 30)
        #expect(end[0].width == 40)
    }

    @Test func subPixelMinYDeltaStaysSameRow() {
        // Layout rounding can leave two words on the same visual row with a tiny
        // minY delta; that must not be read as a line break.
        let rects = [
            0: CGRect(x: 0, y: 0, width: 20, height: 20),
            1: CGRect(x: 30, y: 0.3, width: 40, height: 20),  // 0.3 ≪ height*0.5
        ]
        let mid = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0.5)
        #expect(mid.count == 1)
        #expect(mid[0].minX == 15)
        #expect(mid[0].width == 30)
    }

    @Test func portalStartsFullyOnFirstRow() {
        // t=0 across a line break → single segment under the active word (row1).
        let rects = [
            0: CGRect(x: 50, y: 0, width: 20, height: 18),   // last of row1
            1: CGRect(x: 0, y: 30, width: 40, height: 18),   // first of row2
        ]
        let segs = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0)
        #expect(segs.count == 1)
        #expect(segs[0].minX == 50)
        #expect(segs[0].width == 20)
        #expect(segs[0].bottomY == 18)   // row1
    }

    @Test func portalSplitsAcrossBothRowsMidTransition() {
        // a: row1 (maxX=70 → row1End). b: row2 (minX=0 → row2Start).
        // seg1 = 70-50 = 20, seg2 = 0, total = 20.
        // t=0.5 → uL = 10, width = lerp(20,40)=30, uR = 40, seam = 20.
        //   row1 piece u∈[10,20] → minX 50+10=60, width 10, bottomY 18.
        //   row2 piece u∈[20,40] → minX 0+(20-20)=0, width 20, bottomY 48.
        let rects = [
            0: CGRect(x: 50, y: 0, width: 20, height: 18),
            1: CGRect(x: 0, y: 30, width: 40, height: 18),
        ]
        let segs = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0.5)
        #expect(segs.count == 2)
        #expect(segs[0].bottomY == 18)   // tail on row1
        #expect(segs[0].minX == 60)
        #expect(segs[0].width == 10)
        #expect(segs[1].bottomY == 48)   // head on row2
        #expect(segs[1].minX == 0)
        #expect(segs[1].width == 20)
    }

    @Test func portalLandsOnNextWordAtEnd() {
        // t=1 → fully arrived: single segment exactly on the next word (row2).
        let rects = [
            0: CGRect(x: 50, y: 0, width: 20, height: 18),
            1: CGRect(x: 0, y: 30, width: 40, height: 18),
        ]
        let segs = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 1)
        #expect(segs.count == 1)
        #expect(segs[0].minX == 0)
        #expect(segs[0].width == 40)
        #expect(segs[0].bottomY == 48)   // row2
    }

    @Test func portalUsesRowExtentsNotJustTheTwoWords() {
        // Extra words extend row1End beyond `a` and pull row2Start left of `b`,
        // so the unrolled travel distance reflects the whole row, not the pair.
        let rects = [
            0: CGRect(x: 50, y: 0, width: 20, height: 18),    // a (active), last-but-one of row1
            10: CGRect(x: 80, y: 0, width: 15, height: 18),   // trailing word on row1 → row1End=95
            1: CGRect(x: 30, y: 30, width: 40, height: 18),   // b on row2
            11: CGRect(x: 0, y: 30, width: 20, height: 18),   // leading word on row2 → row2Start=0
        ]
        // seg1 = 95-50 = 45, seg2 = 30-0 = 30, total = 75.
        // t=0 → uL 0, width 20, uR 20 ≤ seg1 → single row1 bar at a.
        let begin = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 0)
        #expect(begin.count == 1)
        #expect(begin[0].minX == 50)
        #expect(begin[0].bottomY == 18)
        // t=1 → lands on b (row2), minX=30 (row2Start 0 + seg2 30).
        let done = PodcastUnderlineGeometry.segments(wordRects: rects, activeIndex: 0, fraction: 1)
        #expect(done.count == 1)
        #expect(done[0].minX == 30)
        #expect(done[0].width == 40)
        #expect(done[0].bottomY == 48)
    }

    // MARK: - Cross-sentence edge relay (Option B)

    @Test func tailExitStartsExactlyUnderLastWord() {
        // fraction 0 → bar IS the last word (continuous with the normal underline).
        let bar = PodcastUnderlineGeometry.tailExit(
            lastWord: CGRect(x: 5, y: 0, width: 20, height: 18), rowRightEdge: 100, fraction: 0
        )
        #expect(bar?.minX == 5)
        #expect(bar?.width == 20)
        #expect(bar?.bottomY == 18)
    }

    @Test func tailExitSlidesRightKeepingWidthUntilTheEdge() {
        // Mid-travel, still clear of the edge → translates right, full width retained.
        let bar = PodcastUnderlineGeometry.tailExit(
            lastWord: CGRect(x: 5, y: 0, width: 20, height: 18), rowRightEdge: 100, fraction: 0.5
        )
        #expect(bar?.minX == 52.5)   // 5 + (100-5)*0.5
        #expect(bar?.width == 20)
    }

    @Test func tailExitClipsAgainstTheEdgeNearTheEnd() {
        // Close to the edge → leading part has slid off, width shrinks.
        let bar = PodcastUnderlineGeometry.tailExit(
            lastWord: CGRect(x: 5, y: 0, width: 20, height: 18), rowRightEdge: 100, fraction: 0.9
        )
        #expect(bar?.minX == 90.5)   // 5 + 95*0.9
        #expect(bar?.width == 9.5)   // clipped at 100
    }

    @Test func tailExitVanishesAtEnd() {
        // fraction 1 → fully slid off the trailing edge → nothing to draw.
        #expect(PodcastUnderlineGeometry.tailExit(
            lastWord: CGRect(x: 5, y: 0, width: 20, height: 18), rowRightEdge: 100, fraction: 1
        ) == nil)
    }

    @Test func headEnterIsAbsentAtStart() {
        // fraction 0 → zero width → the entering head has not appeared yet.
        #expect(PodcastUnderlineGeometry.headEnter(
            firstWord: CGRect(x: 10, y: 30, width: 40, height: 18), rowLeftEdge: 10, fraction: 0
        ) == nil)
    }

    @Test func headEnterGrowsInFromTheLeadingEdge() {
        // Mid-travel → a partial bar anchored at the leading edge, growing right.
        let bar = PodcastUnderlineGeometry.headEnter(
            firstWord: CGRect(x: 10, y: 30, width: 40, height: 18), rowLeftEdge: 10, fraction: 0.5
        )
        #expect(bar?.minX == 10)
        #expect(bar?.width == 20)     // 40 * 0.5
        #expect(bar?.bottomY == 48)
    }

    @Test func headEnterLandsExactlyOnFirstWordAtEnd() {
        // fraction 1 → exactly the first word (continuous handoff into the normal
        // underline once the cell becomes current).
        let bar = PodcastUnderlineGeometry.headEnter(
            firstWord: CGRect(x: 10, y: 30, width: 40, height: 18), rowLeftEdge: 10, fraction: 1
        )
        #expect(bar?.minX == 10)
        #expect(bar?.width == 40)
        #expect(bar?.bottomY == 48)
    }
}

/// `PodcastTranscriptIdentity` is the O(1) fingerprint the transcript token tree
/// uses as its `EquatableView` basis: it must change iff the rendered token tree
/// must change (episode swap, sentence count, span) and stay stable otherwise. It
/// must NOT deep-compare the whole `[PodcastSentence]` array (that O(n·words)
/// compare is the very cost the Equatable short-circuit avoids).
struct PodcastTranscriptIdentityTests {
    private func sentence(_ id: Int, _ start: TimeInterval, _ end: TimeInterval, _ text: String = "x") -> PodcastSentence {
        PodcastSentence(id: id, speaker: "A", text: text, startTime: start, endTime: end, words: [])
    }

    @Test func emptyTranscriptHasStableIdentity() {
        #expect(PodcastTranscriptIdentity(sentences: []) == PodcastTranscriptIdentity(sentences: []))
    }

    @Test func sameTranscriptIsEqual() {
        let s = [sentence(0, 0, 2), sentence(1, 2, 5)]
        #expect(PodcastTranscriptIdentity(sentences: s) == PodcastTranscriptIdentity(sentences: s))
    }

    @Test func differentCountIsUnequal() {
        let a = [sentence(0, 0, 2)]
        let b = [sentence(0, 0, 2), sentence(1, 2, 5)]
        #expect(PodcastTranscriptIdentity(sentences: a) != PodcastTranscriptIdentity(sentences: b))
    }

    @Test func episodeSwapWithSameCountButDifferentSpanIsUnequal() {
        // Sentence ids restart at 0 each episode, so an id-only key could collide.
        // The span (first.start + last.end) distinguishes a same-length new episode.
        let ep1 = [sentence(0, 0, 2), sentence(1, 2, 5)]
        let ep2 = [sentence(0, 10, 12), sentence(1, 12, 15)]
        #expect(PodcastTranscriptIdentity(sentences: ep1) != PodcastTranscriptIdentity(sentences: ep2))
    }

    @Test func samePlayheadDifferenceDoesNotAffectIdentity() {
        // The fingerprint depends only on the transcript, never on a playhead/time,
        // so two identities built from the same sentences are equal regardless of
        // how often the playhead moves between builds.
        let s = [sentence(0, 0, 2), sentence(1, 2, 5), sentence(2, 5, 9)]
        let first = PodcastTranscriptIdentity(sentences: s)
        let second = PodcastTranscriptIdentity(sentences: s)
        #expect(first == second)
        #expect(first.hashValue == second.hashValue)
    }
}
