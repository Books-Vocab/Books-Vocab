import SwiftUI

enum VocabActionTone {
    case primary
    case neutral
    case success
    case warning
    case destructive
}

typealias VocabTabOption<ID: Hashable> = AppTabOption<ID>

struct VocabTabSelector<ID: Hashable>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: ID

    var body: some View {
        AppTabSelector(
            options: options,
            selection: $selection,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabChromePill: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    var count: Int? = nil
    var emphasized: Bool = false

    var body: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconSmall)

            Text(title.localized)
                .font(vocabSkin.typography.captionStrong)

            if let count {
                Text("\(count)")
                    .font(vocabSkin.typography.monoLabel)
                    .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
                    .padding(.vertical, vocabSkin.spacing.compactRowAccessoryTopInset)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill((emphasized ? vocabSkin.palette.overlayFill : vocabSkin.palette.mutedFill))
                    )
            }
        }
        .foregroundStyle(emphasized ? Color.white : vocabSkin.palette.secondaryText)
        .padding(.horizontal, vocabSkin.spacing.chipHorizontalPaddingOuter)
        .padding(.vertical, vocabSkin.spacing.chipVerticalPadding + 2)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .fill(emphasized ? vocabSkin.palette.primaryText : vocabSkin.palette.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .stroke(emphasized ? vocabSkin.palette.primaryText : vocabSkin.palette.cardBorder, lineWidth: 1)
        )
    }
}

struct VocabSearchField: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var text: String
    let prompt: String

    var body: some View {
        AppSearchField(
            text: $text,
            prompt: prompt,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabToolbarGlyph: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    let badge: String?
    let tone: Color?

    init(systemImage: String, badge: String? = nil, tone: Color? = nil) {
        self.systemImage = systemImage
        self.badge = badge
        self.tone = tone
    }

    var body: some View {
        AppToolbarGlyph(
            systemImage: systemImage,
            badge: badge,
            style: .vocab(vocabSkin, tone: tone)
        )
    }
}

struct VocabChromeIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    var tone: Color? = nil
    var label: String? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(tone ?? vocabSkin.palette.secondaryText)
                .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.cardBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label ?? systemImage)
    }
}

struct VocabOverlayHeader<LeadingAccessory: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    var badgeText: String? = nil
    let onClose: () -> Void
    @ViewBuilder let leadingAccessory: LeadingAccessory

    init(
        title: String,
        systemImage: String,
        badgeText: String? = nil,
        onClose: @escaping () -> Void,
        @ViewBuilder leadingAccessory: () -> LeadingAccessory = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.badgeText = badgeText
        self.onClose = onClose
        self.leadingAccessory = leadingAccessory()
    }

    var body: some View {
        HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
            leadingAccessory

            Label(title.localized, systemImage: systemImage)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            if let badgeText {
                Text(badgeText)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
                    .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill(vocabSkin.palette.mutedFill)
                    )
            }

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", label: "關閉", action: onClose)
        }
        .padding(.horizontal, vocabSkin.metrics.overlayHeaderHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.overlayHeaderVerticalInset)
    }
}

struct VocabInlineActionButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    var tone: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(title.localized, action: action)
            .font(vocabSkin.typography.body)
            .foregroundStyle(tone ?? vocabSkin.palette.accent)
            .buttonStyle(.plain)
    }
}

struct VocabSectionHeader: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    var systemImage: String? = nil
    var trailingText: String? = nil

    var body: some View {
        HStack(spacing: vocabSkin.spacing.microGap) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconTiny)
            }

            Text(title.localized)
                .font(vocabSkin.typography.captionStrong)
                .tracking(vocabSkin.metrics.labelTracking)

            if let trailingText {
                Text(trailingText.localized)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }

            Spacer()
        }
        .foregroundStyle(vocabSkin.palette.tertiaryText)
    }
}

struct VocabSliderRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let format: String
    var labelWidth: CGFloat = 52
    var valueWidth: CGFloat = 36

    var body: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Text(label.localized)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .frame(width: labelWidth, alignment: .leading)

            Slider(value: $value, in: range)

            Text(String(format: format, value))
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: valueWidth, alignment: .trailing)
        }
        .frame(height: vocabSkin.metrics.tabSelectorHeight)
    }
}

struct VocabMetricHeroCard: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let description: String
    let value: String

    var body: some View {
        VocabCard {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title.localized)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text(description.localized)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                Spacer()

                Text(value)
                    .font(vocabSkin.typography.numericHero)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .monospacedDigit()
            }
        }
    }
}

struct VocabAccessoryIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    let tone: Color
    var background: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconToolbar)
                .foregroundStyle(tone)
                .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                        .fill(background ?? vocabSkin.palette.mutedFill)
                )
        }
        .buttonStyle(.plain)
    }
}

struct VocabSortPill: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var sortOption: KGVocabSortOption

    var body: some View {
        Menu {
            ForEach(KGVocabSortOption.allCases) { option in
                Button {
                    sortOption = option
                } label: {
                    Label(option.label, systemImage: option.systemImage)
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.up.arrow.down")
                Text(sortOption.label)
            }
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.secondaryText)
        }
        .accessibilityLabel("排序方式：\(sortOption.label)")
        .accessibilityHint("點兩下切換排序")
    }
}

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

                Divider()
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
            .animation(AppMotion.controlEaseOut, value: configuration.isPressed)
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
            return (.white, vocabSkin.palette.primaryText, vocabSkin.palette.primaryText)
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
