import SwiftUI

// MARK: - Shared Section Helpers (internal，供各 Section 檔案使用)

struct SettingsSectionHeader: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let icon: String

    var body: some View {
        AppSectionHeader(
            title: title,
            systemImage: icon,
            style: .init(
                font: vocabSkin.typography.captionStrong,
                color: vocabSkin.palette.secondaryText
            )
        )
    }
}

struct SettingsSectionFooter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        AppSectionFooter(
            text: text,
            style: .init(
                font: vocabSkin.typography.caption,
                color: vocabSkin.palette.tertiaryText
            )
        )
    }
}

typealias SettingsDivider = AppSettingsDivider

struct SettingsRow<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let icon: String
    let label: String
    let content: Content

    init(icon: String, label: String, @ViewBuilder content: () -> Content) {
        self.icon = icon
        self.label = label
        self.content = content()
    }

    var body: some View {
        AppKeyValueRow(
            icon: icon,
            label: label,
            style: .settings(vocabSkin)
        ) {
            content
        }
    }
}

struct SettingsTrailingChevronIcon: View {
    @Environment(\.vocabSkin) private var vocabSkin

    var body: some View {
        Image(systemName: "chevron.right")
            .font(vocabSkin.typography.iconTiny)
            .foregroundStyle(vocabSkin.palette.tertiaryText)
    }
}

struct SettingsDisclosureValue: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Text(text)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.secondaryText)
            SettingsTrailingChevronIcon()
        }
    }
}

struct SettingsMenuValue: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Text(text)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.secondaryText)
            Image(systemName: "chevron.up.chevron.down")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
    }
}

struct SettingsTitleSubtitleStack: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let subtitle: String?
    let titleFont: Font
    let titleColor: Color
    let subtitleColor: Color
    let subtitleLineLimit: Int?

    init(
        title: String,
        subtitle: String? = nil,
        titleFont: Font,
        titleColor: Color,
        subtitleColor: Color,
        subtitleLineLimit: Int? = 1
    ) {
        self.title = title
        self.subtitle = subtitle
        self.titleFont = titleFont
        self.titleColor = titleColor
        self.subtitleColor = subtitleColor
        self.subtitleLineLimit = subtitleLineLimit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(titleFont)
                .foregroundStyle(titleColor)
                .lineLimit(1)

            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(subtitleColor)
                    .lineLimit(subtitleLineLimit)
            }
        }
    }
}

struct SettingsStatusBadge: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String
    let tone: Color

    var body: some View {
        Text(text)
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(tone)
            .padding(.horizontal, vocabSkin.spacing.badgeHorizontalPadding)
            .padding(.vertical, vocabSkin.spacing.chipVerticalPadding)
            .background(tone.opacity(0.12))
            .clipShape(Capsule())
    }
}

struct SettingsStatusValue: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String
    let color: Color
    let lineLimit: Int?
    let alignment: TextAlignment

    init(text: String, color: Color, lineLimit: Int? = 1, alignment: TextAlignment = .trailing) {
        self.text = text
        self.color = color
        self.lineLimit = lineLimit
        self.alignment = alignment
    }

    var body: some View {
        Text(text)
            .font(vocabSkin.typography.caption)
            .foregroundStyle(color)
            .lineLimit(lineLimit)
            .multilineTextAlignment(alignment)
    }
}

struct SettingsStatusSummaryValue: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String
    let color: Color
    let showsIndicator: Bool

    init(text: String, color: Color, showsIndicator: Bool = true) {
        self.text = text
        self.color = color
        self.showsIndicator = showsIndicator
    }

    var body: some View {
        HStack(spacing: 6) {
            if showsIndicator {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
            }

            Text(text)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .lineLimit(1)
        }
    }
}

struct SettingsNavigationRow<Trailing: View>: View {
    let icon: String
    let label: String
    let action: () -> Void
    let trailing: Trailing

    init(
        icon: String,
        label: String,
        action: @escaping () -> Void,
        @ViewBuilder trailing: () -> Trailing = { EmptyView() }
    ) {
        self.icon = icon
        self.label = label
        self.action = action
        self.trailing = trailing()
    }

    var body: some View {
        Button(action: action) {
            SettingsRow(icon: icon, label: label) {
                HStack(spacing: 6) {
                    trailing
                    SettingsTrailingChevronIcon()
                }
            }
        }
        .buttonStyle(.plain)
    }
}

struct SettingsCardNavigationRow<Leading: View, Trailing: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let action: () -> Void
    let leading: Leading
    let trailing: Trailing

    init(
        action: @escaping () -> Void,
        @ViewBuilder leading: () -> Leading,
        @ViewBuilder trailing: () -> Trailing = { EmptyView() }
    ) {
        self.action = action
        self.leading = leading()
        self.trailing = trailing()
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: vocabSkin.spacing.controlGap) {
                leading

                Spacer(minLength: vocabSkin.spacing.inlineGap)

                trailing

                SettingsTrailingChevronIcon()
            }
            .padding(.horizontal, vocabSkin.spacing.cardPadding)
            .padding(.vertical, 13)
        }
        .buttonStyle(.plain)
    }
}

