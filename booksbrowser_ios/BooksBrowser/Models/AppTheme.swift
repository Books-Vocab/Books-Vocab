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
            tertiaryText: Color(red: 0.60, green: 0.60, blue: 0.58),
            quaternaryText: Color(red: 0.72, green: 0.72, blue: 0.70),
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
            tertiaryText: Color(red: 0.58, green: 0.60, blue: 0.64),
            quaternaryText: Color(red: 0.45, green: 0.47, blue: 0.52),
            accent: AppColors.accentDark,
            success: AppColors.savedDark,
            warning: AppColors.warning(.dark),
            destructive: AppColors.destructive(.dark),
            mutedFill: Color.white.opacity(0.08),
            scrim: Color.black.opacity(0.42),
            tint: Color(hue: 215/360, saturation: 0.18, brightness: 0.74)
        )
    )

    static func resolve(for colorScheme: ColorScheme) -> AppTheme {
        colorScheme == .dark ? .dark : .light
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
    @ViewBuilder let content: () -> Content

    var body: some View {
        let theme = AppTheme.resolve(for: colorScheme)
        content()
            .appTheme(theme)
            .vocabSkin(.themed(theme))
            .tint(theme.palette.tint)
    }
}
