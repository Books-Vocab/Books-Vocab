#if os(iOS)
import SwiftUI
import UIKit
import Inject

/// Selection state for the long-press → phrase-select flow. Shared between the
/// outer view (which owns it as `@State`) and the Equatable transcript child
/// (which reads it to swap a bubble into `PodcastSelectableSentenceTextView` and
/// clears it on phrase/explain commit). Kept top-level + `Equatable` so it can
/// participate in the transcript column's `EquatableView` short-circuit.
struct PodcastSentenceSelection: Equatable {
    let sentenceId: Int
    let initialRange: NSRange?
}

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
/// ## Per-frame cost model (the scroll-freeze fix)
///
/// The follow scroll + word underline are continuous engines that must update
/// every display frame (60–120 Hz). The transcript itself, however, is a
/// non-lazy column of hundreds of sentences, each exploding into per-word `Text`
/// tokens + `CachedFlowLayout` + anchor preferences — thousands of view values.
/// Re-evaluating that whole struct tree every frame saturated the main thread and
/// froze scrolling. So the work is split:
///   • `PodcastTranscriptColumn` (the token tree) is wrapped in `.equatable()`.
///     Its `==` compares an O(1) `PodcastTranscriptIdentity` + the few
///     sentence-level inputs that actually change the tokens (current sentence,
///     selection, size, word-follow toggle). Per-frame playhead ticks compare
///     equal → SwiftUI skips its `body`, reusing the already-built tree.
///   • The per-frame follow `.offset` is applied to that Equatable child as a
///     render transform (not a body change), driven by the outer `TimelineView`.
///   • The word underline reads the LIVE playhead each frame through a reference
///     (`liveAnchor`), so the Equatable-skip never starves it of fresh time.
struct PodcastSentenceLevelView: View {
    @ObserveInjection private var inject

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
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    @Environment(\.appSkin) private var skin
    @AppStorage("podcast.wordFollowEnabled") private var wordFollowEnabled: Bool = true

    @State private var isFollowing = true
    @State private var selectionState: PodcastSentenceSelection?
    /// Measured vertical center of each sentence within the transcript column's
    /// OWN coordinate space (offset-independent), keyed by sentence id. Drives
    /// the continuous follow offset.
    @State private var sentenceCenters: [Int: CGFloat] = [:]
    /// Content offset while NOT following (manual browse). Seeded from the live
    /// follow offset the instant follow disengages → seamless hand-off, no jump.
    @State private var manualOffset: CGFloat = 0
    @State private var dragStartOffset: CGFloat = 0
    @State private var viewportHeight: CGFloat = 0

