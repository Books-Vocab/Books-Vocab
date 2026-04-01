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

// MARK: - Card Background Modifier

/// 為已有 padding 的內容套用 VocabSkin 標準卡片背景（fill + border stroke）
/// 用於不需要 VocabCard 容器的情境（例如 calendarSection 自行管理 padding）
private struct VocabCardBackgroundModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .padding(vocabSkin.spacing.cardPadding)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .fill(vocabSkin.palette.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )
            )
    }
}

extension View {
    func vocabCardBackground() -> some View {
        modifier(VocabCardBackgroundModifier())
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
    let guidanceText: String?
    let symbolBounce: Bool

    init(title: String, systemImage: String, description: String, guidanceText: String? = nil, symbolBounce: Bool = false) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.guidanceText = guidanceText
        self.symbolBounce = symbolBounce
    }

    var body: some View {
        AppEmptyStateContent(
            title: title,
            systemImage: systemImage,
            description: description,
            guidanceText: guidanceText,
            symbolBounce: symbolBounce,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabEmptyStateCard: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let description: String
    let action: AppEmptyStateAction?

    init(title: String, systemImage: String, description: String, action: AppEmptyStateAction? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.action = action
    }

    var body: some View {
        AppEmptyStateCard(
            title: title,
            systemImage: systemImage,
            description: description,
            action: action,
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
                            .animateControl(ratio)
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
