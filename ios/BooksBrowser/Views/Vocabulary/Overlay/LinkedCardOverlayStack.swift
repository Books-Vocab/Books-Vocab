import SwiftUI

struct LinkedCardOverlayStack: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var stack: [VocabularyEntry]
    var allEntries: [VocabularyEntry] = []

    var body: some View {
        if !stack.isEmpty {
            ZStack {
                vocabSkin.palette.overlayScrim
                    .ignoresSafeArea()
                    .onTapGesture {
                        _ = stack.popLast()
                    }

                ForEach(Array(stack.enumerated()), id: \.element.id) { index, entry in
                    linkedCardLayer(entry: entry, index: index)
                        .zIndex(Double(index + 1))
                        .allowsHitTesting(index == stack.count - 1)
                        .animateSpring(stack.count)
                }
            }
            .transition(.overlayFade)
        }
    }

    private func linkedCardLayer(entry: VocabularyEntry, index: Int) -> some View {
        VStack(spacing: 0) {
            VocabOverlayHeader(
                title: index == 0 ? "Linked Card" : "Nested Link",
                systemImage: "rectangle.stack",
                badgeText: index > 0 ? "+\(index)" : nil,
                onClose: { close(from: index) }
            )

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: AppMetrics.dividerThin)

            WordDetailSheet(
                entry: entry,
                allEntries: allEntries,
                wrapInNavigation: false,
                linkedCardStack: $stack
            )
        }
        .frame(
            maxWidth: max(420, 680 - CGFloat(index) * AppOverlayMetrics.linkedCardLayerShrinkStep),
            maxHeight: max(420, 620 - CGFloat(index) * AppOverlayMetrics.linkedCardLayerShrinkStep)
        )
        .background(vocabSkin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous)
                .stroke(vocabSkin.palette.cardBorder.opacity(0.8), lineWidth: 1)
        )
        .shadow(color: vocabSkin.palette.shadow.opacity(1.4), radius: AppShadows.panelRadius, y: AppShadows.panelY)
        .padding(.horizontal, AppMetrics.spacingMedium + CGFloat(index) * AppOverlayMetrics.linkedCardLayerOffsetY)
        .padding(.vertical, AppMetrics.sectionInset + CGFloat(index) * AppOverlayMetrics.linkedCardLayerOffsetX)
        .scaleEffect(max(0.94, 1 - CGFloat(index) * 0.02))
        .offset(x: CGFloat(index) * AppOverlayMetrics.linkedCardLayerOffsetX, y: CGFloat(index) * AppOverlayMetrics.linkedCardLayerOffsetY)
        .transition(.linkedOverlayCard)
    }

    private func close(from index: Int) {
        guard stack.indices.contains(index) else { return }
        stack.removeSubrange(index...)
    }
}
