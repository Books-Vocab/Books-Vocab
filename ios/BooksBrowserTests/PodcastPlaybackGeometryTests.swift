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
            #expect(r.index >= 0)
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
    @Test func hiddenWhenNoActiveWord() {
        #expect(PodcastUnderlineGeometry.bar(wordRects: [0: CGRect(x: 0, y: 0, width: 10, height: 4)], activeIndex: -1, fraction: 0) == nil)
    }

    @Test func hiddenWhenRectMissing() {
        #expect(PodcastUnderlineGeometry.bar(wordRects: [:], activeIndex: 0, fraction: 0.5) == nil)
    }

    @Test func glidesTowardNextWordOnSameRow() {
        let rects = [
            0: CGRect(x: 0, y: 0, width: 20, height: 18),
            1: CGRect(x: 30, y: 0, width: 40, height: 18),
        ]
        let start = PodcastUnderlineGeometry.bar(wordRects: rects, activeIndex: 0, fraction: 0)!
        #expect(start.minX == 0)
        #expect(start.width == 20)
        let mid = PodcastUnderlineGeometry.bar(wordRects: rects, activeIndex: 0, fraction: 0.5)!
        #expect(mid.minX == 15)   // lerp 0→30
        #expect(mid.width == 30)  // lerp 20→40
        let end = PodcastUnderlineGeometry.bar(wordRects: rects, activeIndex: 0, fraction: 1)!
        #expect(end.minX == 30)
        #expect(end.width == 40)
    }

    @Test func staysOnActiveWordAcrossLineBreak() {
        let rects = [
            0: CGRect(x: 50, y: 0, width: 20, height: 18),
            1: CGRect(x: 0, y: 30, width: 40, height: 18),  // next row (below)
        ]
        let bar = PodcastUnderlineGeometry.bar(wordRects: rects, activeIndex: 0, fraction: 0.9)!
        #expect(bar.minX == 50)
        #expect(bar.width == 20)
    }

    @Test func staysOnActiveWordWhenNextWordOnAnyOtherRow() {
        // Different row regardless of direction (next word above) → no horizontal drag.
        let rects = [
            0: CGRect(x: 50, y: 30, width: 20, height: 18),
            1: CGRect(x: 0, y: 0, width: 40, height: 18),  // different row (above)
        ]
        let bar = PodcastUnderlineGeometry.bar(wordRects: rects, activeIndex: 0, fraction: 0.9)!
        #expect(bar.minX == 50)
        #expect(bar.width == 20)
    }
}

struct PodcastScrollGeometryTests {
    @Test func anchorClimbsThroughCenter() {
        #expect(PodcastScrollGeometry.centerAnchor(fraction: 0.5).y == 0.5)
        #expect(PodcastScrollGeometry.centerAnchor(fraction: 0).y < 0.5)
        #expect(PodcastScrollGeometry.centerAnchor(fraction: 1).y > 0.5)
        #expect(PodcastScrollGeometry.centerAnchor(fraction: 0.5).x == 0.5)
    }

    @Test func anchorClampsOutOfRangeFraction() {
        #expect(PodcastScrollGeometry.centerAnchor(fraction: -1) == PodcastScrollGeometry.centerAnchor(fraction: 0))
        #expect(PodcastScrollGeometry.centerAnchor(fraction: 2) == PodcastScrollGeometry.centerAnchor(fraction: 1))
    }

    @Test func sentenceFractionRampsAndClamps() {
        #expect(PodcastScrollGeometry.sentenceFraction(time: 10, start: 10, end: 20) == 0)
        #expect(PodcastScrollGeometry.sentenceFraction(time: 15, start: 10, end: 20) == 0.5)
        #expect(PodcastScrollGeometry.sentenceFraction(time: 20, start: 10, end: 20) == 1)
        #expect(PodcastScrollGeometry.sentenceFraction(time: 5, start: 10, end: 20) == 0)
        #expect(PodcastScrollGeometry.sentenceFraction(time: 99, start: 10, end: 20) == 1)
    }

    @Test func sentenceFractionDegenerateWindow() {
        // Zero-length sentence: before start → 0, at/after → 1 (no divide-by-zero).
        #expect(PodcastScrollGeometry.sentenceFraction(time: 10, start: 10, end: 10) == 1)
        #expect(PodcastScrollGeometry.sentenceFraction(time: 9, start: 10, end: 10) == 0)
    }
}
