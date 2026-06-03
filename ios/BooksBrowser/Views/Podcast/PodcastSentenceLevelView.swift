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
        // Computed ONCE per render (not per frame). The transcript token tree is
        // built lazily by a native `ScrollView` + `LazyVStack`; follow is a
        // discrete animated `scrollTo` per sentence, NOT a per-frame offset. This
        // replaces the offset-driven engine whose outer per-frame `TimelineView`
        // re-evaluated the whole non-lazy column every display frame (the
        // scroll-freeze root cause). Native scroll is GPU-composited and off the
        // SwiftUI per-frame eval path.
        let slots = speakerSlots
        return ScrollViewReader { proxy in
            ScrollView {
                transcriptColumn(speakerSlots: slots)
            }
            .scrollIndicators(.hidden)
            .overlay(alignment: .bottom) {
                if shouldShowFollowControl {
                    followPill()
                        .padding(.bottom, skin.spacing.sectionGap)
                        .transition(.readerPanelReveal)
                }
            }
            // Auto-follow: glide the spoken sentence to viewport center as the
            // playhead advances. One animated scroll per sentence boundary; the
            // animation duration gives the continuous gliding feel without any
            // per-frame main-thread work.
            .onChange(of: currentId) { _, id in
                followScroll(to: id, proxy: proxy)
            }
            // Re-engage follow (pill / Catalyst toggle): snap back to the current
            // sentence the moment the user opts back in.
            .onChange(of: isFollowing) { _, following in
                guard following else { return }
                followScroll(to: currentId, proxy: proxy)
            }
            // In-place episode swap: the player reuses this view instance and
            // replaces `sentences` without recreating it. Re-center on the new
            // episode's current sentence.
            .onChange(of: PodcastTranscriptIdentity(sentences: sentences)) { _, _ in
                followScroll(to: currentId, proxy: proxy)
            }
            // Initial placement: `onChange` does not fire for the value present at
            // mount. `onAppear`'s `scrollTo` can no-op because the `LazyVStack`
            // hasn't realized/laid out the target row yet, so defer one runloop
            // turn via `.task` before centering (no animation on first placement).
            .task {
                await Task.yield()
                if let id = currentId { proxy.scrollTo(id, anchor: .center) }
            }
            // Manual browse: any user drag disengages follow (the native scroll
            // itself still handles the movement — this gesture only flips the
            // flag, it does not consume the drag). Catalyst indirect scroll does
            // NOT trigger DragGesture, so that platform uses the always-on pill.
            .simultaneousGesture(
                DragGesture(minimumDistance: 8).onChanged { _ in
                    if isFollowing { isFollowing = false }
                }
            )
            .animation(AppMotion.contentFade, value: isFollowing)
        }
        .enableInjection()
    }

    /// Animated scroll that centers `id`, gated on follow being active. The
    /// `easeInOut` duration is what makes the move read as a continuous glide
    /// rather than a jump; tuned for feel (see Phase 2).
    private func followScroll(to id: Int?, proxy: ScrollViewProxy) {
        guard isFollowing, let id else { return }
        withAnimation(AppMotion.podcastFollowScroll) {
            proxy.scrollTo(id, anchor: .center)
        }
    }

    /// The transcript token tree, wrapped in `.equatable()` so token-irrelevant
    /// parent renders (e.g. follow-state flips) don't re-evaluate hundreds of
    /// sentences × per-word tokens. See `PodcastTranscriptColumn`. `speakerSlots`
    /// is passed in (computed once in `body`) so reconstructing this value for the
    /// Equatable check stays O(1) work.
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
                isFollowing = false
                selectionState = sel
            },
            onClearSelection: { selectionState = nil }
        )
        .equatable()
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
                // Re-engage follow: flipping the flag triggers `.onChange(of:
                // isFollowing)` → `followScroll`, which animates the scroll back to
                // the current sentence. The spring here drives the pill transition.
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

// MARK: - Transcript column (Equatable)

/// The transcript column, hosted in a native `ScrollView` + `LazyVStack` so only
/// on-screen bubbles are realized. Wrapped by the parent in `.equatable()`.
///
/// `Equatable` keeps the column's `body` from re-evaluating on parent renders
/// that don't change the token tree (e.g. follow-state flips): the `==` compares
/// only an O(1) `PodcastTranscriptIdentity` plus the sentence-level highlight /
/// selection / size / word-follow flags. The live playhead is read from
/// `liveAnchor` (a reference, excluded from `==`) inside the word underline's own
/// `TimelineView`, so the underline animates per frame without re-running the
/// token tree.
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

    /// The body-skip contract: equal iff nothing that changes the TOKEN TREE
    /// changed. Compares O(1) transcript identity + sentence-level highlight /
    /// selection / size / word-follow + `isPlaying` (gates the underline's
    /// TimelineView pause). Deliberately excludes `liveAnchor` (read live per
    /// frame by the underline), `duration`, and the closures (stable per parent
    /// render), so token-irrelevant parent renders short-circuit here.
    static func == (lhs: PodcastTranscriptColumn, rhs: PodcastTranscriptColumn) -> Bool {
        PodcastTranscriptIdentity(sentences: lhs.sentences) == PodcastTranscriptIdentity(sentences: rhs.sentences)
            && lhs.currentId == rhs.currentId
            && lhs.selectionState == rhs.selectionState
            && lhs.subtitleSize == rhs.subtitleSize
            && lhs.wordFollowEnabled == rhs.wordFollowEnabled
            && lhs.isPlaying == rhs.isPlaying
    }

    var body: some View {
        LazyVStack(spacing: skin.spacing.inlineGap) {
            ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                bubbleRow(sentence, showSpeaker: sentence.speaker != prevSpeaker)
                    .id(sentence.id)
            }
        }
        .padding(.vertical, skin.spacing.sectionGap)
        .padding(.horizontal, skin.spacing.cardPadding)
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