    private var currentId: Int? { renderState?.sentenceId }

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
        // Computed ONCE per parent render (not per frame): the follow
        // `TimelineView` below reconstructs `PodcastTranscriptColumn` every tick to
        // run its Equatable check, so any O(n) input it needs must be hoisted out
        // of that closure or it re-runs at the display refresh rate.
        let slots = speakerSlots
        return GeometryReader { vp in
            ZStack(alignment: .bottom) {
                // Offset-driven follow: a single continuous `.offset` positions
                // the transcript so the spoken sentence glides through the
                // viewport center with NO per-sentence jump. (`scrollTo` can only
                // align same-fraction points of view+viewport, so it cannot keep
                // an intra-sentence point centered — a manual offset is required.)
                // When not following, the same offset is driven by the user's drag.
                //
                // CRUCIAL: only the `.offset` value is recomputed per frame here.
                // `transcriptColumn` is wrapped in `.equatable()` so its body is
                // NOT re-evaluated every tick — SwiftUI just re-applies the new
                // offset transform to the already-built token tree.
                TimelineView(.animation(paused: !isPlaying || !isFollowing)) { ctx in
                    let offset = isFollowing
                        ? followOffset(viewportHeight: vp.size.height, now: ctx.date.timeIntervalSinceReferenceDate)
                        : manualOffset
                    transcriptColumn(speakerSlots: slots)
                        .offset(y: offset)
                        // Until centers are first measured, `offset` falls back to
                        // 0 (column pinned to top). Hide that one pre-measurement
                        // frame so the content appears already-centered instead of
                        // snapping top→center on load. The column still lays out
                        // while invisible, so the GeometryReaders populate centers.
                        .opacity(sentenceCenters.isEmpty ? 0 : 1)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .clipped()
                .contentShape(Rectangle())
                // Manual browse: drag hands off seamlessly from the live follow
                // offset (no jump), then moves 1:1. `simultaneousGesture` so word
                // tap / long-press still resolve (they have ~0 movement).
                .simultaneousGesture(browseDrag(viewportHeight: vp.size.height))
                .onPreferenceChange(SentenceCenterKey.self) { sentenceCenters = $0 }
                .onAppear { viewportHeight = vp.size.height }
                .onChange(of: vp.size.height) { _, h in viewportHeight = h }
                // In-place episode swap: the player reuses this same view instance
                // (`.task(id:)` / `reloadEpisode()`) and replaces `sentences` without
                // tearing down/recreating the view, so `sentenceCenters` keeps the
                // PREVIOUS episode's measurements. That left the no-jump guard
                // (`.opacity(sentenceCenters.isEmpty ? 0 : 1)`) armed against stale
                // data → the first frame of the new transcript rendered with old
                // centers, flashing a misaligned frame before snapping correct.
                // Reset to empty so the guard re-arms (hides the pre-measurement
                // frame) until the new episode's preference pass repopulates centers.
                // Keyed on the O(1) `PodcastTranscriptIdentity` (count + span) rather
                // than full-array `==`: sentence ids restart at 0 each episode so an
                // id-only key could collide, but the time span reliably detects the
                // swap and never fires during same-episode playback — without the
                // O(n·words) deep compare the old `onChange(of: sentences)` ran.
                .onChange(of: PodcastTranscriptIdentity(sentences: sentences)) { _, _ in
                    sentenceCenters = [:]
                }

                if shouldShowFollowControl {
                    followPill()
                        .padding(.bottom, skin.spacing.sectionGap)
                        .transition(.readerPanelReveal)
                }
            }
            .animation(AppMotion.contentFade, value: isFollowing)
        }
        .enableInjection()
    }

    /// The transcript token tree, wrapped in `.equatable()` so the per-frame
    /// follow `TimelineView` above does not re-evaluate hundreds of sentences ×
    /// per-word tokens every display frame. See `PodcastTranscriptColumn`.
    /// `speakerSlots` is passed in (computed once in `body`) so reconstructing
    /// this value for the per-frame Equatable check stays O(1) work.
    private func transcriptColumn(speakerSlots: [String: Int]) -> some View {
        PodcastTranscriptColumn(
            sentences: sentences,
            renderState: renderState,
            currentId: currentId,
            selectionState: selectionState,
            subtitleSize: subtitleSize,
            wordFollowEnabled: wordFollowEnabled,
            isPlaying: isPlaying,
            duration: duration,
            liveAnchor: liveAnchor,
            speakerSlots: speakerSlots,
            skin: skin,
            onSentenceTap: onSentenceTap,
            onWordTap: onWordTap,
            onPhraseTap: { phrase, context in
                selectionState = nil
                onPhraseTap(phrase, context)
            },
            onExplainTap: { text, context in
                selectionState = nil
                onExplainTap(text, context)
            },
            onEnterSelection: { sel in
                seedManualOffsetFromFollow()
                isFollowing = false
                selectionState = sel
            },
            onClearSelection: { selectionState = nil }
        )
        .equatable()
    }

    /// Continuous content offset that keeps the spoken sentence at viewport
    /// center. Falls back to the last manual offset until centers are measured.
    private func followOffset(viewportHeight: CGFloat, now: TimeInterval) -> CGFloat {
        let t = PodcastPlaybackClock.projectedTime(anchor: liveAnchor.value, now: now, duration: duration)
        return PodcastScrollGeometry.centerOffset(
            time: t, sentences: sentences, centers: sentenceCenters, viewportHeight: viewportHeight
        ) ?? manualOffset
    }

    /// Snapshot the live follow offset into the manual offset so disengaging
    /// follow (drag / long-press select / Catalyst stop pill) never jumps.
    private func seedManualOffsetFromFollow() {
        let off = followOffset(viewportHeight: viewportHeight, now: Date().timeIntervalSinceReferenceDate)
        manualOffset = off
        dragStartOffset = off
    }

