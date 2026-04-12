import SwiftUI

struct PodcastWordLevelView: View {
    let renderState: SubtitleRenderState
    let highlightedWordIndex: Int
    let hostNames: [String]
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        HStack(alignment: .top, spacing: skin.spacing.inlineGap) {
            SpeakerAccentBar(speaker: renderState.speaker, hostNames: hostNames)
            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                SpeakerChip(speaker: renderState.speaker, hostNames: hostNames)
                wordFlow
            }
        }
        .padding(skin.spacing.cardPadding)
        .background(
            skin.palette.cardBackground,
            in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
        )
        .animation(AppMotion.contentReveal, value: renderState.sentenceId)
    }

    @ViewBuilder
    private var wordFlow: some View {
        CachedFlowLayout(spacing: skin.spacing.wordRowVerticalGap) {
            ForEach(renderState.words) { word in
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
                        onWordTap(word.text, renderState.sentenceText)
                    }
            }
        }
    }
}

// MARK: - CachedFlowLayout (uses Layout cache to avoid double-compute)

struct CachedFlowLayout: Layout {
    let spacing: CGFloat

    struct LayoutData {
        var size: CGSize
        var offsets: [CGPoint]
    }

    func makeCache(subviews: Subviews) -> LayoutData {
        LayoutData(size: .zero, offsets: [])
    }

    func sizeThatFits(
        proposal: ProposedViewSize, subviews: Subviews, cache: inout LayoutData
    ) -> CGSize {
        cache = computeLayout(proposal: proposal, subviews: subviews)
        return cache.size
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews,
        cache: inout LayoutData
    ) {
        for (index, offset) in cache.offsets.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y),
                proposal: .unspecified
            )
        }
    }

    private func computeLayout(
        proposal: ProposedViewSize, subviews: Subviews
    ) -> LayoutData {
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
        return LayoutData(
            size: CGSize(width: maxX, height: y + rowHeight),
            offsets: offsets
        )
    }
}
