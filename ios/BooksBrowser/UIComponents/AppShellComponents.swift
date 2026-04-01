import SwiftUI

enum AppShellMetrics {
    static let pageHorizontalPadding = AppMetrics.sectionInset
    static let pageTopPadding: CGFloat = 12
    static let pageBottomPadding: CGFloat = 48
    static let sectionSpacing: CGFloat = 24
    static let cardCornerRadius = AppMetrics.cornerRadiusMedium
    static let cardShadowRadius: CGFloat = 6
    static let cardShadowY: CGFloat = 2
    static let cardPadding: CGFloat = 18
    static let toolbarBadgeHorizontalPadding: CGFloat = 5
    static let toolbarBadgeVerticalPadding: CGFloat = 2
}

struct AppSectionCardStyle {
    let background: Color
    let border: Color
    let shadow: Color
    let cornerRadius: CGFloat
    let borderOpacity: Double
    let shadowRadius: CGFloat
    let shadowY: CGFloat
}

struct AppSectionTextStyle {
    let font: Font
    let color: Color
}

struct AppSectionCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    let customStyle: AppSectionCardStyle?
    @ViewBuilder let content: Content

    init(
        padding: CGFloat = AppShellMetrics.cardPadding,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.customStyle = nil
        self.content = content()
    }

    init(
        padding: CGFloat = AppShellMetrics.cardPadding,
        style: AppSectionCardStyle,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.customStyle = style
        self.content = content()
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        content
            .padding(padding)
            .background(style.background)
            .clipShape(
                RoundedRectangle(
                    cornerRadius: style.cornerRadius,
                    style: .continuous
                )
            )
            .overlay(
                RoundedRectangle(
                    cornerRadius: style.cornerRadius,
                    style: .continuous
                )
                .stroke(style.border.opacity(style.borderOpacity), lineWidth: 1)
            )
            .shadow(color: style.shadow, radius: style.shadowRadius, y: style.shadowY)
    }
}

struct AppSectionHeader: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let customStyle: AppSectionTextStyle?

    init(title: String, systemImage: String, style: AppSectionTextStyle? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .header(appTheme)
        Label(title.localized, systemImage: systemImage)
            .font(style.font)
            .foregroundStyle(style.color)
            .padding(.leading, AppMetrics.spacingExtraSmall)
    }
}

struct AppSectionFooter: View {
    @Environment(\.appTheme) private var appTheme
    let text: String
    let customStyle: AppSectionTextStyle?

    init(text: String, style: AppSectionTextStyle? = nil) {
        self.text = text
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .footer(appTheme)
        Text(text.localized)
            .font(style.font)
            .foregroundStyle(style.color)
            .lineSpacing(3)
            .padding(.horizontal, AppMetrics.spacingExtraSmall)
    }
}

struct AppSearchFieldStyle {
    let iconFont: Font
    let iconColor: Color
    let textFont: Font
    let textColor: Color
    let clearButtonFont: Font
    let clearButtonColor: Color
    let background: Color
    let border: Color
    let cornerRadius: CGFloat
}

struct AppSearchField: View {
    @Binding var text: String
    let prompt: String
    let style: AppSearchFieldStyle

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)

            TextField(prompt.localized, text: $text)
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .autocorrectionDisabled()
                .font(style.textFont)
                .foregroundStyle(style.textColor)

            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(style.clearButtonFont)
                        .foregroundStyle(style.clearButtonColor)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(
            RoundedRectangle(cornerRadius: style.cornerRadius, style: .continuous)
                .fill(style.background)
        )
        .overlay(
            RoundedRectangle(cornerRadius: style.cornerRadius, style: .continuous)
                .stroke(style.border, lineWidth: 1)
        )
    }
}

struct AppKeyValueRowStyle {
    let iconFont: Font
    let iconColor: Color
    let labelFont: Font
    let labelColor: Color
    let horizontalPadding: CGFloat
    let verticalPadding: CGFloat
    let minHeight: CGFloat
    let iconWidth: CGFloat
    let spacing: CGFloat
}

struct AppKeyValueRow<Content: View>: View {
    let icon: String
    let label: String
    let style: AppKeyValueRowStyle
    let content: Content

    init(
        icon: String,
        label: String,
        style: AppKeyValueRowStyle,
        @ViewBuilder content: () -> Content
    ) {
        self.icon = icon
        self.label = label
        self.style = style
        self.content = content()
    }

    var body: some View {
        HStack(spacing: style.spacing) {
            Image(systemName: icon)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)
                .frame(width: style.iconWidth, alignment: .center)

            Text(label.localized)
                .font(style.labelFont)
                .foregroundStyle(style.labelColor)

            Spacer()

            content
        }
        .padding(.horizontal, style.horizontalPadding)
        .padding(.vertical, style.verticalPadding)
        .frame(minHeight: style.minHeight)
    }
}

struct AppSettingsDivider: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let leadingInset: CGFloat

    init(leadingInset: CGFloat = 50) {
        self.leadingInset = leadingInset
    }

    var body: some View {
        Rectangle()
            .fill(vocabSkin.palette.divider)
            .frame(height: AppMetrics.dividerStandard)
            .padding(.leading, leadingInset)
    }
}

struct AppSectionBlock<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let eyebrow: String?
    @ViewBuilder let content: Content

    init(
        title: String,
        eyebrow: String? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.eyebrow = eyebrow
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                if let eyebrow, !eyebrow.isEmpty {
                    Text(eyebrow)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                        .tracking(1.0)
                }
                Text(title.localized)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
            .padding(.horizontal, vocabSkin.metrics.readerSettingsHeaderMicroInset)

            AppSectionCard(padding: vocabSkin.metrics.readerSettingsCardPadding, style: .settings(vocabSkin)) {
                content
            }
        }
    }
}
