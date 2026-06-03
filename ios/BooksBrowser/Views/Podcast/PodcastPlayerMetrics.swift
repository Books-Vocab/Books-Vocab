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

/// Reference-typed live channel for the current `PlaybackAnchor`.
///
/// Why a reference: `PodcastSentenceLevelView`'s transcript token tree is wrapped
/// in an `EquatableView` so SwiftUI skips re-evaluating thousands of word tokens
/// on every display frame (the scroll-freeze fix). But the per-frame underline +
/// follow offset still need the *live* playhead each frame. If the anchor were
/// passed by VALUE into the Equatable child, the child would capture whichever
/// anchor existed at its last `body` eval and freeze (stale-anchor bug). Passing
/// this reference instead lets the inner per-frame `TimelineView` closures read
/// `liveAnchor.value` fresh every frame — the reference identity is stable across
/// frames (so it never disturbs the Equatable short-circuit) while its contents
/// stay current. The pure `PlaybackAnchor` value type and all clock math are
/// unchanged; the ViewModel mirrors every `playbackAnchor` mutation here in one
/// `didSet`, so no call site can forget to update it.
@MainActor
final class PodcastLiveAnchor {
    var value: PlaybackAnchor
    init(value: PlaybackAnchor) { self.value = value }
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
        guard let b = wordRects[activeIndex + 1], abs(b.minY - a.minY) < a.height * 0.5 else {
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

/// O(1) identity of a transcript's token tree, used as the `EquatableView` basis
/// for `PodcastSentenceLevelView`'s transcript column and to detect episode swaps.
/// The column explodes every sentence into per-word `Text` tokens +
/// `CachedFlowLayout` (thousands of view values); the `.equatable()` wrapper lets
/// SwiftUI short-circuit its `body` when nothing token-affecting changed — and
/// that short-circuit must be cheap, so it compares THIS fingerprint, never the
/// full `[PodcastSentence]` array (whose O(n·words) `==` is the very cost we avoid).
///
/// The fingerprint changes iff the rendered token tree must change:
///   • `count` — sentences added/removed
///   • `firstStart` + `lastEnd` — distinguishes an episode swap that happens to
///     keep the same count (sentence ids restart at 0 each episode, so an
///     id-only key could collide; the time span cannot).
struct PodcastTranscriptIdentity: Equatable, Hashable {
    let count: Int
    let firstStart: TimeInterval
    let lastEnd: TimeInterval

    init(sentences: [PodcastSentence]) {
        self.count = sentences.count
        self.firstStart = sentences.first?.startTime ?? 0
        self.lastEnd = sentences.last?.endTime ?? 0
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