struct SettingsInlineInfoButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "info.circle")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }
}

struct SettingsActionRowLabel<Trailing: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let isLoading: Bool
    let trailing: Trailing

    init(
        title: String,
        systemImage: String,
        isLoading: Bool = false,
        @ViewBuilder trailing: () -> Trailing = { SettingsTrailingChevronIcon() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.isLoading = isLoading
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: vocabSkin.spacing.controlGap) {
            if isLoading {
                ProgressView()
                    .controlSize(.small)
            } else {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconMedium)
            }

            Text(title)
                .font(vocabSkin.typography.body.weight(.medium))

            Spacer()

            trailing
        }
        .foregroundStyle(vocabSkin.palette.primaryText)
        .padding(.horizontal, vocabSkin.spacing.cardPadding)
        .padding(.vertical, 13)
        .frame(minHeight: 50)
    }
}

extension SubscriptionBadgeTone {
    func color(in skin: VocabSkin) -> Color {
        switch self {
        case .neutral:
            skin.palette.secondaryText
        case .accent:
            skin.palette.accent
        case .success:
            skin.palette.success
        }
    }
}

struct SettingsFeaturePanel<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let borderTone: Color
    let content: Content

    init(borderTone: Color, @ViewBuilder content: () -> Content) {
        self.borderTone = borderTone
        self.content = content()
    }

    var body: some View {
        content
            .padding(vocabSkin.spacing.cardPadding)
            .background(vocabSkin.palette.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .stroke(borderTone, lineWidth: 1)
            )
    }
}

struct SettingsSubscriptionInfoBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let detail: String?
    let titleFont: Font

    init(title: String, detail: String? = nil, titleFont: Font) {
        self.title = title
        self.detail = detail
        self.titleFont = titleFont
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
            Text(title)
                .font(titleFont)
                .foregroundStyle(vocabSkin.palette.primaryText)

            if let detail, !detail.isEmpty {
                Text(detail)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
        }
    }
}

struct SettingsSubscriptionFeatureItem: Identifiable {
    let title: String
    let description: String?
    let icon: String
    let tone: Color

    var id: String { title }
}

struct SettingsSubscriptionFeatureList: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let borderTone: Color
    let items: [SettingsSubscriptionFeatureItem]

    var body: some View {
        SettingsFeaturePanel(borderTone: borderTone) {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                ForEach(items) { item in
                    HStack(alignment: .top, spacing: vocabSkin.spacing.controlGap) {
                        Image(systemName: item.icon)
                            .font(vocabSkin.typography.iconMedium)
                            .foregroundStyle(item.tone)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title)
                                .font(item.description == nil ? vocabSkin.typography.body : vocabSkin.typography.body.weight(.medium))
                                .foregroundStyle(vocabSkin.palette.primaryText)

                            if let description = item.description {
                                Text(description)
                                    .font(vocabSkin.typography.caption)
                                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                            }
                        }

                        Spacer()
                    }
                }
            }
        }
    }
}

struct SettingsSelectableRow<Leading: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let isSelected: Bool
    let leading: Leading

    init(isSelected: Bool, @ViewBuilder leading: () -> Leading) {
        self.isSelected = isSelected
        self.leading = leading()
    }

    var body: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            leading

            Spacer()

            if isSelected {
                Image(systemName: "checkmark")
                    .font(vocabSkin.typography.iconSmall)
                    .foregroundStyle(vocabSkin.palette.accent)
            }
        }
        .padding(.horizontal, vocabSkin.spacing.cardPadding)
        .padding(.vertical, vocabSkin.spacing.rowPadding)
        .contentShape(Rectangle())
        .background(isSelected ? vocabSkin.palette.accent.opacity(0.08) : Color.clear)
    }
}

struct SettingsSelectionTile<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let isSelected: Bool
    let content: Content

    init(isSelected: Bool, @ViewBuilder content: () -> Content) {
        self.isSelected = isSelected
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(
                        isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(0.4),
                        lineWidth: 1
                    )
            )
    }
}

struct SettingsStepperIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconMedium.weight(.medium))
                .foregroundStyle(enabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                .frame(width: 52, height: 52)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.pageBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

struct SettingsCardModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
            content
        }
    }
}

extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }

    func appSettingsButtonChrome() -> some View {
        modifier(SettingsButtonChromeModifier())
    }
}

struct SettingsButtonChromeModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .padding(vocabSkin.spacing.cardPadding)
            .background(vocabSkin.palette.pageBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )
    }
}
