import SwiftUI

struct AppTheme: Equatable {
    struct Palette: Equatable {
        let pageBackground: Color
        let stageBackground: Color
        let cardBackground: Color
        let elevatedCardBackground: Color
        let cardBorder: Color
        let borderStrong: Color
        let divider: Color
        let shadow: Color
        let primaryText: Color
        let secondaryText: Color
        let tertiaryText: Color
        let quaternaryText: Color
        let accent: Color
        let brandHero: Color
        let accentSubtle: Color
        let success: Color
        let successBg: Color
        let warning: Color
        let warningBg: Color
        let destructive: Color
        let destructiveBg: Color
        let info: Color
        let infoBg: Color
        let mutedFill: Color
        let scrim: Color
        let tint: Color
        // 中性半透明填充（白/黑疊加）— 由 AppSkin 等上層 skin passthrough 取用
        let overlayFill: Color
        let progressBarBackground: Color
        let buttonIdleFill: Color
        let buttonPressedFill: Color
    }

    let colorScheme: ColorScheme
    let palette: Palette

    // Notion-inspired light：純白卡片 + 暖近白頁面，靠 border 分層而非重陰影。
    static let light = AppTheme(
        colorScheme: .light,
        palette: .init(
            pageBackground: Color(red: 0.969, green: 0.965, blue: 0.953), // #F7F6F3
            stageBackground: Color(red: 0.984, green: 0.980, blue: 0.973), // #FBFAF8
            cardBackground: Color.white,
            elevatedCardBackground: Color.white,
            cardBorder: Color.black.opacity(0.09),
            borderStrong: Color.black.opacity(0.16),
            divider: Color.black.opacity(0.06),
            shadow: Color.black.opacity(0.04),
            primaryText: Color(red: 0.216, green: 0.208, blue: 0.184),     // #37352F ~11:1
            secondaryText: Color(red: 0.420, green: 0.416, blue: 0.396),   // #6B6A65 ~5:1
            tertiaryText: Color(red: 0.541, green: 0.537, blue: 0.514),    // #8A8983 ~3.2:1 metadata
            quaternaryText: Color(red: 0.608, green: 0.604, blue: 0.576),  // #9B9A93 ~2.6:1 decorative
            accent: AppColors.accentLight,
            brandHero: AppColors.brandHeroLight,
            accentSubtle: AppColors.accentLight.opacity(0.12),
            success: AppColors.savedLight,
            successBg: AppColors.savedLight.opacity(0.10),
            warning: AppColors.warning(.light),
            warningBg: AppColors.warning(.light).opacity(0.10),
            destructive: AppColors.destructiveLight,
            destructiveBg: AppColors.destructiveLight.opacity(0.10),
            info: AppColors.infoLight,
            infoBg: AppColors.infoLight.opacity(0.10),
            mutedFill: Color.black.opacity(0.04),
            scrim: Color.black.opacity(0.20),
            tint: AppColors.tintLight,
            overlayFill: Color.white.opacity(0.12),
            progressBarBackground: Color.black.opacity(0.07),
            buttonIdleFill: Color.black.opacity(0.06),
            buttonPressedFill: Color.black.opacity(0.10)
        )
    )

    // Notion-inspired dark：中性深灰階（無 indigo tint），#191919 頁面 / #2C2C2C 卡片。
    static let dark = AppTheme(
        colorScheme: .dark,
        palette: .init(
            pageBackground: Color(red: 0.098, green: 0.098, blue: 0.098),  // #191919
            stageBackground: Color(red: 0.122, green: 0.122, blue: 0.122), // #1F1F1F
            cardBackground: Color(red: 0.173, green: 0.173, blue: 0.173),  // #2C2C2C
            elevatedCardBackground: Color(red: 0.216, green: 0.216, blue: 0.216), // #373737
            cardBorder: Color.white.opacity(0.094),
            borderStrong: Color.white.opacity(0.18),
            divider: Color.white.opacity(0.08),
            shadow: Color.black.opacity(0.34),
            primaryText: Color(red: 0.902, green: 0.902, blue: 0.890),     // #E6E6E3 ~13:1
            secondaryText: Color(red: 0.702, green: 0.702, blue: 0.682),   // #B3B3AE ~7.8:1
            tertiaryText: Color(red: 0.549, green: 0.549, blue: 0.529),    // #8C8C87 ~4.9:1
            quaternaryText: Color(red: 0.431, green: 0.431, blue: 0.412),  // #6E6E69 ~3.2:1 decorative
            accent: AppColors.accentDark,
            brandHero: AppColors.brandHeroDark,
            accentSubtle: AppColors.accentDark.opacity(0.18),
            success: AppColors.savedDark,
            successBg: AppColors.savedDark.opacity(0.14),
            warning: AppColors.warning(.dark),
            warningBg: AppColors.warning(.dark).opacity(0.14),
            destructive: AppColors.destructive(.dark),
            destructiveBg: AppColors.destructive(.dark).opacity(0.14),
            info: AppColors.infoDark,
            infoBg: AppColors.infoDark.opacity(0.14),
            mutedFill: Color.white.opacity(0.07),
            scrim: Color.black.opacity(0.42),
            // tint 走灰階 chrome (tintDark = primaryText.dark)，奶黃 brandHero
            // 保留給 CTA — Phase 1c 拍板：chrome ≠ CTA。
            tint: AppColors.tintDark,
            overlayFill: Color.white.opacity(0.15),
            progressBarBackground: Color.white.opacity(0.10),
            buttonIdleFill: Color.white.opacity(0.10),
            buttonPressedFill: Color.white.opacity(0.16)
        )
    )

