import SwiftUI

struct AppToolbarGlyphStyle {
    let iconFont: Font
    let iconColor: Color
    let badgeFont: Font
    let badgeForeground: Color
    let badgeBackground: Color
    let spacing: CGFloat
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
                        AppRoundedRect(roundness: AppRoundness.pill)
                            .fill(style.badgeBackground)
                    )
            }
        }
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
            spacing: AppSpacing.s1
        )
    }

    static func vocab(_ skin: AppSkin, tone: Color? = nil) -> AppToolbarGlyphStyle {
        .init(
            iconFont: skin.typography.iconToolbar,
            iconColor: tone ?? skin.palette.secondaryText,
            badgeFont: skin.typography.monoLabel,
            badgeForeground: .white,
            badgeBackground: tone ?? skin.palette.destructive,
            spacing: AppSpacing.s1
        )
    }
}

struct AppStateMessageStyle {
    let iconFont: Font
    let iconColor: Color
    let titleFont: Font
    let titleColor: Color
    let descriptionFont: Font
    let descriptionColor: Color
    let accentColor: Color
    let background: Color
    let border: Color
    let spacing: CGFloat
    let verticalPadding: CGFloat
    let horizontalPadding: CGFloat
    let roundness: CGFloat
}

struct AppStateMessageContent<Accessory: View>: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String?
    let customStyle: AppStateMessageStyle?
    @ViewBuilder let accessory: Accessory

    init(
        title: String,
        systemImage: String,
        description: String? = nil,
        style: AppStateMessageStyle? = nil,
        @ViewBuilder accessory: () -> Accessory = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.customStyle = style
        self.accessory = accessory()
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        VStack(alignment: .leading, spacing: style.spacing) {
            HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s2) {
                Image(systemName: systemImage)
                    .font(style.iconFont)
                    .foregroundStyle(style.iconColor)

                Text(title.localized)
                    .font(style.titleFont)
                    .foregroundStyle(style.titleColor)

                Spacer()
            }

            if let description, !description.isEmpty {
                Text(description.localized)
                    .font(style.descriptionFont)
                    .foregroundStyle(style.descriptionColor)
                    .fixedSize(horizontal: false, vertical: true)
            }

            accessory
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct AppStateMessageCard<Accessory: View>: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String?
    let customStyle: AppStateMessageStyle?
    @ViewBuilder let accessory: Accessory

    init(
        title: String,
        systemImage: String,
        description: String? = nil,
        style: AppStateMessageStyle? = nil,
        @ViewBuilder accessory: () -> Accessory = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.customStyle = style
        self.accessory = accessory()
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        AppSectionCard(padding: 0) {
            AppStateMessageContent(
                title: title,
                systemImage: systemImage,
                description: description,
                style: style
            ) {
                accessory
            }
            .padding(.horizontal, style.horizontalPadding)
            .padding(.vertical, style.verticalPadding)
        }
        .background(style.background)
        .clipShape(AppRoundedRect(roundness: style.roundness))
        .overlay(
            AppRoundedRect(roundness: style.roundness)
                .stroke(style.border, lineWidth: 1)
        )
    }
}

extension AppStateMessageStyle {
    static func themed(_ theme: AppTheme) -> AppStateMessageStyle {
        .init(
            iconFont: AppFonts.body(weight: .semibold),
            iconColor: theme.palette.accent,
            titleFont: AppFonts.body(weight: .semibold),
            titleColor: theme.palette.primaryText,
            descriptionFont: AppFonts.caption(),
            descriptionColor: theme.palette.secondaryText,
            accentColor: theme.palette.accent,
            background: theme.palette.cardBackground,
            border: theme.palette.cardBorder.opacity(0.9),
            spacing: AppSpacing.s2,
            verticalPadding: 12,
            horizontalPadding: 14,
            roundness: AppRoundness.card
        )
    }

    static func vocab(_ skin: AppSkin) -> AppStateMessageStyle {
        .init(
            iconFont: skin.typography.iconSmall,
            iconColor: skin.palette.accent,
            titleFont: skin.typography.body.weight(.semibold),
            titleColor: skin.palette.primaryText,
            descriptionFont: skin.typography.caption,
            descriptionColor: skin.palette.secondaryText,
            accentColor: skin.palette.accent,
            background: skin.palette.cardBackground,
            border: skin.palette.cardBorder,
            spacing: AppSpacing.s2,
            verticalPadding: 12,
            horizontalPadding: 14,
            // 與上面的 themed() 同一個 token：兩個 factory 是同一個元件的兩種上色，
            // 圓度沒有理由分家。舊值 6 vs 8 差 1.33×，若照舊值機械對應會變成
            // control(.30) vs card(.15) 差 2×，反而把原本的小落差放大。
            roundness: skin.roundness.card
        )
    }
}

#Preview("AppToolbarComponents") {
    AppThemeContainer {
        AppToolbarComponentsPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppToolbarComponentsPreview: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s5) {
            HStack(spacing: AppSpacing.s4) {
                AppToolbarGlyph(systemImage: "arrow.clockwise", style: .themed(appTheme))
                AppToolbarGlyph(systemImage: "tray.full", badge: "7", style: .themed(appTheme))
            }

            AppStateMessageCard(
                title: "狀態訊息",
                systemImage: "info.circle",
                description: "這是一則狀態說明文字。"
            )
        }
        .padding()
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
