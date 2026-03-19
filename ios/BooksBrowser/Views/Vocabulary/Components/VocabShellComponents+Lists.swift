import SwiftUI

// MARK: - List Cards, Status Hero, Timeline, Button Styles

struct VocabListCard<Header: View, Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let headerPadding: EdgeInsets
    @ViewBuilder let header: Header
    @ViewBuilder let content: Content

    init(
        headerPadding: EdgeInsets? = nil,
        @ViewBuilder header: () -> Header,
        @ViewBuilder content: () -> Content
    ) {
        self.headerPadding = headerPadding ?? EdgeInsets(
            top: VocabSkin.baseMetrics.listCardHeaderTopInset,
            leading: VocabSkin.baseMetrics.listRowHorizontalInset,
            bottom: VocabSkin.baseMetrics.listCardHeaderBottomInset,
            trailing: VocabSkin.baseMetrics.listRowHorizontalInset
        )
        self.header = header()
        self.content = content()
    }

    var body: some View {
        VocabCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                header
                    .padding(headerPadding)

                Rectangle()
                    .fill(vocabSkin.palette.divider)
                    .frame(height: AppMetrics.dividerThin)
                    .padding(.horizontal, vocabSkin.metrics.listDividerInset)

                content
            }
        }
    }
}

struct VocabStatusHero<Badges: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    var tone: Color
    let title: String
    var description: String? = nil
    @ViewBuilder let badges: Badges

    init(
        systemImage: String,
        tone: Color,
        title: String,
        description: String? = nil,
        @ViewBuilder badges: () -> Badges = { EmptyView() }
    ) {
        self.systemImage = systemImage
        self.tone = tone
        self.title = title
        self.description = description
        self.badges = badges()
    }

    var body: some View {
        VStack(spacing: vocabSkin.spacing.statusHeroGap) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.symbolHero)
                .foregroundStyle(tone)

            Text(title.localized)
                .font(vocabSkin.typography.sectionTitle)

            if let description {
                Text(description.localized)
                    .font(vocabSkin.typography.body)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .padding(.horizontal, vocabSkin.spacing.heroDescriptionHorizontalInset)
            }

            badges
        }
    }
}

struct VocabTimelineRow<Trailing: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let statusSymbol: AnyView
    let title: String
    let titleTone: Color
    let detail: String?
    let detailTone: Color
    @ViewBuilder let trailing: Trailing

    init(
        title: String,
        titleTone: Color,
        detail: String? = nil,
        detailTone: Color,
        @ViewBuilder statusSymbol: () -> some View,
        @ViewBuilder trailing: () -> Trailing = { EmptyView() }
    ) {
        self.statusSymbol = AnyView(statusSymbol())
        self.title = title
        self.titleTone = titleTone
        self.detail = detail
        self.detailTone = detailTone
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: vocabSkin.spacing.timelineRowGap) {
            statusSymbol
                .frame(width: 20)

            VStack(alignment: .leading, spacing: vocabSkin.spacing.timelineDetailGap) {
                HStack {
                    Text(title.localized)
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(titleTone)

                    Spacer()

                    trailing
                }

                if let detail, !detail.isEmpty {
                    Text(detail.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(detailTone)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, vocabSkin.spacing.sectionGap)
    }
}

struct VocabActionButtonStyle: ButtonStyle {
    @Environment(\.vocabSkin) private var vocabSkin
    let tone: VocabActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette

        configuration.label
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(palette.foreground)
            .padding(.horizontal, vocabSkin.spacing.actionButtonHorizontalPadding)
            .padding(.vertical, vocabSkin.spacing.actionButtonVerticalPadding)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(palette.background)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.992 : 1)
            .animateControl(configuration.isPressed)
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return styleFromShared(.primary)
        case .neutral:
            return styleFromShared(.neutral)
        case .success:
            return (
                vocabSkin.palette.success,
                vocabSkin.palette.success.opacity(VocabActionButtonPalette.idleFillOpacity),
                vocabSkin.palette.success.opacity(VocabActionButtonPalette.borderOpacity)
            )
        case .warning:
            let warning = vocabSkin.palette.warning
            return (
                warning,
                warning.opacity(VocabActionButtonPalette.warningIdleFillOpacity),
                warning.opacity(VocabActionButtonPalette.borderOpacity)
            )
        case .destructive:
            return styleFromShared(.destructive)
        }
    }

    private func styleFromShared(_ tone: AppActionTone) -> (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return (vocabSkin.palette.pageBackground, vocabSkin.palette.primaryText, vocabSkin.palette.primaryText)
        case .neutral:
            return (
                vocabSkin.palette.primaryText,
                vocabSkin.palette.cardBackground,
                vocabSkin.palette.cardBorder
            )
        case .outline:
            return (
                vocabSkin.palette.primaryText,
                .clear,
                vocabSkin.palette.secondaryText.opacity(VocabActionButtonPalette.outlineBorderOpacity)
            )
        case .destructive:
            return (
                vocabSkin.palette.destructive,
                vocabSkin.palette.destructive.opacity(VocabActionButtonPalette.idleFillOpacity),
                vocabSkin.palette.destructive.opacity(VocabActionButtonPalette.borderOpacity)
            )
        }
    }
}

private enum VocabActionButtonPalette {
    static let idleFillOpacity: Double = 0.10
    static let warningIdleFillOpacity: Double = 0.12
    static let borderOpacity: Double = 0.22
    static let outlineBorderOpacity: Double = 0.3
}

extension ButtonStyle where Self == VocabActionButtonStyle {
    static func vocabAction(_ tone: VocabActionTone = .primary) -> VocabActionButtonStyle {
        VocabActionButtonStyle(tone: tone)
    }
}
