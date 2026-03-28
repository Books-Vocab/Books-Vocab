import SwiftUI

struct AppTheme: Equatable {
    struct Palette: Equatable {
        let pageBackground: Color
        let stageBackground: Color
        let cardBackground: Color
        let elevatedCardBackground: Color
        let cardBorder: Color
        let divider: Color
        let shadow: Color
        let primaryText: Color
        let secondaryText: Color
        let tertiaryText: Color
        let quaternaryText: Color
        let accent: Color
        let success: Color
        let warning: Color
        let destructive: Color
        let mutedFill: Color
        let scrim: Color
        let tint: Color
    }

    let colorScheme: ColorScheme
    let palette: Palette

    static let light = AppTheme(
        colorScheme: .light,
        palette: .init(
            pageBackground: Color(red: 0.954, green: 0.952, blue: 0.947),
            stageBackground: Color(red: 0.972, green: 0.970, blue: 0.964),
            cardBackground: Color(red: 0.989, green: 0.987, blue: 0.982),
            elevatedCardBackground: Color.white.opacity(0.96),
            cardBorder: Color.black.opacity(0.048),
            divider: Color.black.opacity(0.05),
            shadow: Color.black.opacity(0.028),
            primaryText: Color(red: 0.19, green: 0.19, blue: 0.18),
            secondaryText: Color(red: 0.43, green: 0.43, blue: 0.42),
            tertiaryText: Color(red: 0.44, green: 0.44, blue: 0.42),   // was 0.60 — improved to ~4.5:1 on pageBackground
            quaternaryText: Color(red: 0.56, green: 0.56, blue: 0.54), // was 0.72 — improved contrast for decorative text
            accent: AppColors.accentLight,
            success: AppColors.savedLight,
            warning: AppColors.warning(.light),
            destructive: AppColors.destructiveLight,
            mutedFill: Color.black.opacity(0.035),
            scrim: Color.black.opacity(0.20),
            tint: AppColors.tint
        )
    )

    static let dark = AppTheme(
        colorScheme: .dark,
        palette: .init(
            pageBackground: Color(red: 0.102, green: 0.104, blue: 0.112),
            stageBackground: Color(red: 0.126, green: 0.129, blue: 0.140),
            cardBackground: Color(red: 0.155, green: 0.160, blue: 0.174),
            elevatedCardBackground: Color.white.opacity(0.08),
            cardBorder: Color.white.opacity(0.10),
            divider: Color.white.opacity(0.09),
            shadow: Color.black.opacity(0.34),
            primaryText: Color(red: 0.94, green: 0.94, blue: 0.92),
            secondaryText: Color(red: 0.74, green: 0.75, blue: 0.77),
            tertiaryText: Color(red: 0.58, green: 0.60, blue: 0.64),   // ~5.8:1 on dark pageBackground ✓
            quaternaryText: Color(red: 0.56, green: 0.58, blue: 0.62), // was 0.45 — improved to ~4.5:1 on dark cardBackground
            accent: AppColors.accentDark,
            success: AppColors.savedDark,
            warning: AppColors.warning(.dark),
            destructive: AppColors.destructive(.dark),
            mutedFill: Color.white.opacity(0.08),
            scrim: Color.black.opacity(0.42),
            tint: Color(hue: 215/360, saturation: 0.18, brightness: 0.74)
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
            divider: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.08),
            shadow: Color(red: 0.30, green: 0.26, blue: 0.20).opacity(0.06),
            primaryText: Color(red: 0.22, green: 0.20, blue: 0.17),
            secondaryText: Color(red: 0.46, green: 0.43, blue: 0.38),
            tertiaryText: Color(red: 0.50, green: 0.47, blue: 0.42),
            quaternaryText: Color(red: 0.60, green: 0.57, blue: 0.52),
            accent: AppColors.accentLight,
            success: AppColors.savedLight,
            warning: AppColors.warning(.light),
            destructive: AppColors.destructiveLight,
            mutedFill: Color(red: 0.42, green: 0.38, blue: 0.32).opacity(0.06),
            scrim: Color(red: 0.30, green: 0.26, blue: 0.20).opacity(0.20),
            tint: AppColors.tint
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
            .vocabSkin(.themed(theme))
            .tint(theme.palette.tint)
    }
}
