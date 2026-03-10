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
                .textInputAutocapitalization(.never)
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
            .frame(height: 1)
            .padding(.leading, leadingInset)
    }
}

struct AppSectionBlock<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let eyebrow: String
    @ViewBuilder let content: Content

    init(
        title: String,
        eyebrow: String,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.eyebrow = eyebrow
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(eyebrow)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .tracking(1.0)
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

extension AppSectionCardStyle {
    static func themed(_ theme: AppTheme) -> AppSectionCardStyle {
        .init(
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder,
            shadow: theme.palette.shadow,
            cornerRadius: AppShellMetrics.cardCornerRadius,
            borderOpacity: 0.7,
            shadowRadius: AppShellMetrics.cardShadowRadius,
            shadowY: AppShellMetrics.cardShadowY
        )
    }

    static func vocab(_ skin: VocabSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            shadow: skin.palette.shadow,
            cornerRadius: skin.radii.card,
            borderOpacity: 0.7,
            shadowRadius: 6,
            shadowY: 2
        )
    }

    static func settings(_ skin: VocabSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            shadow: .clear,
            cornerRadius: skin.radii.card,
            borderOpacity: 1,
            shadowRadius: 0,
            shadowY: 0
        )
    }
}

extension AppSectionTextStyle {
    static func header(_ theme: AppTheme) -> AppSectionTextStyle {
        .init(font: AppFonts.caption(weight: .semibold), color: theme.palette.secondaryText)
    }

    static func footer(_ theme: AppTheme) -> AppSectionTextStyle {
        .init(font: AppFonts.caption(), color: theme.palette.tertiaryText)
    }
}

extension AppSearchFieldStyle {
    static func themed(_ theme: AppTheme) -> AppSearchFieldStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            iconColor: theme.palette.tertiaryText,
            textFont: AppFonts.body(),
            textColor: theme.palette.primaryText,
            clearButtonFont: AppFonts.caption(weight: .medium),
            clearButtonColor: theme.palette.quaternaryText,
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder,
            cornerRadius: AppMetrics.cornerRadiusMedium - 2
        )
    }

    static func vocab(_ skin: VocabSkin) -> AppSearchFieldStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.tertiaryText,
            textFont: skin.typography.body,
            textColor: skin.palette.primaryText,
            clearButtonFont: skin.typography.iconMedium,
            clearButtonColor: skin.palette.quaternaryText,
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            cornerRadius: skin.radii.control
        )
    }
}

extension AppKeyValueRowStyle {
    static func themed(_ theme: AppTheme) -> AppKeyValueRowStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            iconColor: theme.palette.secondaryText,
            labelFont: AppFonts.body(),
            labelColor: theme.palette.primaryText,
            horizontalPadding: AppShellMetrics.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: 12
        )
    }

    static func vocab(_ skin: VocabSkin) -> AppKeyValueRowStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.secondaryText,
            labelFont: skin.typography.body,
            labelColor: skin.palette.primaryText,
            horizontalPadding: skin.spacing.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: 12
        )
    }

    static func settings(_ skin: VocabSkin) -> AppKeyValueRowStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.secondaryText,
            labelFont: skin.typography.body,
            labelColor: skin.palette.primaryText,
            horizontalPadding: skin.spacing.cardPadding,
            verticalPadding: 13,
            minHeight: 50,
            iconWidth: 22,
            spacing: 12
        )
    }
}

#Preview("Shared Shell / App") {
    AppThemeContainer {
        AppShellPreview(variant: .app)
    }
}

#Preview("Shared Shell / Vocab") {
    AppThemeContainer {
        AppShellPreview(variant: .vocab)
    }
}

#Preview("Shared Shell / Settings") {
    AppThemeContainer {
        AppShellPreview(variant: .settings)
    }
}

private enum AppShellPreviewVariant {
    case app
    case vocab
    case settings
}

