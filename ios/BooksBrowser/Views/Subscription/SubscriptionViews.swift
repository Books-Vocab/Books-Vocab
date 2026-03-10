import SwiftUI

struct ProAccessGateCard: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let title: String
    let description: String
    let actionTitle: String
    let systemImage: String
    let onAction: () -> Void

    var body: some View {
        VocabCard {
            VStack(spacing: 16) {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(vocabSkin.palette.accent)
                    .transition(.contentSwap)

                VStack(spacing: 6) {
                    Text(title)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text(description)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .lineSpacing(4)
                }

                Button(action: onAction) {
                    Text(actionTitle)
                        .font(vocabSkin.typography.body.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.vocabAction(.primary))
            }
            .padding(.vertical, 8)
            .transition(.contentSwap)
        }
    }
}
