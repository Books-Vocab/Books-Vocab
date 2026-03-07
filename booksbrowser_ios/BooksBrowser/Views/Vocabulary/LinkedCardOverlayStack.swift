import SwiftUI

struct LinkedCardOverlayStack: View {
    @Binding var stack: [VocabularyEntry]

    var body: some View {
        if !stack.isEmpty {
            ZStack {
                Color.black.opacity(0.20)
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
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(.secondary)

                Spacer()

                if index > 0 {
                    Text("+\(index)")
                        .font(AppFonts.caption(weight: .semibold))
                        .foregroundStyle(.tertiary)
                }

                Button {
                    close(from: index)
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, AppMetrics.spacingMedium)
            .padding(.vertical, 14)
            .background(Color.white.opacity(0.92))

            Divider()

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
        .background(Color.white.opacity(0.98))
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 0.8)
        )
        .shadow(color: .black.opacity(0.10), radius: 28, y: 14)
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
