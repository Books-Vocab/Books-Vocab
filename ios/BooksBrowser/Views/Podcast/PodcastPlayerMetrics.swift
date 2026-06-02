import SwiftUI

/// Podcast 播放器專用版面參數（seek bar、控制列）。
enum PodcastPlayerMetrics {
    static let seekBarTrackHeight: CGFloat = 5
    static let seekBarThumbSize: CGFloat = 16
    static let seekBarThumbOffset: CGFloat = 8
    static let seekBarHitArea: CGFloat = 20
    static let controlsClusterSpacing: CGFloat = 8
    static let controlsBottomPadding: CGFloat = 20
}

/// Snapshot used to extrapolate a continuous playback position between the
/// 15 Hz `AVPlayer` time ticks. Refreshed on every real tick / seek / play /
/// pause / rate change so extrapolation error never accumulates beyond one
/// tick (~66 ms). `wallClock` and the consuming `TimelineView`'s `context.date`
/// MUST share the `Date.timeIntervalSinceReferenceDate` basis.
struct PlaybackAnchor: Equatable {
    var mediaTime: TimeInterval
    var wallClock: TimeInterval
    var rate: Double
}

/// Pure clock math for the continuous subtitle playhead. No SwiftUI / AVFoundation
/// dependency so it is unit-testable in isolation (see `PodcastPlaybackGeometryTests`).
enum PodcastPlaybackClock {
    static func makeAnchor(mediaTime: TimeInterval, now: TimeInterval, rate: Double) -> PlaybackAnchor {
        PlaybackAnchor(mediaTime: mediaTime, wallClock: now, rate: rate)
    }

    /// Linear extrapolation of media time from the anchor. `rate == 0` (paused /
    /// seeking) holds the position still. Clamped to `[0, duration]` when
    /// `duration > 0`, else lower-bounded at 0.
    static func projectedTime(anchor: PlaybackAnchor, now: TimeInterval, duration: TimeInterval) -> TimeInterval {
        let raw = anchor.mediaTime + (now - anchor.wallClock) * anchor.rate
        let lower = max(0, raw)
        guard duration > 0 else { return lower }
        return min(lower, duration)
    }

    /// Re-anchor on a rate change WITHOUT a position jump. Order is pinned:
    /// project the current position from the OLD anchor first, then stamp `now`
    /// and apply `newRate` — projecting after swapping the rate would warp the
    /// position at the switch instant.
    static func anchorAfterRateChange(
        old: PlaybackAnchor, now: TimeInterval, newRate: Double, duration: TimeInterval
    ) -> PlaybackAnchor {
        let media = projectedTime(anchor: old, now: now, duration: duration)
        return PlaybackAnchor(mediaTime: media, wallClock: now, rate: newRate)
    }
}

/// Locates the active word within a sentence's cues at a given media time, plus
/// the fractional progress through that word. Mirrors the gap-fallback semantics
/// of `PodcastSubtitleEngine.currentCue`: the active word is the last cue whose
/// `startTime <= time`, so silence gaps (time past a word's end but before the
/// next word's start) hold the previous word at `fraction == 1` rather than
/// strobing the highlight off.
enum PodcastWordProgress {
    /// `index == -1` (fraction 0) before the first word / for empty input.
    static func locate(time: TimeInterval, words: [PodcastSubtitleCue]) -> (index: Int, fraction: Double) {
        guard let first = words.first else { return (-1, 0) }
        if time < first.startTime { return (-1, 0) }
        // Largest index with startTime <= time (mirrors currentCue's `hi` fallback).
        var lo = 0, hi = words.count - 1, found = -1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if words[mid].startTime <= time { found = mid; lo = mid + 1 } else { hi = mid - 1 }
        }
        guard found >= 0 else { return (-1, 0) }
        let w = words[found]
        let dur = w.endTime - w.startTime
        let fraction: Double
        if dur <= 0 {
            fraction = time >= w.endTime ? 1 : 0
        } else {
            fraction = min(1, max(0, (time - w.startTime) / dur))
        }
        return (found, fraction)
    }
}

/// Geometry of the single continuous underline capsule. As the active word
/// plays (fraction 0→1) the capsule glides from the active word toward the next
/// word ON THE SAME ROW, so motion is continuous instead of teleporting per
/// word. Across a line break (next word on a different row) it returns the
/// active word's bar unchanged — the view applies a short spring for that
/// non-continuous hop rather than dragging a bar across the row gap.
enum PodcastUnderlineGeometry {
    struct Bar: Equatable {
        var minX: CGFloat
        var width: CGFloat
        var bottomY: CGFloat  // word baseline bottom; view adds the 3pt offset
    }