    private func browseDrag(viewportHeight: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 8)
            .onChanged { value in
                if isFollowing {
                    // First drag event: hand off from the live follow position,
                    // then disengage. Translation (~0 here) applied next event.
                    let off = followOffset(
                        viewportHeight: viewportHeight, now: Date().timeIntervalSinceReferenceDate
                    )
                    manualOffset = off
                    dragStartOffset = off
                    isFollowing = false
                } else {
                    manualOffset = clampOffset(
                        dragStartOffset + value.translation.height, viewportHeight: viewportHeight
                    )
                }
            }
            .onEnded { _ in dragStartOffset = manualOffset }
    }

    /// Clamp so the user can't drag the transcript into empty space beyond the
    /// first/last sentence (each still centerable).
    private func clampOffset(_ y: CGFloat, viewportHeight: CGFloat) -> CGFloat {
        guard let minC = sentenceCenters.values.min(),
              let maxC = sentenceCenters.values.max() else { return y }
        let maxOffset = viewportHeight / 2 - minC  // first sentence centered
        let minOffset = viewportHeight / 2 - maxC  // last sentence centered
        guard minOffset <= maxOffset else { return y }
        return min(maxOffset, max(minOffset, y))
    }

    // MARK: - Follow pill

    // Mac Catalyst 的滑鼠滾輪/觸控板捲動是 indirect scroll,不觸發 SwiftUI DragGesture
    // (平台限制,Apple 至今無 API),故無法像 iOS 那樣隱式偵測「使用者捲離當前句」。
    // 因此 Catalyst 上 pill 常駐為明確 toggle(跟隨中 ⇄ 追隨當前);iPhone/iPad 維持
    // 手指拖曳隱式脫離 follow 的既有體驗(pill 僅在已脫離時出現)。
    private var shouldShowFollowControl: Bool {
        guard selectionState == nil else { return false }
        #if targetEnvironment(macCatalyst)
        return true
        #else
        return !isFollowing
        #endif
    }

    @ViewBuilder
    private func followPill() -> some View {
        if isFollowing {
            // iPhone/iPad 在 following 時 shouldShowFollowControl 為 false,不會到這;
            // 僅 Catalyst 顯示此態,作為「停止跟隨、自由瀏覽」開關。
            pillCapsule {
                seedManualOffsetFromFollow()
                isFollowing = false
            } content: {
                Image(systemName: "pause.fill")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.secondaryText)
                Text(L10n.string("停止跟隨"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
            }
        } else {
            pillCapsule {
                // Re-engage follow: the offset container snaps back to the live
                // follow offset (animated by the body's isFollowing animation).
                withAnimation(AppMotion.standardSpring) {
                    isFollowing = true
                }
            } content: {
                if let speaker = renderState?.speaker {
                    let idx = hostNames.firstIndex(of: speaker)
                    Circle()
                        .fill(PodcastSpeakerTint.color(for: idx, skin: skin))
                        .frame(width: 6, height: 6)
                }
                Text(L10n.string("追隨當前"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
                Image(systemName: "arrow.down")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.secondaryText)
            }
        }
    }

    @ViewBuilder
    private func pillCapsule<Content: View>(
        action: @escaping () -> Void,
        @ViewBuilder content: () -> Content
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 6) { content() }
                .padding(.horizontal, 14)
                .padding(.vertical, AppSpacing.s2)
                .background(
                    Capsule()
                        .fill(skin.palette.cardBackground.opacity(0.96))
                        .overlay(Capsule().stroke(skin.palette.cardBorder, lineWidth: 1))
                )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Transcript column (Equatable, per-frame skipped)

/// The non-lazy column of every sentence, wrapped by the parent in `.equatable()`.
///
/// Non-lazy (not `LazyVStack`) is required because `.offset` does not move a
/// `LazyVStack`'s realization window — off-window cells would blank out. Each
/// bubble reports its center in the column's own coordinate space for the
/// continuous follow offset.
///
/// `Equatable` is the heart of the scroll-freeze fix: the parent's follow
/// `TimelineView` re-evaluates every display frame, but this struct's `==`
/// compares only the inputs that actually change the rendered tokens — an O(1)
/// `PodcastTranscriptIdentity` plus the sentence-level highlight / selection /
/// size / word-follow flags. The per-frame playhead is read LIVE from `liveAnchor`
/// (a reference, excluded from `==`), so frame ticks compare equal and SwiftUI
/// skips this whole `body`, reusing the already-built token tree. The word
/// underline's inner `TimelineView` still reads `liveAnchor.value` fresh each
/// frame, so it never freezes despite the parent skip.
private struct PodcastTranscriptColumn: View, Equatable {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let currentId: Int?
    let selectionState: PodcastSentenceSelection?
    let subtitleSize: PodcastSubtitleSize
    let wordFollowEnabled: Bool
    let isPlaying: Bool
    let duration: TimeInterval
    let liveAnchor: PodcastLiveAnchor
    let speakerSlots: [String: Int]
    let skin: AppSkin
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    let onEnterSelection: (PodcastSentenceSelection) -> Void
    let onClearSelection: () -> Void

    /// Named coordinate space for measuring sentence centers, independent of the
    /// outer `.offset` (which is a render transform, not a layout change).
    private static let transcriptSpace = "podcastTranscript"

    /// The body-skip contract: equal iff nothing that changes the TOKEN TREE
    /// changed. Compares O(1) transcript identity + sentence-level highlight /
    /// selection / size / word-follow + `isPlaying` (gates the underline's
    /// TimelineView pause). Deliberately excludes `liveAnchor` (read live per
    /// frame), `duration`, geometry, and the closures (stable per parent render),
    /// so the per-frame follow ticks short-circuit here.
    static func == (lhs: PodcastTranscriptColumn, rhs: PodcastTranscriptColumn) -> Bool {
        PodcastTranscriptIdentity(sentences: lhs.sentences) == PodcastTranscriptIdentity(sentences: rhs.sentences)
            && lhs.currentId == rhs.currentId
            && lhs.selectionState == rhs.selectionState
            && lhs.subtitleSize == rhs.subtitleSize
            && lhs.wordFollowEnabled == rhs.wordFollowEnabled
            && lhs.isPlaying == rhs.isPlaying
    }

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                bubbleRow(sentence, showSpeaker: sentence.speaker != prevSpeaker)
                    .id(sentence.id)
                    .background(
                        GeometryReader { g in
                            Color.clear.preference(
                                key: SentenceCenterKey.self,
                                value: [sentence.id: g.frame(in: .named(Self.transcriptSpace)).midY]
                            )
                        }
                    )
            }
        }
        .padding(.vertical, skin.spacing.sectionGap)
        .padding(.horizontal, skin.spacing.cardPadding)
        .coordinateSpace(name: Self.transcriptSpace)
    }

    // MARK: - Bubble row

    @ViewBuilder
    private func bubbleRow(_ sentence: PodcastSentence, showSpeaker: Bool) -> some View {
        let slot = speakerSlots[sentence.speaker] ?? 0
        let idx: Int? = slot
        // Odd slots align right, even align left — for 2-speaker podcasts that
        // matches host[0]=left / host[1]=right; 3+ speakers fan out cleanly.
        let alignRight = (slot % 2 == 1)
        let isCurrent = sentence.id == currentId
        let isSelecting = selectionState?.sentenceId == sentence.id
        HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: AppSpacing.tinyGap) {
                if showSpeaker {
                    Text(sentence.speaker)
                        .font(subtitleSize.speakerFont)
                        .foregroundStyle(tint(for: idx).opacity(isCurrent || isSelecting ? 0.88 : 0.58))
                        .transition(.overlayFade)
                }
                bubbleContent(sentence: sentence, idx: idx, isCurrent: isCurrent, isSelecting: isSelecting)
            }
            if !alignRight { Spacer(minLength: 48) }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if !isSelecting {
                handleSentenceTap(sentence, isCurrent: isCurrent)
            }
        }
    }

    @ViewBuilder
    private func bubbleContent(
        sentence: PodcastSentence,
        idx: Int?,
        isCurrent: Bool,
        isSelecting: Bool
    ) -> some View {
        let bubbleTint = tint(for: idx)
        // Every bubble carries the speaker's tint — non-current uses a very
        // light wash so the conversation reads as alternating speakers at a
        // glance (chat-bubble convention), while current pops with a richer
        // fill. Replaces the prior neutral mutedFill for non-current bubbles
        // which made every speaker look identical.
        let bg: Color = isCurrent || isSelecting
            ? bubbleTint.opacity(0.18)
            : bubbleTint.opacity(0.08)
        let fg: Color = isCurrent || isSelecting ? skin.palette.primaryText : skin.palette.secondaryText

        Group {
            if isSelecting {
                PodcastSelectableSentenceTextView(
                    text: sentence.text,
                    font: subtitleSize.uiSubtitleFont,
                    textColor: UIColor(fg),
                    tintColor: UIColor(bubbleTint),
                    initialSelectionRange: selectionState?.initialRange
                ) { phrase, context in
                    onPhraseTap(phrase, context)
                } onExplainSelection: { text, context in
                    onExplainTap(text, context)
                }
            } else {
                // All bubbles use CachedFlowLayout of per-word tokens — same layout
                // algorithm whether current or not. This guarantees line breaks don't
                // shift when a sentence becomes current (the prior design mixed a
                // single wrapping Text with an overlay FlowLayout whose wrapping
                // disagreed, producing visible misalignment + jank).
                wordFlow(for: sentence, isCurrent: isCurrent, textColor: fg, tint: bubbleTint)
            }
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, 10)
        .background(bg, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .stroke(
                    bubbleTint.opacity(isCurrent || isSelecting ? 0.22 : 0.08),
                    lineWidth: isCurrent || isSelecting ? 1 : 0.8
                )
        }
        .animation(AppMotion.contentFade, value: isCurrent)
        .animation(AppMotion.contentFade, value: isSelecting)
    }

    @ViewBuilder
    private func wordFlow(
        for sentence: PodcastSentence,
        isCurrent: Bool,
        textColor: Color,
        tint: Color
    ) -> some View {
        // When the sentence is current AND we have renderState for it, use the
        // per-cue words so the active-word underline and word-tap map 1:1 to
        // the audio. Otherwise derive stable tokens from sentence.text.
        if isCurrent, let rs = renderState, rs.sentenceId == sentence.id {
            CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
                ForEach(Array(rs.words.enumerated()), id: \.element.id) { index, word in
                    Text(word.text)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        // Report each word's frame so the single continuous
                        // underline can be positioned/sized against real geometry.
                        .anchorPreference(key: WordFrameKey.self, value: .bounds) { [index: $0] }
                        .onTapGesture {
                            onWordTap(word.text, rs.sentenceText)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            enterSelectionMode(for: sentence, wordIndex: index)
                        }
                }
            }
            // Single continuous capsule driven by the extrapolated playhead —
            // replaces the prior per-word overlay + `.animation(value:)` snap,
            // which strobed off on sub-130ms words. Gated by `wordFollowEnabled`
            // (false → bar(...) gets no chance to render).
            .overlayPreferenceValue(WordFrameKey.self) { anchors in
                continuousUnderline(anchors: anchors, words: sentence.words, tint: tint)
            }
        } else {
            CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
                // Use sentence.words (same source the current-branch uses) so
                // token count and line-wrapping stay identical when the sentence
                // becomes current — avoids any jump in bubble height.
                ForEach(Array(sentence.words.enumerated()), id: \.offset) { index, cue in
                    Text(cue.word)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        .onTapGesture {
                            onWordTap(cue.word, sentence.text)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            enterSelectionMode(for: sentence, wordIndex: index)
                        }
                }
            }
        }
    }

    /// The single continuous underline. `rects` are resolved once per layout
    /// pass (from anchor preferences); the inner `TimelineView` re-evaluates at
    /// the display refresh rate and only lerps the capsule — it does NOT rebuild
    /// the word tokens, so `CachedFlowLayout` never re-runs per frame.
    ///
    /// The playhead is read LIVE from `liveAnchor.value` inside the TimelineView
    /// closure. This is what defeats the stale-anchor trap: even though the parent
    /// `PodcastTranscriptColumn.body` is skipped per frame (Equatable), this inner
    /// TimelineView runs its own per-frame schedule and reads the current anchor
    /// through the reference — never a value frozen at the last body eval.
    ///
    /// `words` MUST be the current sentence's cues (sentence-relative indices),
    /// matching `PodcastWordProgress.locate`'s array basis.
    @ViewBuilder
    private func continuousUnderline(
        anchors: [Int: Anchor<CGRect>],
        words: [PodcastSubtitleCue],
        tint: Color
    ) -> some View {
        GeometryReader { geo in
            let rects = anchors.mapValues { geo[$0] }
            TimelineView(.animation(paused: !isPlaying)) { ctx in
                let t = PodcastPlaybackClock.projectedTime(
                    anchor: liveAnchor.value,
                    now: ctx.date.timeIntervalSinceReferenceDate,
                    duration: duration
                )
                let loc = PodcastWordProgress.locate(time: t, words: words)
                if wordFollowEnabled,
                   let bar = PodcastUnderlineGeometry.bar(
                       wordRects: rects, activeIndex: loc.index, fraction: loc.fraction
                   ) {
                    Capsule()
                        .fill(tint)
                        .frame(width: bar.width, height: 3)
                        // bottomY (word bottom) + 3pt offset + half the 3pt height.
                        .position(x: bar.minX + bar.width / 2, y: bar.bottomY + 4.5)
                }
            }
        }
    }

    // MARK: - Helpers

    private func tint(for idx: Int?) -> Color {
        PodcastSpeakerTint.color(for: idx, skin: skin)
    }

    private func handleSentenceTap(_ sentence: PodcastSentence, isCurrent: Bool) {
        if selectionState != nil {
            onClearSelection()
            return
        }
        if !isCurrent { onSentenceTap(sentence) }
    }

    private func enterSelectionMode(for sentence: PodcastSentence, wordIndex: Int) {
        onEnterSelection(
            PodcastSentenceSelection(
                sentenceId: sentence.id,
                initialRange: selectionRange(for: sentence, wordIndex: wordIndex)
            )
        )
    }

    private func selectionRange(for sentence: PodcastSentence, wordIndex: Int) -> NSRange? {
        let nsText = sentence.text as NSString
        var searchStart = 0

        for (index, cue) in sentence.words.enumerated() {
            let searchRange = NSRange(
                location: searchStart,
                length: max(0, nsText.length - searchStart)
            )
            let foundRange = nsText.range(of: cue.word, options: [], range: searchRange)
            guard foundRange.location != NSNotFound else { continue }
            if index == wordIndex { return foundRange }
            searchStart = foundRange.location + foundRange.length
        }

        return nil
    }
}

