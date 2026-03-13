import SwiftUI

struct VocabCard<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let padding: CGFloat
    @ViewBuilder let content: Content

    init(
        padding: CGFloat? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding ?? VocabSkin.baseSpacing.cardPadding
        self.content = content()
    }

    var body: some View {
        AppSectionCard(
            padding: padding,
            style: .vocab(vocabSkin)
        ) {
            content
        }
    }
}

struct VocabToneChip: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String
    let tone: Color

    var body: some View {
        Text(text.localized)
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(tone)
            .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
            .padding(.vertical, vocabSkin.spacing.chipVerticalPadding)
            .background(tone.opacity(0.08))
            .clipShape(
                RoundedRectangle(cornerRadius: vocabSkin.radii.chip, style: .continuous)
            )
            .accessibilityLabel("語氣標記".localized)
    }
}

struct VocabTierLabel: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let tier: String
    var prominent: Bool = false

    var body: some View {
        Text(vocabSkin.tierLabel(for: tier))
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(vocabSkin.tierColor(for: tier).opacity(prominent ? 1 : 0.78))
            .padding(.horizontal, prominent ? vocabSkin.spacing.prominentChipHorizontalPadding : 0)
            .padding(.vertical, prominent ? vocabSkin.spacing.prominentChipVerticalPadding : 0)
            .background(
                Group {
                    if prominent {
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill(vocabSkin.tierColor(for: tier).opacity(0.08))
                    }
                }
            )
            .accessibilityLabel(L10n.format("難度等級：%@", tier))
    }
}

struct VocabEmptyStateContent: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let description: String

    var body: some View {
        AppEmptyStateContent(
            title: title,
            systemImage: systemImage,
            description: description,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabEmptyStateCard: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let description: String

    var body: some View {
        AppEmptyStateCard(
            title: title,
            systemImage: systemImage,
            description: description,
            cardStyle: .vocab(vocabSkin),
            contentStyle: .vocab(vocabSkin)
        )
    }
}

struct VocabStateMessageCard<Accessory: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let description: String?
    @ViewBuilder let accessory: Accessory

    init(
        title: String,
        systemImage: String,
        description: String? = nil,
        @ViewBuilder accessory: () -> Accessory = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.accessory = accessory()
    }

    var body: some View {
        AppStateMessageCard(
            title: title,
            systemImage: systemImage,
            description: description,
            style: .vocab(vocabSkin)
        ) {
            accessory
        }
    }
}

// MARK: - Shared Review Progress

struct VocabReviewProgress: Hashable {
    let statusLabel: String
    let detailLabel: String?
    let ratio: Double?
}

struct VocabReviewProgressBar: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @ScaledMetric(relativeTo: .body) private var scaledBarHeight: CGFloat = 5

    let progress: VocabReviewProgress

    var body: some View {
        if let ratio = progress.ratio {
            VStack(alignment: .trailing, spacing: vocabSkin.spacing.reviewProgressBarGap) {
                if let detailLabel = progress.detailLabel {
                    Text(detailLabel)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                GeometryReader { proxy in
                    let clampedFraction = min(ratio, 1.0)
                    ZStack(alignment: .leading) {
                        Capsule(style: .continuous)
                            .fill(vocabSkin.palette.progressBarBackground)

                        Capsule(style: .continuous)
                            .fill(ReviewGradient.color(for: ratio))
                            .frame(width: max(6, proxy.size.width * clampedFraction))
                            .animation(AppMotion.controlEaseOut, value: ratio)
                    }
                    .accessibilityLabel("複習進度".localized)
                    .accessibilityValue("\(Int(min(ratio, 1.0) * 100))%")
                }
                .frame(width: vocabSkin.metrics.progressBarWidth, height: scaledBarHeight)
            }
        } else if let detailLabel = progress.detailLabel {
            Text(detailLabel)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.secondaryText)
        }
    }
}

struct ReviewGradientBar: View {
    private let sampleCount = 20

    var body: some View {
        GeometryReader { proxy in
            HStack(spacing: 0) {
                ForEach(0..<sampleCount, id: \.self) { i in
                    let ratio = Double(i) / Double(sampleCount - 1) * 3.0
                    Rectangle().fill(ReviewGradient.color(for: ratio))
                }
            }
        }
    }
}

private struct VocabCanvasBackgroundModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content.background(vocabSkin.palette.pageBackground.ignoresSafeArea())
    }
}

extension View {
    func vocabCanvasBackground() -> some View {
        modifier(VocabCanvasBackgroundModifier())
    }
}
