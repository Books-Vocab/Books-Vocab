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
}
