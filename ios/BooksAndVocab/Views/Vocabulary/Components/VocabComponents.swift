import SwiftUI

struct VocabCard<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let padding: CGFloat
    @ViewBuilder let content: Content

    init(
        padding: CGFloat? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding ?? AppSkin.baseSpacing.cardPadding
        self.content = content()
    }

    var body: some View {
        AppSectionCard(
            padding: padding,
            style: .vocab(appSkin)
        ) {
            content
        }
        .enableInjection()
    }
}

// MARK: - Card Background Modifier

/// 為已有 padding 的內容套用 AppSkin 標準卡片背景（fill + border stroke）
/// 用於不需要 VocabCard 容器的情境（例如 calendarSection 自行管理 padding）
private struct VocabCardBackgroundModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        content
            .padding(appSkin.spacing.cardPadding)
            .background(
                RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous)
                    .fill(appSkin.palette.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous)
                            .stroke(appSkin.palette.cardBorder, lineWidth: 1)
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
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let text: String
    let tone: Color

    var body: some View {
        Text(text.localized)
            .font(appSkin.typography.caption)
            .foregroundStyle(tone)
            .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
            .padding(.vertical, appSkin.spacing.chipVerticalPadding)
            .background(tone.opacity(0.08))
            .clipShape(
                Capsule(style: .continuous)
            )
            .accessibilityLabel("語氣標記".localized)
            .enableInjection()
    }
}

struct VocabTierLabel: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let tier: String
    var prominent: Bool = false

    var body: some View {
        Text(appSkin.tierLabel(for: tier))
            .font(appSkin.typography.monoLabel)
            .foregroundStyle(appSkin.tierColor(for: tier).opacity(prominent ? 1 : 0.78))
            .padding(.horizontal, prominent ? appSkin.spacing.prominentChipHorizontalPadding : 0)
            .padding(.vertical, prominent ? appSkin.spacing.prominentChipVerticalPadding : 0)
            .background(
                Group {
                    if prominent {
                        Capsule(style: .continuous)
                            .fill(appSkin.tierColor(for: tier).opacity(0.08))
                    }
                }
            )
            .accessibilityLabel(L10n.format("難度等級：%@", tier))
            .enableInjection()
    }
}

struct VocabEmptyStateContent: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    let systemImage: String
    let description: String
    let guidanceText: String?
    let action: AppEmptyStateAction?
    let symbolBounce: Bool

    init(title: String, systemImage: String, description: String, guidanceText: String? = nil, action: AppEmptyStateAction? = nil, symbolBounce: Bool = false) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.guidanceText = guidanceText
        self.action = action
        self.symbolBounce = symbolBounce
    }

    var body: some View {
        AppEmptyStateContent(
            title: title,
            systemImage: systemImage,
            description: description,
            guidanceText: guidanceText,
            action: action,
            symbolBounce: symbolBounce,
            style: .vocab(appSkin)
        )
        .enableInjection()
    }
}

struct VocabEmptyStateCard: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
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
            cardStyle: .vocab(appSkin),
            contentStyle: .vocab(appSkin)
        )
        .enableInjection()
    }
}

struct VocabStateMessageCard<Accessory: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
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
            style: .vocab(appSkin)
        ) {
            accessory
        }
        .enableInjection()
    }
}

// MARK: - Shared Review Progress

struct VocabReviewProgress: Hashable {
    let statusLabel: String
    let detailLabel: String?
    let ratio: Double?
}

struct VocabReviewProgressBar: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @ScaledMetric(relativeTo: .body) private var scaledBarHeight: CGFloat = 5

    let progress: VocabReviewProgress

    var body: some View {
        Group {
            if let ratio = progress.ratio {
                VStack(alignment: .trailing, spacing: TodayReviewMetrics.progressBarGap) {
                    if let detailLabel = progress.detailLabel {
                        Text(detailLabel)
                            .font(appSkin.typography.monoLabel)
                            .monospacedDigit()
                            .foregroundStyle(appSkin.palette.secondaryText)
                    }

                    GeometryReader { proxy in
                        let clampedFraction = min(ratio, 1.0)
                        ZStack(alignment: .leading) {
                            Capsule(style: .continuous)
                                .fill(appSkin.palette.progressBarBackground)

                            Capsule(style: .continuous)
                                .fill(ReviewGradient.color(for: ratio))
                                .frame(width: max(6, proxy.size.width * clampedFraction))
                                .animateControl(ratio)
                        }
                        .accessibilityLabel("複習進度".localized)
                        .accessibilityValue("\(Int(min(ratio, 1.0) * 100))%")
                    }
                    .frame(width: appSkin.metrics.progressBarWidth, height: scaledBarHeight)
                }
            } else if let detailLabel = progress.detailLabel {
                Text(detailLabel)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.secondaryText)
            }
        }
        .enableInjection()
    }
}

struct ReviewGradientBar: View {
    @ObserveInjection private var inject
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
        .enableInjection()
    }
}

private struct VocabCanvasBackgroundModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        content.background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}

extension View {
    func vocabCanvasBackground() -> some View {
        modifier(VocabCanvasBackgroundModifier())
    }
}
