import SwiftUI

// MARK: - Shared Section Helpers (internal，供各 Section 檔案使用)

struct SettingsSectionHeader: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    let icon: String

    var body: some View {
        AppSectionHeader(
            title: title,
            systemImage: icon,
            style: .init(
                font: appSkin.typography.caption,
                color: appSkin.palette.secondaryText
            )
        )
    }
}

struct SettingsSectionFooter: View {
    @Environment(\.appSkin) private var appSkin
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        AppSectionFooter(
            text: text,
            style: .init(
                font: appSkin.typography.caption,
                color: appSkin.palette.tertiaryText
            )
        )
    }
}

typealias SettingsDivider = AppSettingsDivider

struct SettingsTrailingChevronIcon: View {
    @Environment(\.appSkin) private var appSkin

    var body: some View {
        Image(systemName: "chevron.right")
            .font(appSkin.typography.iconTiny)
            .foregroundStyle(appSkin.palette.tertiaryText)
    }
}

struct SettingsDisclosureValue: View {
    @Environment(\.appSkin) private var appSkin
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Text(text)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)
            SettingsTrailingChevronIcon()
        }
    }
}

struct SettingsMenuValue: View {
    @Environment(\.appSkin) private var appSkin
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Text(text)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)
            Image(systemName: "chevron.up.chevron.down")
                .font(appSkin.typography.iconTiny)
                .foregroundStyle(appSkin.palette.tertiaryText)
        }
    }
}

struct SettingsTitleSubtitleStack: View {
    @Environment(\.appSkin) private var appSkin
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
                    .font(appSkin.typography.caption)
                    .foregroundStyle(subtitleColor)
                    .lineLimit(subtitleLineLimit)
            }
        }
    }
}

struct SettingsStatusBadge: View {
    @Environment(\.appSkin) private var appSkin
    let text: String
    let tone: Color

    var body: some View {
        Text(text)
            .font(appSkin.typography.monoLabel)
            .foregroundStyle(tone)
            .padding(.horizontal, appSkin.spacing.badgeHorizontalPadding)
            .padding(.vertical, appSkin.spacing.chipVerticalPadding)
            .background(tone.opacity(0.12))
            .clipShape(Capsule())
    }
}

struct SettingsStatusValue: View {
    @Environment(\.appSkin) private var appSkin
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
            .font(appSkin.typography.caption)
            .foregroundStyle(color)
            .lineLimit(lineLimit)
            .multilineTextAlignment(alignment)
    }
}

struct SettingsStatusSummaryValue: View {
    @Environment(\.appSkin) private var appSkin
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
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)
                .lineLimit(1)
        }
    }
}
