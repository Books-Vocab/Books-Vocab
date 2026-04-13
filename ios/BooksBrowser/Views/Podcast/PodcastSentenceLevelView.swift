import SwiftUI

/// Chat-style transcript: sentences laid out as left/right bubbles by speaker.
///
/// Design principles:
///   • flat — no shadow, no scale lift, no blur
///   • follow-by-default: auto-scrolls with the current sentence; user drag
///     disables follow and surfaces a "追隨當前" pill that, when tapped,
///     re-enables follow and scrolls back to center.
///   • alignment distinguishes speakers (host[0] → left, host[1] → right);
///     the speaker label is shown only when it changes from the previous row.
///   • layout transitions are explicitly animated (bubble bg, underline,
///     label show/hide) to avoid the snap-change jank of dt→0 shifts.
struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let highlightedWordIndex: Int
    let hostNames: [String]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    let onPhraseTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    @State private var isFollowing = true
    @State private var didInitialScroll = false

    private var currentId: Int? { renderState?.sentenceId }

    var body: some View {
        ScrollViewReader { proxy in
            ZStack(alignment: .bottom) {
                ScrollView {
                    LazyVStack(spacing: skin.spacing.inlineGap) {
                        ForEach(Array(sentences.enumerated()), id: \.element.id) { index, sentence in
                            let prevSpeaker = index > 0 ? sentences[index - 1].speaker : nil
                            let showSpeaker = sentence.speaker != prevSpeaker
                            bubbleRow(sentence, showSpeaker: showSpeaker)
                                .id(sentence.id)
                        }
                    }
                    .padding(.vertical, skin.spacing.sectionGap)
                    .padding(.horizontal, skin.spacing.cardPadding)
                }
                // User drag disables follow mode. `minimumDistance: 24` avoids
                // cancelling follow on a finger-tremor tap (10pt contact +
                // small slide during release). Genuine scroll easily clears it.
                .simultaneousGesture(
                    DragGesture(minimumDistance: 24)
                        .onChanged { _ in
                            if isFollowing { isFollowing = false }
                        }
                )

                if !isFollowing {
                    followPill {
                        isFollowing = true
                        if let id = currentId {
                            withAnimation(AppMotion.standardSpring) {
                                proxy.scrollTo(id, anchor: .center)
                            }
                        }
                    }
                    .padding(.bottom, skin.spacing.sectionGap)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .onAppear {
                // If currentId is already known at appear, do the one-shot scroll.
                // Otherwise the .onChange below will handle it when the first
                // sentence resolves after restoreProgress / first time-tick.
                if !didInitialScroll, let id = currentId {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        proxy.scrollTo(id, anchor: .center)
                        didInitialScroll = true
                    }
                }
            }
            .onChange(of: currentId) { _, newId in
                guard let newId else { return }
                // First non-nil currentId → one-shot initial scroll without animation
                // so restored positions appear immediately.
                if !didInitialScroll {
                    proxy.scrollTo(newId, anchor: .center)
                    didInitialScroll = true
                    return
                }
                // Auto-follow: smoothly recenter when the sentence advances.
                guard isFollowing else { return }
                withAnimation(AppMotion.standardSpring) {
                    proxy.scrollTo(newId, anchor: .center)
                }
            }
            .animation(AppMotion.contentFade, value: isFollowing)
        }
    }

    // MARK: - Bubble row

    @ViewBuilder
    private func bubbleRow(_ sentence: PodcastSentence, showSpeaker: Bool) -> some View {
        let idx = hostNames.firstIndex(of: sentence.speaker)
        let alignRight = (idx == 1)
        let isCurrent = sentence.id == currentId
        HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: 3) {
                if showSpeaker {
                    Text(sentence.speaker)
                        .font(skin.typography.monoLabel)
                        .foregroundStyle(tint(for: idx).opacity(isCurrent ? 0.85 : 0.45))
                        .transition(.opacity)
                }
                bubbleContent(sentence: sentence, idx: idx, isCurrent: isCurrent)
            }
            if !alignRight { Spacer(minLength: 48) }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if !isCurrent { onSentenceTap(sentence) }
        }
    }

    @ViewBuilder
    private func bubbleContent(
        sentence: PodcastSentence,
        idx: Int?,
        isCurrent: Bool
    ) -> some View {
        let bubbleTint = tint(for: idx)
        let bg: Color = isCurrent
            ? bubbleTint.opacity(0.10)
            : skin.palette.mutedFill.opacity(0.35)
        let fg: Color = isCurrent ? skin.palette.primaryText : skin.palette.secondaryText
        // All bubbles use CachedFlowLayout of per-word tokens — same layout
        // algorithm whether current or not. This guarantees line breaks don't
        // shift when a sentence becomes current (the prior design mixed a
        // single wrapping Text with an overlay FlowLayout whose wrapping
        // disagreed, producing visible misalignment + jank).
        wordFlow(for: sentence, isCurrent: isCurrent, textColor: fg, tint: bubbleTint)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(bg, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
            .animation(AppMotion.contentFade, value: isCurrent)
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
                ForEach(rs.words) { word in
                    let isActive = word.id == highlightedWordIndex
                    Text(word.text)
                        .font(skin.typography.body)
                        .foregroundStyle(textColor)
                        .overlay(alignment: .bottom) {
                            if isActive {
                                Rectangle()
                                    .fill(tint)
                                    .frame(height: 1.5)
                                    .offset(y: 3)
                                    .transition(.opacity)
                            }
                        }
                        .onTapGesture {
                            onWordTap(word.text, rs.sentenceText)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            onPhraseTap(rs.sentenceText, rs.sentenceText)
                        }
                }
            }
            .animation(AppMotion.standardSpring, value: highlightedWordIndex)
        } else {
            CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
                // Use sentence.words (same source the current-branch uses) so
                // token count and line-wrapping stay identical when the sentence
                // becomes current — avoids any jump in bubble height.
                ForEach(Array(sentence.words.enumerated()), id: \.offset) { _, cue in
                    Text(cue.word)
                        .font(skin.typography.body)
                        .foregroundStyle(textColor)
                        .onTapGesture {
                            onWordTap(cue.word, sentence.text)
                        }
                        .onLongPressGesture(minimumDuration: 0.35) {
                            onPhraseTap(sentence.text, sentence.text)
                        }
                }
            }
        }
    }

    // MARK: - Follow pill

    @ViewBuilder
    private func followPill(_ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let speaker = renderState?.speaker {
                    let idx = hostNames.firstIndex(of: speaker)
                    Circle()
                        .fill(tint(for: idx))
                        .frame(width: 6, height: 6)
                }
                Text("追隨當前")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.primaryText)
                Image(systemName: "arrow.down")
                    .font(.caption2)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(
                Capsule()
                    .fill(skin.palette.cardBackground.opacity(0.96))
                    .overlay(Capsule().stroke(skin.palette.cardBorder, lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    // MARK: - Helpers

    private func tint(for idx: Int?) -> Color {
        switch idx {
        case 0: return skin.palette.accent
        case 1: return skin.palette.success
        default: return skin.palette.tertiaryText
        }
    }
}
