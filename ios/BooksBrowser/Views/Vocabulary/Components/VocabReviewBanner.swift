import SwiftUI

struct VocabReviewBanner<FilterContent: View>: View {
    @Environment(\.vocabSkin) private var skin

    let dueCount: Int
    let unlearnedCount: Int
    let onStartDue: () -> Void
    let onStartUnlearned: () -> Void
    @ViewBuilder let filterContent: FilterContent

    init(
        dueCount: Int,
        unlearnedCount: Int,
        onStartDue: @escaping () -> Void,
        onStartUnlearned: @escaping () -> Void,
        @ViewBuilder filterContent: () -> FilterContent = { EmptyView() }
    ) {
        self.dueCount = dueCount
        self.unlearnedCount = unlearnedCount
        self.onStartDue = onStartDue
        self.onStartUnlearned = onStartUnlearned
        self.filterContent = filterContent()
    }

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            HStack {
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    Text("今日複習".localized)
                        .font(skin.typography.captionStrong)
                        .foregroundStyle(skin.palette.primaryText)

                    HStack(spacing: 4) {
                        if dueCount > 0 {
                            Text(L10n.format("%@ 張到期", "\(dueCount)"))
                        }
                        if dueCount > 0 && unlearnedCount > 0 {
                            Text("·")
                        }
                        if unlearnedCount > 0 {
                            Text(L10n.format("%@ 未學習", "\(unlearnedCount)"))
                        }
                    }
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                }

                Spacer()

                filterContent
            }

            HStack(spacing: skin.spacing.inlineGap) {
                Spacer()

                if dueCount > 0 {
                    Button {
                        onStartDue()
                    } label: {
                        Label("到期複習".localized, systemImage: "clock.badge")
                            .font(skin.typography.captionStrong)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                }

                if unlearnedCount > 0 {
                    Button {
                        onStartUnlearned()
                    } label: {
                        Label("未學複習".localized, systemImage: "sparkles")
                            .font(skin.typography.captionStrong)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
        }
        .padding(skin.spacing.cardPadding)
        .background(skin.palette.cardBackground, in: RoundedRectangle(cornerRadius: skin.radii.card))
    }
}

#Preview {
    VocabReviewBanner(
        dueCount: 5,
        unlearnedCount: 3,
        onStartDue: {},
        onStartUnlearned: {}
    )
    .padding()
}
