#if os(iOS)
import SwiftUI
import Inject

/// Chat-style transcript: sentences laid out as left/right bubbles by speaker.
///
/// Design principles:
///   • flat — no shadow, no scale lift, no blur
///   • follow-by-default: auto-scrolls with the current sentence. On iOS a user
///     drag disables follow and surfaces a "追隨當前" pill (tap → re-enable +
///     recenter). On Mac Catalyst, mouse-wheel/trackpad scrolling is indirect
///     and never fires DragGesture, so the pill is always shown as an explicit
///     toggle ("停止跟隨" ⇄ "追隨當前"). See `shouldShowFollowControl`.
///   • alignment distinguishes speakers (host[0] → left, host[1] → right);
///     the speaker label is shown only when it changes from the previous row.
///   • layout transitions are explicitly animated (bubble bg, underline,
///     label show/hide) to avoid the snap-change jank of dt→0 shifts.
///
/// ## Scroll engine (the scroll-freeze fix)
///
/// HISTORY: an earlier offset-driven engine drove follow with an outer
/// `TimelineView(.animation)` that recomputed a manual `.offset` over a NON-lazy
/// column EVERY display frame. That re-evaluated the whole token tree (hundreds of
/// sentences × their per-word flow layout + per-sentence `GeometryReader`
/// preferences) per frame and froze the UI on entry — confirmed on-device:
/// rendering only 30 sentences still froze (so NOT a realization-count cost), and
/// the device logged `Bound preference … multiple times per frame`. Root cause was
/// the engine itself, not the token count.
///
/// NOW: a native `ScrollView` + `ScrollViewReader` + `LazyVStack` (GPU-composited
/// scroll, off the SwiftUI per-frame eval path; only on-screen bubbles realized).
///   • Follow = one animated `scrollTo(currentId, anchor: .center)` per sentence
///     boundary (`onChange(of: currentId)` → `followScroll`); zero per-frame work.
///   • Each row is a `PodcastBubbleCell` wrapped in its OWN `.equatable()`, so a
///     sentence advance re-bodies only the ~2 cells whose `isCurrent` flipped —
///     not the whole column (the column itself is no longer `Equatable`). This is
///     the per-advance-rebuild fix; the playhead never enters any cell's `==`.
///   • The word underline is a per-frame continuous engine on the CURRENT cell
///     only, reading the LIVE playhead through a reference (`liveAnchor`) inside
///     its own `TimelineView`. Across a line break it renders as a portal (two
///     capsules via `PodcastUnderlineGeometry.segments`) — no animation modifier,
///     geometry per frame.
struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    /// Continuous-playhead source (reference): the active word + its underline are
    /// derived every frame by extrapolating `liveAnchor.value` and running
    /// `PodcastWordProgress.locate` over the current sentence's cues. A reference
    /// (not a `PlaybackAnchor` value) so the Equatable transcript child can be
    /// skipped per frame while the per-frame underline/offset still read the live
    /// playhead — see `PodcastLiveAnchor`.
    let liveAnchor: PodcastLiveAnchor
    let duration: TimeInterval
    let isPlaying: Bool
    let hostNames: [String]
    let subtitleSize: PodcastSubtitleSize
    let initialScrollPositionResolved: Bool
    /// Follow-scroll target id, LEADING the spoken sentence by ~0.5 s (ViewModel's
    /// `scrollLeadSentenceId`). Drives auto-follow only — highlight/underline stay
    /// keyed on the precise `currentId`, so the scroll arrives early while the
    /// highlight stays exact. On a seek the VM pins this to the current sentence
    /// (★B1), so a tapped bubble centers itself, not its successor.
    let scrollLeadId: Int?
    /// 詞庫已查詞集（`translationHandler.lookedUpWords`），驅動字幕詞庫螢光筆。原始未正規化
    /// 字串;column 每次 render 折疊一次供比對。
    let lookedUpWords: Set<String>
    let highlightPreferences: VocabHighlightPreferences
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void

    /// Assigns each distinct speaker a stable slot by first appearance in the
    /// transcript. Decouples alignment + tint from `hostNames` — earlier the
    /// view required the SRT speaker tag to exactly match a hostNames entry,
    /// so any mismatch (case, whitespace, untracked guest) collapsed every
    /// bubble onto the left. Now even unknown speakers get a consistent slot.
    private var speakerSlots: [String: Int] {
        var slots: [String: Int] = [:]
        var next = 0
        // Seed hostNames first so the documented host[0]=left / host[1]=right
        // ordering still wins when names line up.
        for name in hostNames where slots[name] == nil {
            slots[name] = next
            next += 1
        }
        for sentence in sentences where slots[sentence.speaker] == nil {
            slots[sentence.speaker] = next
            next += 1
        }
        return slots
    }

    var body: some View {
        PodcastTranscriptViewport(
            sentences: sentences,
            renderState: renderState,
            liveAnchor: liveAnchor,
            duration: duration,
            isPlaying: isPlaying,
            hostNames: hostNames,
            subtitleSize: subtitleSize,
            initialScrollPositionResolved: initialScrollPositionResolved,
            scrollLeadId: scrollLeadId,
            lookedUpWords: lookedUpWords,
            highlightPreferences: highlightPreferences,
            speakerSlots: speakerSlots,
            onSentenceTap: onSentenceTap,
            onWordTap: onWordTap,
            onPhraseTap: onPhraseTap,
            onExplainTap: onExplainTap
        )
    }
}

