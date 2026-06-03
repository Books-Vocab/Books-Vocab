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
/// ## Scroll engine (the scroll-freeze fix)
///
/// HISTORY: an earlier offset-driven engine drove follow with an outer
/// `TimelineView(.animation)` that recomputed a manual `.offset` over a NON-lazy
/// column EVERY display frame. That re-evaluated the whole token tree (hundreds of
/// sentences × per-word `Text` + `CachedFlowLayout` + per-sentence `GeometryReader`
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
            .onChange(of: currentId) { old, id in
                #if DEBUG
                logBoundary(from: old, to: id)
                #endif
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
    /// duration is what makes the move read as a continuous glide rather than a
    /// jump; tuned for feel (`AppMotion.podcastFollowScroll`).
    private func followScroll(to id: Int?, proxy: ScrollViewProxy) {
        guard isFollowing, let id else { return }
        PerfLog.scroll.measure("scrollTo", "id=\(id)") {
            withAnimation(AppMotion.podcastFollowScroll) {
                proxy.scrollTo(id, anchor: .center)
            }
        }
    }

    #if DEBUG
    /// Boundary tracer for the cross-sentence underline-handoff design (Option B).
    /// Emits ONE line per `currentId` flip so we can validate the timing model the
    /// edge-relay depends on, straight from real-episode SRT data:
    ///   • `gap = mStart - nEnd` — are sentences contiguous (≈0) or is there real
    ///     silence between them? (compact SRT *should* stitch end=next.start, but
    ///     the engine admits rounding/silence gaps — this measures the truth).
    ///   • `nEnd == lastW.e` and `mStart == firstW.s` — confirms a sentence's span
    ///     IS its first/last word's span (so the relay can key off word times).
    ///   • `projT` vs `mStart` — how late the flip fires after the playhead crosses
    ///     the boundary (one tick ≈ 0.066 s budget).
    /// One-shot per flip → cheap; `mark` lazily builds the detail only when enabled.
    private func logBoundary(from oldId: Int?, to newId: Int?) {
        func f(_ v: TimeInterval) -> String { String(format: "%.3f", v) }
        let projT = PodcastPlaybackClock.projectedTime(
            anchor: liveAnchor.value,
            now: Date().timeIntervalSinceReferenceDate,
            duration: duration
        )
        guard let newId, let to = sentences.first(where: { $0.id == newId }) else {
            PerfLog.underline.mark("boundary", "clear from=\(oldId.map(String.init) ?? "nil") projT=\(f(projT))")
            return
        }
        guard let oldId, let from = sentences.first(where: { $0.id == oldId }),
              let lw = from.words.last, let fw = to.words.first else {
            PerfLog.underline.mark("boundary", "init to=\(newId) mStart=\(f(to.startTime)) projT=\(f(projT))")
            return
        }
        let gap = to.startTime - from.endTime
        PerfLog.underline.mark(
            "boundary",
            "\(oldId)->\(newId) projT=\(f(projT)) nEnd=\(f(from.endTime)) mStart=\(f(to.startTime)) "
                + "gap=\(f(gap)) lastW=\(f(lw.startTime))..\(f(lw.endTime)) firstW=\(f(fw.startTime))..\(f(fw.endTime))"
        )
    }
    #endif

    /// The transcript column. NOT wrapped in `.equatable()` at the column level:
    /// each row is a `PodcastBubbleCell` wrapped in its OWN `.equatable()`, so a
    /// sentence advance re-bodies only the ~2 cells whose `isCurrent` changed
    /// instead of the whole column. `speakerSlots` is passed in (computed once in
    /// `body`).
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

// MARK: - Transcript column

/// The transcript column, hosted in a native `ScrollView` + `LazyVStack` so only
/// on-screen bubbles are realized. The column body is CHEAP — it builds one
/// `PodcastBubbleCell` value struct per realized row; each is wrapped in
/// `.equatable()`, so when `currentId` changes SwiftUI re-bodies only the cells
/// whose Equatable inputs actually changed (the leaving + gaining cell, ~2),
/// short-circuiting all the others — they never re-measure their `CachedFlowLayout`.
///
/// The column itself is intentionally NOT `Equatable`: a column-level wrapper
/// whose `==` included `currentId` returned false on every advance and forced the
/// whole column body to rebuild all realized rows (the measured per-advance hitch).
/// Dropping it and gating at per-cell granularity is the fix. The column body re-
/// runs on parent renders, but that is cheap now (only value structs are built;
/// the token trees live behind the per-cell Equatable boundary).
private struct PodcastTranscriptColumn: View {
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

    var body: some View {
        PerfLog.render.mark("column.body", "id=\(currentId ?? -1) n=\(sentences.count)")
        let hasActiveSelection = selectionState != nil
        return LazyVStack(spacing: skin.spacing.inlineGap) {
            ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                let slot = speakerSlots[sentence.speaker] ?? 0
                let isSelectingThis = selectionState?.sentenceId == sentence.id
                let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                // Cross-sentence relay wiring: the cell after `currentId` is the
                // entering bubble; its handoff window opens at its predecessor's
                // last word (gap-free SRT). `hasNext` lets the leaving cell slide
                // off rather than hold on the final sentence.
                let isNext = currentId.map { sentence.id == $0 + 1 } ?? false
                let hasNext = index < sentences.count - 1
                let entryFromTime = index > 0 ? sentences[index - 1].words.last?.startTime : nil
                PodcastBubbleCell(
                    sentenceId: sentence.id,
                    contentHash: sentence.startTime.hashValue ^ sentence.endTime.hashValue ^ sentence.words.count,
                    isCurrent: sentence.id == currentId,
                    isNext: isNext,
                    isSelecting: isSelectingThis,
                    initialSelectionRange: isSelectingThis ? selectionState?.initialRange : nil,
                    hasActiveSelection: hasActiveSelection,
                    subtitleSize: subtitleSize,
                    wordFollowEnabled: wordFollowEnabled,
                    isPlaying: isPlaying,
                    alignRight: slot % 2 == 1,
                    showSpeaker: sentence.speaker != prevSpeaker,
                    speaker: sentence.speaker,
                    words: sentence.words,
                    fullText: sentence.text,
                    skin: PodcastBubbleSkin(skin: skin, slot: slot),
                    liveAnchor: liveAnchor,
                    duration: duration,
                    hasNext: hasNext,
                    entryFromTime: entryFromTime,
                    onSentenceTap: {
                        if hasActiveSelection {
                            onClearSelection()
                        } else if sentence.id != currentId {
                            onSentenceTap(sentence)
                        }
                    },
                    onWordTap: onWordTap,
                    onPhraseTap: onPhraseTap,
                    onExplainTap: onExplainTap,
                    onEnterSelection: { wordIndex in
                        onEnterSelection(
                            PodcastSentenceSelection(
                                sentenceId: sentence.id,
                                initialRange: selectionRange(for: sentence, wordIndex: wordIndex)
                            )
                        )
                    },
                    onClearSelection: onClearSelection
                )
                .equatable()
                .id(sentence.id)
            }
        }
        .padding(.vertical, skin.spacing.sectionGap)
        .padding(.horizontal, skin.spacing.cardPadding)
    }

    /// Maps a word index to its `NSRange` within the sentence text, to seed the
    /// selectable text view's initial selection. Kept on the column (not the cell)
    /// so the cell stays a pure value — the cell calls back with just the word index.
    private func selectionRange(for sentence: PodcastSentence, wordIndex: Int) -> NSRange? {
        let nsText = sentence.text as NSString
        var searchStart = 0
        for (index, cue) in sentence.words.enumerated() {
            let searchRange = NSRange(location: searchStart, length: max(0, nsText.length - searchStart))
            let foundRange = nsText.range(of: cue.word, options: [], range: searchRange)
            guard foundRange.location != NSNotFound else { continue }
            if index == wordIndex { return foundRange }
            searchStart = foundRange.location + foundRange.length
        }
        return nil
    }
}

