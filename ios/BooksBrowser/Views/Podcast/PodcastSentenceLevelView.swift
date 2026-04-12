import SwiftUI

struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let currentSentenceId: Int?
    let hostNames: [String]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: skin.spacing.wordRowVerticalGap) {
                    ForEach(sentences) { sentence in
                        let isCurrent = sentence.id == currentSentenceId
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
            .onChange(of: currentSentenceId) { _, newId in
                guard let newId else { return }
                withAnimation(AppMotion.standardSpring) {
                    proxy.scrollTo(newId, anchor: .center)
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
                if isCurrent {
                    tappableText(sentence)
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
    private func tappableText(_ sentence: PodcastSentence) -> some View {
        let words = sentence.text.split(separator: " ").map(String.init)
        FlowLayout(spacing: 4) {
            ForEach(Array(words.enumerated()), id: \.offset) { _, word in
                Text(word)
                    .font(skin.typography.body)
                    .foregroundStyle(skin.palette.primaryText)
                    .onTapGesture { onWordTap(word, sentence.text) }
            }
        }
    }
}