#Preview("Podcast Subtitle XL") {
    let cues1 = [
        PodcastSubtitleCue(id: 1, startTime: 0, endTime: 0.4, speaker: "Maya", word: "OK"),
        PodcastSubtitleCue(id: 2, startTime: 0.4, endTime: 0.8, speaker: "Maya", word: "so"),
        PodcastSubtitleCue(id: 3, startTime: 0.8, endTime: 1.2, speaker: "Maya", word: "here's"),
        PodcastSubtitleCue(id: 4, startTime: 1.2, endTime: 1.6, speaker: "Maya", word: "a"),
        PodcastSubtitleCue(id: 5, startTime: 1.6, endTime: 2.2, speaker: "Maya", word: "question."),
    ]
    let cues2 = [
        PodcastSubtitleCue(id: 6, startTime: 2.2, endTime: 2.7, speaker: "Kai", word: "We"),
        PodcastSubtitleCue(id: 7, startTime: 2.7, endTime: 3.0, speaker: "Kai", word: "live"),
        PodcastSubtitleCue(id: 8, startTime: 3.0, endTime: 3.2, speaker: "Kai", word: "in"),
        PodcastSubtitleCue(id: 9, startTime: 3.2, endTime: 3.5, speaker: "Kai", word: "the"),
        PodcastSubtitleCue(id: 10, startTime: 3.5, endTime: 4.0, speaker: "Kai", word: "most"),
        PodcastSubtitleCue(id: 11, startTime: 4.0, endTime: 4.7, speaker: "Kai", word: "comfortable"),
        PodcastSubtitleCue(id: 12, startTime: 4.7, endTime: 5.2, speaker: "Kai", word: "era."),
    ]
    let s1 = PodcastSentence(id: 0, speaker: "Maya", text: "OK so here's a question.", startTime: 0, endTime: 2.2, words: cues1)
    let s2 = PodcastSentence(id: 1, speaker: "Kai", text: "We live in the most comfortable era.", startTime: 2.2, endTime: 5.2, words: cues2)

    return AppThemeContainer {
        PodcastSentenceLevelView(
            sentences: [s1, s2],
            renderState: SubtitleRenderState(from: s2, hostNames: ["Maya", "Kai"]),
            liveAnchor: PodcastLiveAnchor(value: PlaybackAnchor(mediaTime: 4.3, wallClock: 0, rate: 0)),
            duration: 5.2,
            isPlaying: false,
            hostNames: ["Maya", "Kai"],
            subtitleSize: .xLarge,
            initialScrollPositionResolved: true,
            scrollLeadId: 1,
            lookedUpWords: ["comfortable"],
            highlightPreferences: .default,
            onSentenceTap: { _ in },
            onWordTap: { _, _ in },
            onPhraseTap: { _, _ in },
            onExplainTap: { _, _ in }
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
