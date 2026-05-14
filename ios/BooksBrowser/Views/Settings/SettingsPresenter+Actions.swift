import SwiftUI

// MARK: - Navigation Rows, Card Navigation, Buttons, Subscription Components, Selection

struct SettingsNavigationRow<Trailing: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
            AppKeyValueRow(icon: icon, label: label, style: .settings(vocabSkin)) {
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

struct SettingsCompactActionButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let action: () -> Void
    let isEnabled: Bool

    init(title: String, isEnabled: Bool = true, action: @escaping () -> Void) {
        self.title = title
        self.action = action
        self.isEnabled = isEnabled
    }

    var body: some View {
        Button(title, action: action)
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(isEnabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )
            .buttonStyle(.plain)
            .disabled(!isEnabled)
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
    let subtitle: String?
    let detail: String?
    let titleFont: Font

    init(title: String, subtitle: String? = nil, detail: String? = nil, titleFont: Font) {
        self.title = title
        self.subtitle = subtitle
        self.detail = detail
        self.titleFont = titleFont
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
            Text(title)
                .font(titleFont)
                .foregroundStyle(vocabSkin.palette.primaryText)

            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .lineSpacing(3)
            }

            if let detail, !detail.isEmpty {
                Text(detail)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .lineSpacing(3)
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

/// Paywall Free vs Pro 對照表的單行資料
struct SettingsPlanComparisonRow: Identifiable {
    enum Mark {
        case check
        case cross
        case label(String)
    }

    let title: String
    let freeMark: Mark
    let proMark: Mark

    var id: String { title }
}

/// Paywall 用 Free vs Pro 功能對照表
///
/// 用途：取代「只列 Pro 有什麼」的單欄 bullet list，直接呈現兩欄差異，
/// 提升決策資訊密度（業界做法：Notion / Linear / Cursor 訂閱頁）。
struct SettingsPlanComparisonTable: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let rows: [SettingsPlanComparisonRow]

    var body: some View {
        SettingsFeaturePanel(borderTone: vocabSkin.palette.cardBorder) {
            VStack(spacing: 0) {
                headerRow

                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    Rectangle()
                        .fill(vocabSkin.palette.divider.opacity(0.5))
                        .frame(height: 1)
                        .padding(.vertical, vocabSkin.spacing.microGap)

                    comparisonRow(row, isLast: index == rows.count - 1)
                }
            }
        }
    }

    private var headerRow: some View {
        HStack(spacing: vocabSkin.spacing.controlGap) {
            Text("功能".localized)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text("Free")
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .frame(width: 52, alignment: .center)

            Text("Pro")
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.accent)
                .frame(width: 52, alignment: .center)
        }
    }

    private func comparisonRow(_ row: SettingsPlanComparisonRow, isLast _: Bool) -> some View {
        HStack(spacing: vocabSkin.spacing.controlGap) {
            Text(row.title)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            markView(row.freeMark, isProColumn: false)
                .frame(width: 52, alignment: .center)

            markView(row.proMark, isProColumn: true)
                .frame(width: 52, alignment: .center)
        }
    }

    @ViewBuilder
    private func markView(_ mark: SettingsPlanComparisonRow.Mark, isProColumn: Bool) -> some View {
        switch mark {
        case .check:
            Image(systemName: "checkmark.circle.fill")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(isProColumn ? vocabSkin.palette.accent : vocabSkin.palette.success)
        case .cross:
            Image(systemName: "minus")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        case .label(let text):
            Text(text)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(isProColumn ? vocabSkin.palette.accent : vocabSkin.palette.secondaryText)
        }
    }
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
