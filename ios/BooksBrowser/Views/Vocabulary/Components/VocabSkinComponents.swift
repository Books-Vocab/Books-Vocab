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
            .accessibilityLabel("語氣標記")
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
            .accessibilityLabel("難度等級：\(tier)")
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
    enum Tone: Hashable {
        case green
        case yellow
        case orange
        case red
    }

    let statusLabel: String
    let detailLabel: String?
    let fraction: Double?
    let tone: Tone
}

struct VocabReviewProgressBar: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @ScaledMetric(relativeTo: .body) private var scaledBarHeight: CGFloat = 5

    let progress: VocabReviewProgress

    var body: some View {
        if let fraction = progress.fraction {
            VStack(alignment: .trailing, spacing: vocabSkin.spacing.reviewProgressBarGap) {
                if let detailLabel = progress.detailLabel {
                    Text(detailLabel)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                GeometryReader { proxy in
                    ZStack(alignment: .leading) {
                        Capsule(style: .continuous)
                            .fill(vocabSkin.palette.progressBarBackground)

                        Capsule(style: .continuous)
                            .fill(resolveTone(progress.tone))
                            .frame(width: max(6, proxy.size.width * fraction))
                            .animation(AppMotion.controlEaseOut, value: fraction)
                    }
                    .accessibilityLabel("複習進度")
                    .accessibilityValue("\(Int(fraction * 100))%")
                }
                .frame(width: vocabSkin.metrics.progressBarWidth, height: scaledBarHeight)
            }
        } else if let detailLabel = progress.detailLabel {
            Text(detailLabel)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.secondaryText)
        }
    }

    private func resolveTone(_ tone: VocabReviewProgress.Tone) -> Color {
        switch tone {
        case .green:
            return vocabSkin.palette.success
        case .yellow:
            return vocabSkin.palette.tierIntermediate
        case .orange:
            return vocabSkin.palette.tierAdvanced
        case .red:
            return vocabSkin.palette.destructive
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
