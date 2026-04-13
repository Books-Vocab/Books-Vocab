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
                // User drag (pan on the transcript) disables follow mode.
                // Scroll-wheel / flick-inertia also produce drag gestures, which is
                // the correct semantic: any intentional movement breaks auto-follow.
                .simultaneousGesture(
                    DragGesture(minimumDistance: 6)
                        .onChanged { _ in
                            if isFollowing { isFollowing = false }
                        }
                )

                if !isFollowing, let id = currentId {
                    followPill {
                        isFollowing = true
                        withAnimation(AppMotion.standardSpring) {
                            proxy.scrollTo(id, anchor: .center)
                        }
                    }
                    .padding(.bottom, skin.spacing.sectionGap)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .onAppear {
                // One-shot initial scroll so the user lands at the current sentence.
                if !didInitialScroll, let id = currentId {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        proxy.scrollTo(id, anchor: .center)
                        didInitialScroll = true
                    }
                }
            }
            .onChange(of: currentId) { _, newId in
                // Auto-follow: smoothly recenter when the sentence advances.
                guard isFollowing, let newId else { return }
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
        // Always render the sentence text with the same Text view; overlay the
        // active-word underline when current. This keeps layout stable — no
        // resize, no re-measure — so transitioning current state is purely a
        // color/opacity interpolation, not a layout recomputation.
        Text(sentence.text)
            .font(skin.typography.body)
            .foregroundStyle(fg)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(bg, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
            .overlay(alignment: .topLeading) {
                if isCurrent, let rs = renderState {
                    tappableWordsOverlay(rs, tint: bubbleTint)
                }
            }
            .animation(AppMotion.contentFade, value: isCurrent)
    }

    /// Overlay that mirrors the sentence layout and renders tappable words
    /// with a sliding active-word underline. Layered on top of the same Text
    /// so the underlying bubble doesn't shift size when the overlay appears.
    @ViewBuilder
    private func tappableWordsOverlay(_ rs: SubtitleRenderState, tint: Color) -> some View {
        CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
            ForEach(rs.words) { word in
                let isActive = word.id == highlightedWordIndex
                Text(word.text)
                    .font(skin.typography.body)
                    .foregroundStyle(skin.palette.primaryText)
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
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .animation(AppMotion.standardSpring, value: highlightedWordIndex)
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