// MARK: - Bubble cell (Equatable)

/// Cheap Equatable skin token for a bubble. Compared ONLY by `paletteBase`
/// (`AppTheme.Palette`, the single source of truth every color derives from — so a
/// theme/colorScheme change flips it) + `slot` (the speaker tint depends on it).
/// The resolved colors/metrics are CARRIED for the body but NOT compared: with the
/// same `paletteBase` + `slot` they are deterministically identical, so comparing
/// them (Color `==` is unreliable) would be both wrong and wasteful.
private struct PodcastBubbleSkin: Equatable {
    let paletteBase: AppTheme.Palette
    let slot: Int
    // Carried, not compared:
    let tint: Color
    let primaryText: Color
    let secondaryText: Color
    let cornerRadius: CGFloat
    let wordRowGap: CGFloat

    init(skin: AppSkin, slot: Int) {
        self.paletteBase = skin.palette.base
        self.slot = slot
        self.tint = PodcastSpeakerTint.color(for: slot, skin: skin)
        self.primaryText = skin.palette.primaryText
        self.secondaryText = skin.palette.secondaryText
        self.cornerRadius = skin.radii.card
        self.wordRowGap = skin.spacing.wordRowVerticalGap
    }

    static func == (l: PodcastBubbleSkin, r: PodcastBubbleSkin) -> Bool {
        l.paletteBase == r.paletteBase && l.slot == r.slot
    }
}

