//
//  AppSurface.swift
//  BooksBrowser
//
//  共用的卡片、標籤與按鈕樣式。
//  設計語言：Mochi 式極簡知識美學 — 純白紙張 + 微投影 + Ghost 按鈕
//

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

enum AppActionTone {
    case primary
    case neutral
    case outline
    case destructive
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

struct AppToolbarGlyphStyle {
    let iconFont: Font
    let iconColor: Color
    let badgeFont: Font
    let badgeForeground: Color
    let badgeBackground: Color
    let spacing: CGFloat
}

struct AppSectionTextStyle {
    let font: Font
    let color: Color
}

struct AppEmptyStateStyle {
    let iconFont: Font
    let iconColor: Color
    let titleFont: Font
    let titleColor: Color
    let descriptionFont: Font
    let descriptionColor: Color
    let spacing: CGFloat
    let verticalPadding: CGFloat
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
            .shadow(
                color: style.shadow,
                radius: style.shadowRadius,
                y: style.shadowY
            )
    }
}

struct AppToolbarGlyph: View {
    @Environment(\.appTheme) private var appTheme
    let systemImage: String
    let badge: String?
    let customStyle: AppToolbarGlyphStyle?
    let tone: Color?

    init(systemImage: String, badge: String? = nil, tone: Color? = nil) {
        self.systemImage = systemImage
        self.badge = badge
        self.customStyle = nil
        self.tone = tone
    }

    init(systemImage: String, badge: String? = nil, style: AppToolbarGlyphStyle) {
        self.systemImage = systemImage
        self.badge = badge
        self.customStyle = style
        self.tone = nil
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme, tone: tone)
        HStack(spacing: style.spacing) {
            Image(systemName: systemImage)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)

            if let badge {
                Text(badge)
                    .font(style.badgeFont)
                    .foregroundStyle(style.badgeForeground)
                    .padding(.horizontal, AppShellMetrics.toolbarBadgeHorizontalPadding)
                    .padding(.vertical, AppShellMetrics.toolbarBadgeVerticalPadding)
                    .background(
                        RoundedRectangle(
                            cornerRadius: AppMetrics.cornerRadiusSmall - 1,
                            style: .continuous
                        )
                        .fill(style.badgeBackground)
                    )
            }
        }
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

struct AppEmptyStateContent: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String
    let customStyle: AppEmptyStateStyle?

    init(title: String, systemImage: String, description: String, style: AppEmptyStateStyle? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        VStack(spacing: style.spacing) {
            Image(systemName: systemImage)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)

            Text(title.localized)
                .font(style.titleFont)
                .foregroundStyle(style.titleColor)

            Text(description.localized)
                .font(style.descriptionFont)
                .foregroundStyle(style.descriptionColor)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }
}

struct AppEmptyStateCard: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String
    let customCardStyle: AppSectionCardStyle?
    let customContentStyle: AppEmptyStateStyle?

    init(
        title: String,
        systemImage: String,
        description: String,
        cardStyle: AppSectionCardStyle? = nil,
        contentStyle: AppEmptyStateStyle? = nil
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.customCardStyle = cardStyle
        self.customContentStyle = contentStyle
    }

    var body: some View {
        let cardStyle = customCardStyle ?? .themed(appTheme)
        let contentStyle = customContentStyle ?? .themed(appTheme)

        AppSectionCard(style: cardStyle) {
            AppEmptyStateContent(
                title: title,
                systemImage: systemImage,
                description: description,
                style: contentStyle
            )
            .padding(.vertical, contentStyle.verticalPadding)
        }
    }
}

struct AppTabOption<ID: Hashable>: Identifiable, Hashable {
    let id: ID
    let title: String
    let count: Int?
    let systemImage: String?

    init(id: ID, title: String, count: Int? = nil, systemImage: String? = nil) {
        self.id = id
        self.title = title
        self.count = count
        self.systemImage = systemImage
    }
}

struct AppTabSelectorStyle {
    let iconFont: Font
    let titleFont: Font
    let countFont: Font
    let iconSelectedColor: Color
    let iconUnselectedColor: Color
    let textSelectedColor: Color
    let textUnselectedColor: Color
    let countSelectedFill: Color
    let countUnselectedFill: Color
    let selectedBackground: Color
    let unselectedBackground: Color
    let selectedBorder: Color
    let unselectedBorder: Color
    let containerBackground: Color
    let controlRadius: CGFloat
    let containerRadius: CGFloat
}

