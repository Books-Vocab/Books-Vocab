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

/// Geometry of the continuous reading underline. As the active word plays
/// (fraction 0→1) the underline glides in reading order from the active word
/// toward the next. ON THE SAME ROW this is one capsule sliding right. ACROSS A
/// LINE BREAK it becomes a "portal": the unrolled reading path is sliced at the
/// row boundary, so the trailing part stays at the end of the current row while
/// the leading part appears at the start of the next row, apportioned by
/// `fraction` — exactly how a wrapping text selection looks. This makes the
/// motion continuous through the wrap instead of teleporting (and never relies on
/// a spring chasing a moving target, which would visually skip the next row's
/// first word). A sentence's last word has no next cue → one bar under it; the
/// next sentence's underline is a separate render (sentence/paragraph break).
enum PodcastUnderlineGeometry {
    struct Bar: Equatable {
        var minX: CGFloat
        var width: CGFloat
        var bottomY: CGFloat  // word baseline bottom; view adds the 3pt offset
    }

    /// Up to two capsule segments. Empty when there is no active word
    /// (`activeIndex < 0`) or its rect is not yet measured. The `wordFollowEnabled`
    /// toggle is gated at the call site (the overlay closure), not here.
    static func segments(wordRects: [Int: CGRect], activeIndex: Int, fraction: Double) -> [Bar] {
        guard activeIndex >= 0, let a = wordRects[activeIndex] else { return [] }
        let t = CGFloat(min(1, max(0, fraction)))
        guard let b = wordRects[activeIndex + 1] else {
            return [Bar(minX: a.minX, width: a.width, bottomY: a.maxY)]
        }
        let width = a.width + (b.width - a.width) * t
        // Same visual row → a single sliding capsule (tolerance absorbs layout
        // rounding so a sub-pixel minY delta is not read as a line break).
        if abs(b.minY - a.minY) < a.height * 0.5 {
            return [Bar(
                minX: a.minX + (b.minX - a.minX) * t,
                width: width,
                bottomY: a.maxY + (b.maxY - a.maxY) * t
            )]
        }
        // Portal across a line break. Unroll the reading path: slide right to the
        // end of `a`'s row, then continue from the left edge of `b`'s row. Use the
        // whole row's extent (not just the a/b pair) so the travel matches what the
        // eye sees wrapping.
        let row1End = wordRects.values
            .filter { abs($0.minY - a.minY) < a.height * 0.5 }
            .map(\.maxX).max() ?? a.maxX
        let row2Start = wordRects.values
            .filter { abs($0.minY - b.minY) < b.height * 0.5 }
            .map(\.minX).min() ?? b.minX
        let seg1 = max(0, row1End - a.minX)     // distance to exit row1
        let seg2 = max(0, b.minX - row2Start)   // distance from row2 start to b
        let total = seg1 + seg2
        let uL = t * total                      // left edge along the unrolled path
        let uR = uL + width
        var bars: [Bar] = []
        if uL < seg1 {                          // tail still on row1
            let hi = min(uR, seg1)
            bars.append(Bar(minX: a.minX + uL, width: hi - uL, bottomY: a.maxY))
        }
        if uR > seg1 {                          // head arrived on row2
            let lo = max(uL, seg1)
            bars.append(Bar(minX: row2Start + (lo - seg1), width: uR - lo, bottomY: b.maxY))
        }
        return bars
    }

    /// Cross-SENTENCE edge relay (Option B "邊緣接力"). A sentence boundary spans two
    /// separate bubbles (two coordinate spaces), so the intra-cell `segments` portal
    /// can't reach across it. Instead each cell renders ITS half of the handoff:
    /// the leaving cell slides its last-word bar OFF the trailing edge (`tailExit`)
    /// while the entering cell grows a bar IN from under its first word
    /// (`headEnter`) — both driven by the SAME fraction. Device-verified that the
    /// SRT is gap-free (`N.endTime == N+1.startTime`), so the leaving last word's
    /// play window == the entering window, and the two fractions are identical →
    /// the two halves stay in lock-step without any cross-cell signal.

    /// Leaving half: the last-word bar translates right toward `rowRightEdge`,
    /// clipped at the edge, shrinking to nothing at `fraction == 1` (slid fully off).
    /// `nil` once it has no visible width (so the caller draws nothing post-exit).
    static func tailExit(lastWord: CGRect, rowRightEdge: CGFloat, fraction: Double) -> Bar? {
        let f = CGFloat(min(1, max(0, fraction)))
        let minX = lastWord.minX + (rowRightEdge - lastWord.minX) * f
        let maxX = min(minX + lastWord.width, rowRightEdge)
        let width = maxX - minX
        guard width > 0.5 else { return nil }
        return Bar(minX: minX, width: width, bottomY: lastWord.maxY)
    }

    /// Entering half: a bar grows in from `rowLeftEdge` and lands exactly under
    /// `firstWord` at `fraction == 1`. `nil` at `fraction == 0` (zero width) so the
    /// head appears only once the handoff has started.
    static func headEnter(firstWord: CGRect, rowLeftEdge: CGFloat, fraction: Double) -> Bar? {
        let f = CGFloat(min(1, max(0, fraction)))
        let maxX = rowLeftEdge + (firstWord.maxX - rowLeftEdge) * f
        let minX = max(rowLeftEdge, maxX - firstWord.width)
        let width = maxX - minX
        guard width > 0.5 else { return nil }
        return Bar(minX: minX, width: width, bottomY: firstWord.maxY)
    }
}

/// O(1) identity of a transcript's token tree, used as the `EquatableView` basis
/// for `PodcastSentenceLevelView`'s transcript column and to detect episode swaps.
/// Each sentence renders a `UITextView` whose TextKit layout + per-frame underline
/// is non-trivial; the `.equatable()` wrapper lets
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

/// 時鐘格式化（`m:ss` / `h:mm:ss`）。純數字格式、locale 無關，故不走 L10n。
/// 集中此處供 `PodcastContinueCard` / `PodcastContinueRailCard` 共用（消除
/// 先前兩處 byte-identical 的 `formatClock` 重複）。
enum PodcastClock {
    static func format(_ sec: Double) -> String {
        guard sec.isFinite, sec >= 0 else { return "0:00" } // i18n-allow: clock format
        let total = Int(sec)
        let h = total / 3600
        let m = (total % 3600) / 60
        let s = total % 60
        if h > 0 {
            return String(format: "%d:%02d:%02d", h, m, s) // i18n-allow: clock format
        }
        return String(format: "%d:%02d", m, s) // i18n-allow: clock format
    }
}
