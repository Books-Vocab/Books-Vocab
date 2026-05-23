import SwiftUI
import Inject

struct ProAccessGateCard: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let title: String
    let description: String
    let actionTitle: String
    let systemImage: String
    let onAction: () -> Void

    var body: some View {
        VocabCard {
            VStack(spacing: AppSpacing.s4) {
                Image(systemName: systemImage)
                    .font(appSkin.typography.symbolHero)
                    .foregroundStyle(appSkin.palette.accent)
                    .transition(.contentSwap)

                VStack(spacing: 6) {
                    Text(title)
                        .font(appSkin.typography.sectionTitle)
                        .foregroundStyle(appSkin.palette.primaryText)

                    Text(description)
                        .font(appSkin.typography.body)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .lineSpacing(4)
                }

                Button(action: onAction) {
                    Text(actionTitle)
                        .font(appSkin.typography.body.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, appSkin.spacing.rowContentSpacing)
                }
                .buttonStyle(.vocabAction(.primary))
            }
            .padding(.vertical, appSkin.spacing.inlineGap)
            .transition(.contentSwap)
        }
        .enableInjection()
    }
}