/// Speaker → tint mapping. Hoisted out of the view so both the transcript column
/// and the follow pill share one source of truth.
enum PodcastSpeakerTint {
    static func color(for idx: Int?, skin: AppSkin) -> Color {
        switch idx {
        case 0: return skin.palette.accent
        case 1: return skin.palette.success
        case 2: return skin.palette.warning
        case 3: return skin.palette.info
        default: return skin.palette.tertiaryText
        }
    }
}

/// Collects each word's frame (as a resolvable `Anchor<CGRect>`) keyed by its
/// index within the current sentence, so the continuous underline overlay can
/// position itself against real word geometry without re-running the layout.
private struct WordFrameKey: PreferenceKey {
    static let defaultValue: [Int: Anchor<CGRect>] = [:]
    static func reduce(value: inout [Int: Anchor<CGRect>], nextValue: () -> [Int: Anchor<CGRect>]) {
        value.merge(nextValue()) { _, new in new }
    }
}

/// Collects each sentence's vertical center (in the transcript column's own
/// coordinate space) keyed by sentence id, for the offset-driven follow scroll.
private struct SentenceCenterKey: PreferenceKey {
    static let defaultValue: [Int: CGFloat] = [:]
    static func reduce(value: inout [Int: CGFloat], nextValue: () -> [Int: CGFloat]) {
        value.merge(nextValue()) { _, new in new }
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
            onSentenceTap: { _ in },
            onWordTap: { _, _ in },
            onPhraseTap: { _, _ in },
            onExplainTap: { _, _ in }
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
