import SwiftUI

/// Chat-style transcript: sentences laid out as left/right bubbles by speaker.
///
/// Design principles:
///   • flat — no shadow, no scale lift, no blur
///   • passive — current sentence highlights but does NOT auto-center;
///     a "回到正在播放" pill appears when the current sentence scrolls off.
///   • alignment distinguishes speakers (host[0] → left, host[1] → right),
///     removing the need for accent bars / chips on each bubble.
struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let highlightedWordIndex: Int
    let hostNames: [String]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    @State private var visibleIds: Set<Int> = []
    @State private var pillEnabled = false

    private var currentId: Int? { renderState?.sentenceId }

    private var isCurrentVisible: Bool {
        guard let id = currentId else { return true }
        return visibleIds.contains(id)
    }

    var body: some View {
        ScrollViewReader { proxy in
            ZStack(alignment: .bottom) {
                ScrollView {
                    LazyVStack(spacing: skin.spacing.inlineGap) {
                        ForEach(sentences) { sentence in
                            bubbleRow(sentence)
                                .id(sentence.id)
                                .onAppear { visibleIds.insert(sentence.id) }
                                .onDisappear { visibleIds.remove(sentence.id) }
                        }
                    }
                    .padding(.vertical, skin.spacing.sectionGap)
                    .padding(.horizontal, skin.spacing.cardPadding)
                }

                if pillEnabled && !isCurrentVisible, let id = currentId {
                    returnPill {
                        withAnimation(AppMotion.standardSpring) {
                            proxy.scrollTo(id, anchor: .center)
                        }
                    }
                    .padding(.bottom, skin.spacing.sectionGap)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .onAppear {
                // One-shot scroll to current on entry; then enable pill logic
                // after a settle delay so lazy-stack visibility stabilizes.
                if let id = currentId {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        proxy.scrollTo(id, anchor: .center)
                    }
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    pillEnabled = true
                }
            }
            .animation(AppMotion.contentFade, value: isCurrentVisible)
        }
    }

    // MARK: - Bubble row

    @ViewBuilder
    private func bubbleRow(_ sentence: PodcastSentence) -> some View {
        let idx = hostNames.firstIndex(of: sentence.speaker)
        let alignRight = (idx == 1)
        let isCurrent = sentence.id == currentId
        HStack(alignment: .bottom, spacing: 0) {
            if alignRight { Spacer(minLength: 48) }
            VStack(alignment: alignRight ? .trailing : .leading, spacing: 3) {
                Text(sentence.speaker)
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(tint(for: idx).opacity(isCurrent ? 0.85 : 0.45))
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
        Group {
            if isCurrent, let rs = renderState {
                tappableWords(rs, tint: bubbleTint)
            } else {
                Text(sentence.text)
                    .font(skin.typography.body)
                    .foregroundStyle(fg)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(bg, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .animation(AppMotion.contentFade, value: isCurrent)
    }

    @ViewBuilder
    private func tappableWords(_ rs: SubtitleRenderState, tint: Color) -> some View {
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
                        }
                    }
                    .animation(AppMotion.feedbackPulse, value: isActive)
                    .onTapGesture {
                        onWordTap(word.text, rs.sentenceText)
                    }
            }
        }
    }

    // MARK: - Return pill

    @ViewBuilder
    private func returnPill(_ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let speaker = renderState?.speaker {
                    let idx = hostNames.firstIndex(of: speaker)
                    Circle()
                        .fill(tint(for: idx))
                        .frame(width: 6, height: 6)
                }
                Text("回到正在播放")
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