private struct AppShellPreview: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin
    let variant: AppShellPreviewVariant
    @State private var selectedTab = 0
    @State private var searchText = "mystery"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
                previewHeader
                previewBody
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(previewBackground.ignoresSafeArea())
    }

    private var previewBackground: Color {
        switch variant {
        case .app:
            return appTheme.palette.pageBackground
        case .vocab, .settings:
            return vocabSkin.palette.pageBackground
        }
    }

    private var previewHeader: some View {
        switch variant {
        case .app:
            return AnyView(AppSectionHeader(title: "Shell", systemImage: "square.grid.2x2"))
        case .vocab:
            return AnyView(
                AppSectionHeader(
                    title: "Vocabulary Shell",
                    systemImage: "character.book.closed",
                    style: .init(
                        font: vocabSkin.typography.captionStrong,
                        color: vocabSkin.palette.secondaryText
                    )
                )
            )
        case .settings:
            return AnyView(
                AppSectionHeader(
                    title: "Settings Shell",
                    systemImage: "gearshape",
                    style: .init(
                        font: vocabSkin.typography.captionStrong,
                        color: vocabSkin.palette.secondaryText
                    )
                )
            )
        }
    }

    @ViewBuilder
    private var previewBody: some View {
        switch variant {
        case .app:
            previewShellCard(
                cardStyle: .themed(appTheme),
                tabStyle: .themed(appTheme),
                searchStyle: .themed(appTheme),
                keyValueStyle: .themed(appTheme),
                toolbarStyle: .themed(appTheme),
                valueColor: appTheme.palette.secondaryText,
                emptyCardStyle: .themed(appTheme),
                emptyContentStyle: .themed(appTheme),
                actionTitle: "主要操作",
                actionTone: .primary
            )
        case .vocab:
            previewShellCard(
                cardStyle: .vocab(vocabSkin),
                tabStyle: .vocab(vocabSkin),
                searchStyle: .vocab(vocabSkin),
                keyValueStyle: .vocab(vocabSkin),
                toolbarStyle: .vocab(vocabSkin),
                valueColor: vocabSkin.palette.secondaryText,
                emptyCardStyle: .vocab(vocabSkin),
                emptyContentStyle: .vocab(vocabSkin),
                actionTitle: "開始複習",
                actionTone: .neutral
            )
        case .settings:
            previewSettingsCard
        }
    }

    private func previewShellCard(
        cardStyle: AppSectionCardStyle,
        tabStyle: AppTabSelectorStyle,
        searchStyle: AppSearchFieldStyle,
        keyValueStyle: AppKeyValueRowStyle,
        toolbarStyle: AppToolbarGlyphStyle,
        valueColor: Color,
        emptyCardStyle: AppSectionCardStyle,
        emptyContentStyle: AppEmptyStateStyle,
        actionTitle: String,
        actionTone: AppActionTone
    ) -> some View {
        VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
            AppSectionCard(style: cardStyle) {
                VStack(alignment: .leading, spacing: 16) {
                    AppTabSelector(
                        options: [
                            .init(id: 0, title: "書庫", count: 12, systemImage: "books.vertical"),
                            .init(id: 1, title: "生詞庫", count: 248, systemImage: "character.book.closed"),
                            .init(id: 2, title: "設定", systemImage: "gearshape")
                        ],
                        selection: $selectedTab,
                        style: tabStyle
                    )

                    AppSearchField(
                        text: $searchText,
                        prompt: "搜尋",
                        style: searchStyle
                    )

                    AppKeyValueRow(
                        icon: "server.rack",
                        label: "伺服器",
                        style: keyValueStyle
                    ) {
                        Text("wordnexus.lol")
                            .font(AppFonts.monoNumbers(size: 12))
                            .foregroundStyle(valueColor)
                    }
                }
            }

            AppEmptyStateCard(
                title: "尚無內容",
                systemImage: "tray",
                description: "這個 preview 用來保護 shared shell 元件的基本輸出。",
                cardStyle: emptyCardStyle,
                contentStyle: emptyContentStyle
            )

            HStack(spacing: 12) {
                AppToolbarGlyph(systemImage: "arrow.clockwise", style: toolbarStyle)
                AppToolbarGlyph(systemImage: "tray.full", badge: "7", style: toolbarStyle)
            }

            Button(actionTitle) {}
                .buttonStyle(.appAction(actionTone))
        }
    }

    private var previewSettingsCard: some View {
        VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
            AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
                VStack(spacing: 0) {
                    AppKeyValueRow(
                        icon: "person.circle",
                        label: "帳號",
                        style: .settings(vocabSkin)
                    ) {
                        Text("reader@example.com")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }

                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)
                        .padding(.leading, 50)

                    AppKeyValueRow(
                        icon: "server.rack",
                        label: "伺服器",
                        style: .settings(vocabSkin)
                    ) {
                        Text("wordnexus.lol")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }
            }

            Button("登出帳號") {}
                .buttonStyle(.appAction(.destructive))

            AppSectionFooter(
                text: "Settings variant 會保護 shared row 與 card 在無陰影設定皮膚下的輸出。",
                style: .init(
                    font: vocabSkin.typography.caption,
                    color: vocabSkin.palette.tertiaryText
                )
            )
        }
    }
}
