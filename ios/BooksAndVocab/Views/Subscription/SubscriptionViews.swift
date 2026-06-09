import SwiftUI

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
                    Text(title.localized)
                        .font(appSkin.typography.sectionTitle)
                        .foregroundStyle(appSkin.palette.primaryText)

                    Text(description.localized)
                        .font(appSkin.typography.body)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .lineSpacing(4)
                }

                Button(action: onAction) {
                    Text(actionTitle.localized)
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

#Preview("ProAccessGateCard") {
    AppThemeContainer {
        ProAccessGateCardPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct ProAccessGateCardPreview: View {
    @Environment(\.appSkin) private var appSkin

    var body: some View {
        ProAccessGateCard(
            title: "解鎖知識圖譜",
            description: "升級至 Pro 即可使用知識圖譜、Today Review 與播客功能。",
            actionTitle: "升級 Pro",
            systemImage: "sparkles",
            onAction: {}
        )
        .padding()
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}