    /// Returns nil when there is no active word (`activeIndex < 0`, e.g. before
    /// the first word) or its rect is not yet measured. The `wordFollowEnabled`
    /// toggle is gated at the call site (the overlay closure), not here.
    static func bar(wordRects: [Int: CGRect], activeIndex: Int, fraction: Double) -> Bar? {
        guard activeIndex >= 0, let a = wordRects[activeIndex] else { return nil }
        guard let b = wordRects[activeIndex + 1], b.minY == a.minY else {
            return Bar(minX: a.minX, width: a.width, bottomY: a.maxY)
        }
        let t = CGFloat(min(1, max(0, fraction)))
        return Bar(
            minX: a.minX + (b.minX - a.minX) * t,
            width: a.width + (b.width - a.width) * t,
            bottomY: a.maxY + (b.maxY - a.maxY) * t
        )
    }
}

/// Continuous scroll centering for the follow-mode "替代 A" path: keep
/// `scrollTo(currentId, anchor:)` but drift the anchor with intra-sentence
/// progress so the current sentence eases upward through center instead of
/// snapping once per sentence.
enum PodcastScrollGeometry {
    /// Progress (0…1) of `time` through a sentence's `[start, end]` window.
    /// Degenerate / zero-length sentences (and `time` at/after end) return 1;
    /// `time` before start returns 0.
    static func sentenceFraction(time: TimeInterval, start: TimeInterval, end: TimeInterval) -> Double {
        guard end > start else { return time < start ? 0 : 1 }
        return min(1, max(0, (time - start) / (end - start)))
    }

    /// Continuous content offset for an offset-driven (non-`scrollTo`) follow
    /// mode. `centers[id]` is each sentence's vertical center in the content's
    /// own coordinate space (offset-independent). The focal point is the current
    /// sentence's center, interpolated toward the NEXT sentence's center by the
    /// intra-sentence progress — so the focus glides continuously through the
    /// viewport center with NO per-sentence jump (at a boundary, fraction→1 lands
    /// exactly on the next center, which then becomes `current` at fraction 0).
    /// Returns `viewportHeight/2 - focalY`. nil when the current center is not
    /// yet measured (caller holds the last good offset).
    ///
    /// `sentences` MUST be ordered by `startTime` (as the engine emits them).
    static func centerOffset(
        time: TimeInterval,
        sentences: [PodcastSentence],
        centers: [Int: CGFloat],
        viewportHeight: CGFloat
    ) -> CGFloat? {
        guard !sentences.isEmpty else { return nil }
        // Current = last sentence with startTime <= time (clamp to first before start).
        var idx = 0
        var lo = 0, hi = sentences.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if sentences[mid].startTime <= time { idx = mid; lo = mid + 1 } else { hi = mid - 1 }
        }
        let cur = sentences[idx]
        guard let curCenter = centers[cur.id] else { return nil }
        let focalY: CGFloat
        if idx + 1 < sentences.count, let nextCenter = centers[sentences[idx + 1].id] {
            let f = CGFloat(sentenceFraction(time: time, start: cur.startTime, end: cur.endTime))
            focalY = curCenter + (nextCenter - curCenter) * f
        } else {
            focalY = curCenter
        }
        return viewportHeight / 2 - focalY
    }
}

enum PodcastSeekBarGeometry {
    static func time(
        locationX: CGFloat,
        width: CGFloat,
        duration: TimeInterval
    ) -> TimeInterval {
        guard width > 0, duration > 0 else { return 0 }
        let ratio = max(0, min(1, Double(locationX / width)))
        return ratio * duration
    }

    static func progressWidth(
        time: TimeInterval,
        duration: TimeInterval,
        totalWidth: CGFloat
    ) -> CGFloat {
        guard duration > 0, totalWidth > 0 else { return 0 }
        let ratio = max(0, min(1, time / duration))
        return CGFloat(ratio) * totalWidth
    }

    static func bufferedWidth(
        bufferedEnd: TimeInterval,
        duration: TimeInterval,
        totalWidth: CGFloat
    ) -> CGFloat {
        guard duration > 0, totalWidth > 0 else { return 0 }
        let ratio = max(0, min(1, bufferedEnd / duration))
        return CGFloat(ratio) * totalWidth
    }
}
