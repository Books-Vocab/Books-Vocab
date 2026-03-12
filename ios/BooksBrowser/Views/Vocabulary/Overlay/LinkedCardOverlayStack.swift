import SwiftUI

private enum LinkedCardStackMetrics {
    /// 每層堆疊的水平位移步長
    static let layerOffsetX: CGFloat = 8
    /// 每層堆疊的垂直位移步長
    static let layerOffsetY: CGFloat = 10
    /// 每層堆疊的尺寸縮減步長
    static let layerShrinkStep: CGFloat = 18
    /// 第 0 層的水平 padding 基底（= cardBlockContentGap）
    static let baseHorizontalPadding: CGFloat = 16
    /// 第 0 層的垂直 padding 基底（= overlayVerticalInset）
    static let baseVerticalPadding: CGFloat = 20
}

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
                        .animation(AppMotion.standardSpring, value: stack.count)
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
                .frame(height: 0.5)

            WordDetailSheet(
                entry: entry,
                allEntries: allEntries,
                wrapInNavigation: false,
                linkedCardStack: $stack
            )
        }
        .frame(
            maxWidth: max(420, 680 - CGFloat(index) * LinkedCardStackMetrics.layerShrinkStep),
            maxHeight: max(420, 620 - CGFloat(index) * LinkedCardStackMetrics.layerShrinkStep)
        )
        .background(vocabSkin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous)
                .stroke(vocabSkin.palette.cardBorder.opacity(0.8), lineWidth: 1)
        )
        .shadow(color: vocabSkin.palette.shadow.opacity(1.4), radius: AppShadows.panelRadius, y: AppShadows.panelY)
        .padding(.horizontal, LinkedCardStackMetrics.baseHorizontalPadding + CGFloat(index) * LinkedCardStackMetrics.layerOffsetY)
        .padding(.vertical, LinkedCardStackMetrics.baseVerticalPadding + CGFloat(index) * LinkedCardStackMetrics.layerOffsetX)
        .scaleEffect(max(0.94, 1 - CGFloat(index) * 0.02))
        .offset(x: CGFloat(index) * LinkedCardStackMetrics.layerOffsetX, y: CGFloat(index) * LinkedCardStackMetrics.layerOffsetY)
        .transition(.linkedOverlayCard)
    }

    private func close(from index: Int) {
        guard stack.indices.contains(index) else { return }
        stack.removeSubrange(index...)
    }
}