    static let sepia = AppTheme(
        colorScheme: .light,
        palette: .init(
            pageBackground: Color(red: 0.96, green: 0.945, blue: 0.92),
            stageBackground: Color(red: 0.97, green: 0.958, blue: 0.935),
            cardBackground: Color(red: 0.985, green: 0.975, blue: 0.955),
            elevatedCardBackground: Color(red: 0.99, green: 0.98, blue: 0.96),
            cardBorder: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.12),
            borderStrong: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.24),
            divider: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.08),
            shadow: Color(red: 0.30, green: 0.26, blue: 0.20).opacity(0.06),
            primaryText: Color(red: 0.22, green: 0.20, blue: 0.17),
            secondaryText: Color(red: 0.46, green: 0.43, blue: 0.38),
            tertiaryText: Color(red: 0.50, green: 0.47, blue: 0.42),
            quaternaryText: Color(red: 0.60, green: 0.57, blue: 0.52),
            accent: AppColors.accentLight,
            brandHero: AppColors.brandHeroLight,
            accentSubtle: AppColors.accentLight.opacity(0.12),
            success: AppColors.savedLight,
            successBg: AppColors.savedLight.opacity(0.10),
            warning: AppColors.warning(.light),
            warningBg: AppColors.warning(.light).opacity(0.10),
            destructive: AppColors.destructiveLight,
            destructiveBg: AppColors.destructiveLight.opacity(0.10),
            info: AppColors.infoLight,
            infoBg: AppColors.infoLight.opacity(0.10),
            mutedFill: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.06),
            scrim: Color(red: 0.30, green: 0.26, blue: 0.20).opacity(0.20),
            tint: AppColors.tintLight,
            // sepia 沿用 light 的中性 fill（與 themed() 既有行為一致：sepia.colorScheme == .light）
            overlayFill: Color.white.opacity(0.12),
            progressBarBackground: Color.black.opacity(0.07),
            buttonIdleFill: Color.black.opacity(0.07),
            buttonPressedFill: Color.black.opacity(0.12)
        )
    )

    static func resolve(for colorScheme: ColorScheme) -> AppTheme {
        colorScheme == .dark ? .dark : .light
    }

    static func resolve(for mode: AppAppearanceMode, systemColorScheme: ColorScheme) -> AppTheme {
        switch mode {
        case .system: return systemColorScheme == .dark ? .dark : .light
        case .light: return .light
        case .sepia: return .sepia
        case .dark: return .dark
        }
    }
}

private struct AppThemeEnvironmentKey: EnvironmentKey {
    static let defaultValue = AppTheme.light
}

extension EnvironmentValues {
    var appTheme: AppTheme {
        get { self[AppThemeEnvironmentKey.self] }
        set { self[AppThemeEnvironmentKey.self] = newValue }
    }
}

extension View {
    func appTheme(_ theme: AppTheme) -> some View {
        environment(\.appTheme, theme)
    }
}

struct AppThemeContainer<Content: View>: View {
    @Environment(\.colorScheme) private var colorScheme
    @EnvironmentObject private var appearanceStore: AppAppearanceStore
    @State private var fontTracker = FontAvailabilityTracker()
    @ViewBuilder let content: () -> Content

    var body: some View {
        let _ = fontTracker.serifCJKVersion
        let theme = AppTheme.resolve(for: appearanceStore.selection, systemColorScheme: colorScheme)
        content()
            .appTheme(theme)
            .appSkin(.themed(theme))
            .tint(theme.palette.tint)
    }
}