/// One transcript bubble as an `Equatable` value view. Wrapped in `.equatable()`
/// inside the column's `ForEach`, so SwiftUI skips its `body` whenever its inputs
/// are unchanged — a sentence advance flips `isCurrent` on only the leaving +
/// gaining cells, so only those ~2 re-body (the rest short-circuit and never
/// re-measure their `CachedFlowLayout`). This is what makes a sentence change
/// O(2 rows) instead of O(all realized rows).
///
/// EXCLUDED from `==`: `liveAnchor` (a reference, read live per frame by the
/// underline's own `TimelineView`), `duration`, and all closures (stable per
/// parent render). `words` / `fullText` / `speaker` are excluded too — they are
/// fully determined by `sentenceId` + `contentHash`, so comparing the scalar keys
/// is enough and avoids an O(n·words) array compare.
private struct PodcastBubbleCell: View, Equatable {
    let sentenceId: Int
    let contentHash: Int
    let isCurrent: Bool
    /// The sentence immediately after `currentId`. Cross-sentence underline relay
    /// (Option B) needs the entering bubble's underline machinery present BEFORE the
    /// `currentId` flip (which lags audio ~one tick / ~55 ms, device-measured), so
    /// the entering head can already be sliding in. Compared in `==` so the cell
    /// gains/loses its machinery as it enters/leaves the "next" slot.
    let isNext: Bool
    let isSelecting: Bool
    let initialSelectionRange: NSRange?
    let hasActiveSelection: Bool
    let subtitleSize: PodcastSubtitleSize
    let wordFollowEnabled: Bool
    let isPlaying: Bool
    let alignRight: Bool
    let showSpeaker: Bool
    let speaker: String
    let words: [PodcastSubtitleCue]
    let fullText: String
    let skin: PodcastBubbleSkin
    // Per-frame channel + stable closures — EXCLUDED from == (determined by
    // `sentenceId` or read live per frame):
    let liveAnchor: PodcastLiveAnchor
    let duration: TimeInterval
    /// Is there a successor sentence (so the leaving handoff should slide off the
    /// edge rather than hold). Determined by `sentenceId` → not compared.
    let hasNext: Bool
    /// Start time of THIS sentence's predecessor's last word — the instant the
    /// entering relay window opens. It equals my `startTime` minus that last word's
    /// duration (gap-free SRT ⇒ predecessor's last-word END == my first-word START),
    /// which is exactly why the leaving tail's fraction and this head's fraction
    /// stay in lock-step. nil for the first sentence. Determined by `sentenceId` →
    /// not compared.
    let entryFromTime: TimeInterval?
    let onSentenceTap: () -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    let onExplainTap: (String, String) -> Void
    let onEnterSelection: (Int) -> Void
    let onClearSelection: () -> Void

    static func == (l: PodcastBubbleCell, r: PodcastBubbleCell) -> Bool {
        l.sentenceId == r.sentenceId
            && l.contentHash == r.contentHash
            && l.isCurrent == r.isCurrent
            && l.isNext == r.isNext
            && l.isSelecting == r.isSelecting
            && l.initialSelectionRange == r.initialSelectionRange
            && l.hasActiveSelection == r.hasActiveSelection
            && l.subtitleSize == r.subtitleSize
            && l.wordFollowEnabled == r.wordFollowEnabled
            && l.isPlaying == r.isPlaying
            && l.alignRight == r.alignRight
            && l.showSpeaker == r.showSpeaker
            && l.skin == r.skin
    }

