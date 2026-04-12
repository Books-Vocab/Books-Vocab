import SwiftUI

struct PodcastWordLevelView: View {
    let sentence: PodcastSentence?
    let currentCue: PodcastSubtitleCue?
    let hostNames: [String]
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        if let sentence {
            HStack(alignment: .top, spacing: skin.spacing.inlineGap) {
                SpeakerAccentBar(speaker: sentence.speaker, hostNames: hostNames)
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    SpeakerChip(speaker: sentence.speaker, hostNames: hostNames)
                    wordFlowLayout(sentence: sentence)
                }
            }
            .padding(skin.spacing.cardPadding)
            .background(skin.palette.cardBackground, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
            .animation(AppMotion.contentReveal, value: sentence.id)
        } else {
            Text("—")
                .font(skin.typography.body)
                .foregroundStyle(skin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func wordFlowLayout(sentence: PodcastSentence) -> some View {
        let words = sentence.text.split(separator: " ").map(String.init)
        FlowLayout(spacing: 4) {
            ForEach(Array(words.enumerated()), id: \.offset) { _, word in
                let isHighlighted = isWordHighlighted(word)
                Text(word)
                    .font(skin.typography.body)
                    .foregroundStyle(isHighlighted ? skin.palette.cardBackground : skin.palette.primaryText)
                    .padding(.horizontal, 2)
                    .padding(.vertical, 1)
                    .background(
                        isHighlighted ? skin.palette.accent : Color.clear,
                        in: RoundedRectangle(cornerRadius: 4, style: .continuous)
                    )
                    .animation(AppMotion.feedbackPulse, value: isHighlighted)
                    .onTapGesture { onWordTap(word, sentence.text) }
            }
        }
    }

    private func isWordHighlighted(_ word: String) -> Bool {
        guard let highlighted = currentCue?.highlightedWord else { return false }
        return highlighted.localizedCaseInsensitiveContains(word) || word.localizedCaseInsensitiveContains(highlighted)
    }
}

struct FlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        computeLayout(proposal: proposal, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = computeLayout(proposal: proposal, subviews: subviews)
        for (index, offset) in result.offsets.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y), proposal: .unspecified)
        }
    }

    private struct LayoutResult {
        var size: CGSize
        var offsets: [CGPoint]
    }

    private func computeLayout(proposal: ProposedViewSize, subviews: Subviews) -> LayoutResult {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, maxX: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0; y += rowHeight + spacing; rowHeight = 0
            }
            offsets.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x)
        }
        return LayoutResult(size: CGSize(width: maxX, height: y + rowHeight), offsets: offsets)
    }
}
