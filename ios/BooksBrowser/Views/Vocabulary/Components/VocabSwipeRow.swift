import SwiftUI

/// A row wrapper that reveals a trailing action button when swiped left.
/// Designed for ScrollView > LazyVStack where native .swipeActions doesn't work.
struct VocabSwipeRow<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let itemID: UUID
    @Binding var activeSwipeID: UUID?
    let actionLabel: String
    let actionImage: String
    let actionTint: Color
    let onAction: () -> Void
    @ViewBuilder let content: Content

    @State private var offset: CGFloat = 0

    private let buttonWidth: CGFloat = 72

    private var isOpen: Bool { activeSwipeID == itemID }

    var body: some View {
        ZStack(alignment: .trailing) {
            Button(action: performAction) {
                VStack(spacing: vocabSkin.spacing.microGap) {
                    Image(systemName: actionImage)
                        .font(vocabSkin.typography.iconMedium)
                    Text(actionLabel.localized)
                        .font(vocabSkin.typography.caption)
                }
                .foregroundStyle(.white)
                .frame(width: buttonWidth)
                .frame(maxHeight: .infinity)
                .background(actionTint)
            }
            .buttonStyle(.plain)

            content
                .background(vocabSkin.palette.cardBackground)
                .offset(x: offset)
                .overlay {
                    if isOpen {
                        Color.clear
                            .contentShape(Rectangle())
                            .onTapGesture { close() }
                    }
                }
                .gesture(swipeGesture)
        }
        .clipped()
        .onChange(of: activeSwipeID) { _, newID in
            if newID != itemID && offset != 0 {
                withAnimation(AppMotion.swipeSnapBackSpring) {
                    offset = 0
                }
            }
        }
    }

    private var swipeGesture: some Gesture {
        DragGesture(minimumDistance: 20)
            .onChanged { value in
                guard abs(value.translation.width) > abs(value.translation.height) else { return }

                let base: CGFloat = isOpen ? -buttonWidth : 0
                var newOffset = base + value.translation.width
                newOffset = min(newOffset, isOpen ? 0 : 6)
                newOffset = max(newOffset, -buttonWidth * 1.3)
                offset = newOffset
            }
            .onEnded { value in
                let base: CGFloat = isOpen ? -buttonWidth : 0
                let projected = base + value.predictedEndTranslation.width
                let shouldOpen = projected < -buttonWidth / 2

                withAnimation(AppMotion.swipeSnapBackSpring) {
                    if shouldOpen {
                        offset = -buttonWidth
                        activeSwipeID = itemID
                    } else {
                        offset = 0
                        if isOpen { activeSwipeID = nil }
                    }
                }
            }
    }

    private func performAction() {
        close()
        onAction()
    }

    private func close() {
        withAnimation(AppMotion.swipeSnapBackSpring) {
            offset = 0
            activeSwipeID = nil
        }
    }
}