    var body: some View {
        let _ = PerfLog.render.tick("cell.body", isCurrent ? "cur" : "non")
        return HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: AppSpacing.tinyGap) {
                if showSpeaker {
                    Text(speaker)
                        .font(subtitleSize.speakerFont)
                        .foregroundStyle(skin.tint.opacity(isCurrent || isSelecting ? 0.88 : 0.58))
                        .transition(.overlayFade)
                }
                bubbleContent
            }
            if !alignRight { Spacer(minLength: 48) }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if !isSelecting { onSentenceTap() }
        }
    }

    @ViewBuilder
    private var bubbleContent: some View {
        let active = isCurrent || isSelecting
        let bg: Color = active ? skin.tint.opacity(0.18) : skin.tint.opacity(0.08)
        let fg: Color = active ? skin.primaryText : skin.secondaryText
        Group {
            if isSelecting {
                PodcastSelectableSentenceTextView(
                    text: fullText,
                    font: subtitleSize.uiSubtitleFont,
                    textColor: UIColor(fg),
                    tintColor: UIColor(skin.tint),
                    initialSelectionRange: initialSelectionRange
                ) { phrase, context in
                    onPhraseTap(phrase, context)
                } onExplainSelection: { text, context in
                    onExplainTap(text, context)
                }
            } else {
                // All bubbles use CachedFlowLayout of per-word tokens — same layout
                // algorithm whether current or not, so line breaks don't shift when
                // a sentence becomes current.
                wordFlow(textColor: fg)
            }
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, 10)
        // Bubble fill + border live in their OWN shape-only layer so the active↔
        // inactive skin crossfade animates on `active` WITHOUT animating the
        // structural `wordFlow` swap (plain Text ↔ anchorPreference +
        // overlayPreferenceValue + GeometryReader + TimelineView) that lives in the
        // content layer above. Animating that swap spins up BOTH subtrees in one
        // transaction → the per-sentence-change hitch — so the swap MUST stay
        // instant. Scoping `.animation(value: active)` to this token-free shape
        // layer gives the smooth bg/border glide the user asked for while keeping
        // the structural swap snap-instant. (Earlier this whole block was left
        // un-animated to dodge the hitch, which made the bubble color hard-cut.)
        .background {
            RoundedRectangle(cornerRadius: skin.cornerRadius, style: .continuous)
                .fill(bg)
                .overlay {
                    RoundedRectangle(cornerRadius: skin.cornerRadius, style: .continuous)
                        .stroke(
                            skin.tint.opacity(active ? 0.22 : 0.08),
                            lineWidth: active ? 1 : 0.8
                        )
                }
                .animation(AppMotion.contentFade, value: active)
        }
        .animation(AppMotion.contentFade, value: isSelecting)
    }

    @ViewBuilder
    private func wordFlow(textColor: Color) -> some View {
        // Underline machinery (anchorPreference + overlayPreferenceValue +
        // GeometryReader + TimelineView) lives on the current cell AND the next one
        // (`isCurrent || isNext`); all other cells are a plain Text flow. The "next"
        // cell needs it BEFORE the `currentId` flip so the cross-sentence entering
        // head can already slide in during the boundary window (the flip lags audio
        // ~one tick). Gating by STRUCTURE (not `paused`) is what bounds the cost to
        // 2 cells — `TimelineView(paused:)` does NOT stop content re-eval. Token
        // content is identical either way (same `words`), so wrapping / bubble
        // height never shift across the (instant, never-animated) swap.
        if isCurrent || isNext {
            CachedFlowLayout(spacing: skin.wordRowGap) {
                ForEach(Array(words.enumerated()), id: \.offset) { index, cue in
                    Text(cue.word)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        // Report each word's frame so the underline can be
                        // positioned/sized against real geometry.
                        .anchorPreference(key: WordFrameKey.self, value: .bounds) { [index: $0] }
                        .onTapGesture { onWordTap(cue.word, fullText) }
                        .onLongPressGesture(minimumDuration: 0.35) { onEnterSelection(index) }
                }
            }
            .overlayPreferenceValue(WordFrameKey.self) { anchors in
                continuousUnderline(anchors)
            }
        } else {
            CachedFlowLayout(spacing: skin.wordRowGap) {
                ForEach(Array(words.enumerated()), id: \.offset) { index, cue in
                    Text(cue.word)
                        .font(subtitleSize.subtitleFont)
                        .foregroundStyle(textColor)
                        .onTapGesture { onWordTap(cue.word, fullText) }
                        .onLongPressGesture(minimumDuration: 0.35) { onEnterSelection(index) }
                }
            }
        }
    }

    /// Continuous word underline for the CURRENT cell only. Resolves word rects
    /// from the anchor preferences once per layout pass; the inner `TimelineView`
    /// re-evaluates per display frame and reads the LIVE playhead via
    /// `liveAnchor.value` (the reference defeats the stale-anchor trap). Across a
    /// line break it renders a portal (two capsules) — see
    /// `PodcastUnderlineGeometry.segments`.
    private func continuousUnderline(_ anchors: [Int: Anchor<CGRect>]) -> some View {
        GeometryReader { geo in
            let rects = anchors.mapValues { geo[$0] }
            TimelineView(.animation(paused: !isPlaying)) { ctx in
                // Current cell logs `ul.frame`; the entering ("next") cell logs
                // `ul.next` so the second per-frame engine is separable in the trace.
                let _ = PerfLog.underline.tick(isCurrent ? "ul.frame" : "ul.next")
                if wordFollowEnabled {
                    let t = PodcastPlaybackClock.projectedTime(
                        anchor: liveAnchor.value,
                        now: ctx.date.timeIntervalSinceReferenceDate,
                        duration: duration
                    )
                    // Geometry recomputed per frame → motion is continuous with NO
                    // animation modifier (a spring chasing a moving target visually
                    // skips words). `relayBars` picks the regime: intra-sentence
                    // portal, leaving tail-exit, or entering head-enter.
                    let bars = relayBars(t: t, rects: rects)
                    ForEach(Array(bars.enumerated()), id: \.offset) { _, bar in
                        Capsule()
                            .fill(skin.tint)
                            .frame(width: bar.width, height: 3)
                            // bottomY (word bottom) + 3pt offset + half the 3pt height.
                            .position(x: bar.minX + bar.width / 2, y: bar.bottomY + 4.5)
                    }
                }
            }
        }
    }

    /// Picks this cell's underline bars for playhead `t`. Three regimes:
    ///   • CURRENT, mid-sentence → the gliding portal (`segments`, incl. the
    ///     line-break two-capsule handoff).
    ///   • CURRENT, on the last word, with a successor → leaving relay: slide the
    ///     bar off the trailing edge (`tailExit`). Once `fraction` hits 1 (the
    ///     ~55 ms pre-flip window) it has vanished → nothing.
    ///   • NEXT (machinery present, not yet current) → entering relay: before my
    ///     first word, grow the head in from my leading edge (`headEnter`) over the
    ///     predecessor's last-word window; once my first word actually plays (the
    ///     pre-flip seam) draw it normally so becoming current is seamless. Outside
    ///     that window the head is absent (zero/negative fraction → nil).
    private func relayBars(
        t: TimeInterval, rects: [Int: CGRect]
    ) -> [PodcastUnderlineGeometry.Bar] {
        let loc = PodcastWordProgress.locate(time: t, words: words)
        if isCurrent {
            let lastIndex = words.count - 1
            if hasNext, lastIndex >= 0, loc.index == lastIndex, let lw = rects[lastIndex] {
                // Exit toward the RIGHT EDGE OF THE LAST WORD'S OWN ROW, not the
                // bubble's full content width: a short last row ("it.", "cleverness.")
                // is far narrower than the widest row, so using content width slides
                // the bar off into the empty space beside the text (a detached
                // floating underline). With the row edge, when the last word is the
                // rightmost on its row (the usual case) the bar retracts rightward to
                // nothing while staying under the text.
                let rowRight = rects.values
                    .filter { abs($0.minY - lw.minY) < lw.height * 0.5 }
                    .map(\.maxX).max() ?? lw.maxX
                return PodcastUnderlineGeometry.tailExit(
                    lastWord: lw, rowRightEdge: rowRight, fraction: loc.fraction
                ).map { [$0] } ?? []
            }
            return PodcastUnderlineGeometry.segments(
                wordRects: rects, activeIndex: loc.index, fraction: loc.fraction
            )
        }
        // isNext: machinery present ahead of the flip so the entering head can lead.
        guard let fw = rects[0], let first = words.first else { return [] }
        if let entry = entryFromTime, t < first.startTime {
            let f = (t - entry) / max(0.0001, first.startTime - entry)
            return PodcastUnderlineGeometry.headEnter(
                firstWord: fw, rowLeftEdge: fw.minX, fraction: f
            ).map { [$0] } ?? []
        }
        // Pre-flip seam: my own words are genuinely playing (not the playhead
        // seeked far past me). The upper bound stops a non-sequential seek from
        // flashing a stale bar on this still-"next" cell in the ~1 tick before
        // `currentId` catches up.
        if t >= first.startTime, t <= (words.last?.endTime ?? first.startTime) {
            return PodcastUnderlineGeometry.segments(
                wordRects: rects, activeIndex: loc.index, fraction: loc.fraction
            )
        }
        return []
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