struct AppTabSelector<ID: Hashable>: View {
    let options: [AppTabOption<ID>]
    @Binding var selection: ID
    let style: AppTabSelectorStyle

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options) { option in
                Button {
                    withAnimation(.easeOut(duration: 0.18)) {
                        selection = option.id
                    }
                } label: {
                    HStack(spacing: 6) {
                        if let systemImage = option.systemImage {
                            Image(systemName: systemImage)
                                .font(style.iconFont)
                                .foregroundStyle(selection == option.id ? style.iconSelectedColor : style.iconUnselectedColor)
                                .fixedSize()
                        }

                        Text(option.title.localized)
                            .font(style.titleFont)
                            .foregroundStyle(selection == option.id ? style.textSelectedColor : style.textUnselectedColor)
                            .lineLimit(1)
                            .minimumScaleFactor(0.72)
                            .layoutPriority(1)

                        if let count = option.count {
                            Text("\(count)")
                                .font(style.countFont)
                                .minimumScaleFactor(0.7)
                                .monospacedDigit()
                                .lineLimit(1)
                                .fixedSize(horizontal: true, vertical: false)
                                .frame(minWidth: 26)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(
                                    RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusSmall - 1, style: .continuous)
                                        .fill(selection == option.id ? style.countSelectedFill : style.countUnselectedFill)
                                )
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: style.controlRadius, style: .continuous)
                            .fill(selection == option.id ? style.selectedBackground : style.unselectedBackground)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: style.controlRadius, style: .continuous)
                            .stroke(selection == option.id ? style.selectedBorder : style.unselectedBorder, lineWidth: 1)
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(
            RoundedRectangle(cornerRadius: style.containerRadius, style: .continuous)
                .fill(style.containerBackground)
        )
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

struct AppActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var appTheme
    let tone: AppActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette

        configuration.label
            .font(AppFonts.subhead(weight: .semibold))
            .foregroundStyle(palette.foreground)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            .background(
                RoundedRectangle(
                    cornerRadius: AppMetrics.cornerRadiusMedium,
                    style: .continuous
                )
                .fill(palette.background)
            )
            .overlay(
                RoundedRectangle(
                    cornerRadius: AppMetrics.cornerRadiusMedium,
                    style: .continuous
                )
                .stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.992 : 1)
            .animation(.easeOut(duration: 0.14), value: configuration.isPressed)
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return (.white, appTheme.palette.primaryText, appTheme.palette.primaryText)
        case .neutral:
            return (
                appTheme.palette.primaryText,
                appTheme.palette.cardBackground,
                appTheme.palette.cardBorder
            )
        case .outline:
            return (
                appTheme.palette.primaryText,
                .clear,
                appTheme.palette.secondaryText.opacity(0.3)
            )
        case .destructive:
            return (
                appTheme.palette.destructive,
                appTheme.palette.destructive.opacity(0.10),
                appTheme.palette.destructive.opacity(0.22)
            )
        }
    }
}

extension ButtonStyle where Self == AppActionButtonStyle {
    static func appAction(_ tone: AppActionTone = .primary) -> AppActionButtonStyle {
        AppActionButtonStyle(tone: tone)
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
}

extension AppToolbarGlyphStyle {
    static func themed(_ theme: AppTheme, tone: Color? = nil) -> AppToolbarGlyphStyle {
        .init(
            iconFont: AppFonts.caption(weight: .medium),
            iconColor: tone ?? theme.palette.secondaryText,
            badgeFont: AppFonts.monoNumbers(size: 10),
            badgeForeground: .white,
            badgeBackground: tone ?? theme.palette.destructive,
            spacing: AppMetrics.spacingExtraSmall
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

extension AppEmptyStateStyle {
    static func themed(_ theme: AppTheme) -> AppEmptyStateStyle {
        .init(
            iconFont: AppFonts.hero(weight: .light),
            iconColor: theme.palette.tertiaryText,
            titleFont: AppFonts.h2(weight: .semibold),
            titleColor: theme.palette.primaryText,
            descriptionFont: AppFonts.body(),
            descriptionColor: theme.palette.secondaryText,
            spacing: 14,
            verticalPadding: 12
        )
    }

    static func bookshelf(_ theme: AppTheme) -> AppEmptyStateStyle {
        .init(
            iconFont: .system(size: 48, weight: .ultraLight),
            iconColor: theme.palette.quaternaryText,
            titleFont: AppFonts.subhead(weight: .medium),
            titleColor: theme.palette.secondaryText,
            descriptionFont: AppFonts.caption(),
            descriptionColor: theme.palette.tertiaryText,
            spacing: 6,
            verticalPadding: 0
        )
    }
}

// MARK: - AppCard (Pure White Paper)

struct AppCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    @ViewBuilder var content: Content

    init(
        padding: CGFloat = AppMetrics.spacingLarge,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background(cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous))
            .overlay(cardBorder.allowsHitTesting(false))
            .shadow(
                color: .black.opacity(AppShadows.paperFloatOpacity),
                radius: AppShadows.paperFloatRadius,
                y: AppShadows.paperFloatY
            )
    }

    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .fill(appTheme.palette.elevatedCardBackground)
    }

    private var cardBorder: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .strokeBorder(appTheme.palette.cardBorder, lineWidth: 0.5)
    }
}

// MARK: - AppTag (Minimalist)

struct AppTag: View {
    @Environment(\.colorScheme) private var colorScheme
    let text: String
    let tone: Color

    var body: some View {
        Text(text.localized)
            .font(AppFonts.caption(weight: .semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(tone.opacity(colorScheme == .dark ? 0.18 : 0.08))
            .foregroundStyle(tone)
            .clipShape(Capsule())
    }
}

// MARK: - GhostButtonStyle

/// 幽靈按鈕 — 無背景、低對比，按下時微微顯現
struct GhostButtonStyle: ButtonStyle {
    let tone: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(tone)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                Capsule()
                    .fill(tone.opacity(configuration.isPressed ? 0.08 : 0))
            )
            .opacity(configuration.isPressed ? 0.7 : 1.0)
            .animation(.easeOut(duration: 0.15), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == GhostButtonStyle {
    static func ghost(_ tone: Color) -> GhostButtonStyle {
        GhostButtonStyle(tone: tone)
    }
}

// MARK: - compatibleGlass (toolbar-only)

extension View {
    @ViewBuilder
    func compatibleGlass(
        in shape: some Shape = Capsule(),
        interactive: Bool = false
    ) -> some View {
        if #available(iOS 26.0, *) {
            let g: Glass = interactive ? .regular.interactive() : .regular
            self.glassEffect(g, in: shape)
        } else {
            self.background(
                shape.fill(.ultraThinMaterial)
                    .overlay(shape.stroke(Color.primary.opacity(0.12), lineWidth: 1))
            )
        }
    }
}
