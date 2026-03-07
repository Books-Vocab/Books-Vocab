import SwiftUI

struct LinkedCardOverlayStack: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var stack: [VocabularyEntry]

    var body: some View {
        if !stack.isEmpty {
            ZStack {
                vocabSkin.palette.primaryText.opacity(0.10)
                    .ignoresSafeArea()
                    .onTapGesture {
                        _ = stack.popLast()
                    }

                ForEach(Array(stack.enumerated()), id: \.element.id) { index, entry in
                    linkedCardLayer(entry: entry, index: index)
                        .zIndex(Double(index + 1))
                        .allowsHitTesting(index == stack.count - 1)
                }
            }
            .transition(.opacity)
        }
    }

    private func linkedCardLayer(entry: VocabularyEntry, index: Int) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: AppMetrics.spacingSmall) {
                Label(index == 0 ? "Linked Card" : "Nested Link", systemImage: "rectangle.stack")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)

                Spacer()

                if index > 0 {
                    Text("+\(index)")
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }

                Button {
                    close(from: index)
                } label: {
                    Image(systemName: "xmark.circle")
                        .font(.system(size: 18, weight: .thin))
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, AppMetrics.spacingMedium)
            .padding(.vertical, 14)

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: 0.5)

            WordDetailSheet(
                entry: entry,
                wrapInNavigation: false,
                linkedCardStack: $stack
            )
        }
        .frame(
            maxWidth: max(420, 680 - CGFloat(index * 18)),
            maxHeight: max(420, 620 - CGFloat(index * 18))
        )
        .background(vocabSkin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous)
                .stroke(vocabSkin.palette.cardBorder.opacity(0.8), lineWidth: 1)
        )
        .shadow(color: vocabSkin.palette.shadow.opacity(1.4), radius: 28, y: 14)
        .padding(.horizontal, AppMetrics.spacingMedium + CGFloat(index * 10))
        .padding(.vertical, AppMetrics.spacingExtraLarge + CGFloat(index * 8))
        .scaleEffect(max(0.94, 1 - CGFloat(index) * 0.02))
        .offset(x: CGFloat(index * 8), y: CGFloat(index * 10))
        .transition(.scale(scale: 0.96).combined(with: .opacity))
    }

    private func close(from index: Int) {
        guard stack.indices.contains(index) else { return }
        stack.removeSubrange(index...)
    }
}
