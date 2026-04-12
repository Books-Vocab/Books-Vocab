import SwiftUI

struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let renderState: SubtitleRenderState?
    let highlightedWordIndex: Int
    let hostNames: [String]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    @State private var scrollDebounceTask: Task<Void, Never>?

    private var currentIndex: Int? {
        guard let sid = renderState?.sentenceId else { return nil }
        return sentences.firstIndex { $0.id == sid }
    }

    /// Windowed range: only render sentences within +-10 of current.
    private var windowedSentences: [PodcastSentence] {
        guard let idx = currentIndex else { return sentences }
        let lo = max(0, idx - 10)
        let hi = min(sentences.count - 1, idx + 10)
        return Array(sentences[lo...hi])
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: skin.spacing.wordRowVerticalGap) {
                    ForEach(windowedSentences) { sentence in
                        let isCurrent = sentence.id == renderState?.sentenceId
                        sentenceRow(sentence, isCurrent: isCurrent)
                            .id(sentence.id)
                            .opacity(isCurrent ? 1.0 : 0.4)
                            .animation(AppMotion.contentFade, value: isCurrent)
                            .onTapGesture {
                                if !isCurrent { onSentenceTap(sentence) }
                            }
                    }
                }
                .padding(.vertical, skin.spacing.sectionGap)
            }
            .onChange(of: renderState?.sentenceId) { _, newId in
                scrollDebounceTask?.cancel()
                scrollDebounceTask = Task {
                    try? await Task.sleep(for: .milliseconds(100))
                    guard !Task.isCancelled else { return }
                    guard let newId else { return }
                    withAnimation(AppMotion.standardSpring) {
                        proxy.scrollTo(newId, anchor: .center)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func sentenceRow(_ sentence: PodcastSentence, isCurrent: Bool) -> some View {
        HStack(alignment: .top, spacing: skin.spacing.inlineGap) {
            SpeakerAccentBar(speaker: sentence.speaker, hostNames: hostNames)
            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                SpeakerChip(speaker: sentence.speaker, hostNames: hostNames)
                if isCurrent, let rs = renderState {
                    tappableWords(rs)
                } else {
                    Text(sentence.text)
                        .font(skin.typography.body)
                        .foregroundStyle(skin.palette.primaryText)
                }
            }
        }
        .padding(skin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .fill(isCurrent ? skin.palette.cardBackground : Color.clear)
        )
    }

    @ViewBuilder
    private func tappableWords(_ rs: SubtitleRenderState) -> some View {
        CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
            ForEach(rs.words) { word in
                let isHighlighted = word.id == highlightedWordIndex
                Text(word.text)
                    .font(skin.typography.body)
                    .foregroundStyle(
                        isHighlighted
                            ? skin.palette.cardBackground
                            : skin.palette.primaryText
                    )
                    .padding(.horizontal, AppMetrics.spacingMicro)
                    .padding(.vertical, 1)
                    .background(
                        isHighlighted ? skin.palette.accent : Color.clear,
                        in: RoundedRectangle(cornerRadius: skin.radii.tiny, style: .continuous)
                    )
                    .animation(AppMotion.feedbackPulse, value: isHighlighted)
                    .onTapGesture {
                        onWordTap(word.text, rs.sentenceText)
                    }
            }
        }
    }
}
