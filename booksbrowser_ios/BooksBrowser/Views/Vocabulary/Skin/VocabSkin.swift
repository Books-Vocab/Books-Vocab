//
//  VocabSkin.swift
//  BooksBrowser
//
//  Vocabulary 功能的唯一 UI Token 來源（顏色、字型、圓角、間距）
//  ─────────────────────────────────────────────────────────────────────
//  使用方式：
//    所有 Vocabulary 組件透過 @Environment(\.vocabSkin) 讀取此值，
//    不應直接使用 AppColors、AppTheme 或硬編碼色彩。
//
//  組裝來源有兩種：
//    1. VocabSkin.themed(appTheme)  — 由 AppTheme（Light/Dark）組裝，
//       99% 情況下使用這個，可隨系統深淺色模式自動切換。
//    2. VocabSkin.previewNeutral   — 硬編碼的靜態淺色 skin，
//       僅用於 SwiftUI Preview 或特定固定場景，不受系統深淺色影響。
//
//  設計哲學：Morandi 紙本排版
//    低飽和度、紙張質感，typography 以 monospaced 為主視覺重心。
//  ─────────────────────────────────────────────────────────────────────

import SwiftUI

struct VocabSkin {
    struct Palette {
        let pageBackground: Color
        let stageBackground: Color
        let cardBackground: Color
        let cardBorder: Color
        let divider: Color
        let shadow: Color
        let primaryText: Color
        let secondaryText: Color
        let tertiaryText: Color
        let quaternaryText: Color
        let translationText: Color
        let accent: Color
        let success: Color
        let destructive: Color
        let highlightMark: Color
        let mutedFill: Color
        let link: Color
    }

    struct Typography {
        let displayTitle: Font
        let sectionTitle: Font
        let detailWord: Font
        let reviewWord: Font
        let rowWord: Font
        let translationTitle: Font
        let body: Font
        let example: Font
        let caption: Font
        let captionStrong: Font
        let monoLabel: Font
        let monoBody: Font
        let monoBodyStrong: Font
        let monoEmphasis: Font
        let numericHero: Font
        let iconTiny: Font
        let iconSmall: Font
        let iconMedium: Font
        let iconToolbar: Font
        let iconNavigation: Font
        let symbolLarge: Font
        let symbolHero: Font
    }

    struct Radii {
        let stage: CGFloat
        let card: CGFloat
        let overlay: CGFloat
        let control: CGFloat
        let chip: CGFloat
        let tiny: CGFloat
    }

    struct Spacing {
        let cardPadding: CGFloat
        let sectionGap: CGFloat
        let inlineGap: CGFloat
        let rowPadding: CGFloat
    }

    let palette: Palette
    let typography: Typography
    let radii: Radii
    let spacing: Spacing

    func tierColor(for tier: String?) -> Color {
        switch tier {
        case "core":
            return palette.success
        case "intermediate":
            return Color(red: 0.72, green: 0.63, blue: 0.36)
        case "advanced":
            return Color(red: 0.84, green: 0.54, blue: 0.28)
        case "rare":
            return palette.destructive
        default:
            return palette.secondaryText
        }
    }

    func tierLabel(for tier: String?) -> String {
        switch tier {
        case "core":
            return "core"
        case "intermediate":
            return "intermediate"
        case "advanced":
            return "advanced"
        case "rare":
            return "rare"
        default:
            return tier ?? ""
        }
    }
}

extension VocabSkin {
    static let baseTypography = Typography(
        displayTitle: .system(size: 24, weight: .semibold, design: .default),
        sectionTitle: .system(size: 18, weight: .semibold, design: .default),
        detailWord: .system(size: 27, weight: .semibold, design: .monospaced),
        reviewWord: .system(size: 36, weight: .semibold, design: .monospaced),
        rowWord: .system(size: 18, weight: .semibold, design: .monospaced),
        translationTitle: .system(size: 21, weight: .semibold, design: .default),
        body: .system(size: 15, weight: .regular, design: .default),
        example: .system(size: 18, weight: .regular, design: .default),
        caption: .system(size: 12, weight: .medium, design: .default),
        captionStrong: .system(size: 12, weight: .semibold, design: .default),
        monoLabel: .system(size: 10, weight: .medium, design: .monospaced),
        monoBody: .system(size: 14, weight: .regular, design: .monospaced),
        monoBodyStrong: .system(size: 14, weight: .semibold, design: .monospaced),
        monoEmphasis: .system(size: 16, weight: .semibold, design: .monospaced),
        numericHero: .system(size: 38, weight: .semibold, design: .default),
        iconTiny: .system(size: 10, weight: .thin, design: .default),
        iconSmall: .system(size: 12, weight: .medium, design: .default),
        iconMedium: .system(size: 14, weight: .medium, design: .default),
        iconToolbar: .system(size: 15, weight: .medium, design: .default),
        iconNavigation: .system(size: 16, weight: .thin, design: .default),
        symbolLarge: .system(size: 30, weight: .light, design: .default),
        symbolHero: .system(size: 44, weight: .light, design: .default)
    )

    static let baseRadii = Radii(
        stage: 14,
        card: 12,
        overlay: 13,
        control: 10,
        chip: 8,
        tiny: 7
    )

    static let baseSpacing = Spacing(
        cardPadding: 18,
        sectionGap: 14,
        inlineGap: 8,
        rowPadding: 9
    )

    /// 由 AppTheme 組裝的 VocabSkin，隨系統深淺色模式自動切換。
    /// 這是正常使用的工廠方法，請在注入 @Environment(\.vocabSkin) 時呼叫此方法。
    static func themed(_ theme: AppTheme) -> VocabSkin {
        VocabSkin(
            palette: .init(
                pageBackground: theme.palette.pageBackground,
                stageBackground: theme.palette.stageBackground,
                cardBackground: theme.palette.cardBackground,
                cardBorder: theme.palette.cardBorder,
                divider: theme.palette.divider,
                shadow: theme.palette.shadow,
                primaryText: theme.palette.primaryText,
                secondaryText: theme.palette.secondaryText,
                tertiaryText: theme.palette.tertiaryText,
                quaternaryText: theme.palette.quaternaryText,
                translationText: theme.colorScheme == .dark
                    ? Color(red: 0.80, green: 0.72, blue: 0.64)
                    : Color(red: 0.54, green: 0.50, blue: 0.44),
                accent: theme.palette.accent,
                success: theme.palette.success,
                destructive: theme.palette.destructive,
                highlightMark: theme.colorScheme == .dark
                    ? Color(red: 0.73, green: 0.66, blue: 0.33)
                    : Color(red: 0.90, green: 0.84, blue: 0.57),
                mutedFill: theme.palette.mutedFill,
                link: theme.colorScheme == .dark
                    ? Color(red: 0.62, green: 0.71, blue: 0.84)
                    : Color(red: 0.47, green: 0.56, blue: 0.67)
            ),
            typography: baseTypography,
            radii: baseRadii,
            spacing: baseSpacing
        )
    }

    /// 硬編碼的靜態淺色 skin，不受系統深淺色模式影響。
    /// 僅用於 SwiftUI Preview 或特定固定呈現場景，正常業務請改用 themed()。
    static let previewNeutral = VocabSkin(
        palette: .init(
            pageBackground: Color(red: 0.954, green: 0.952, blue: 0.947),
            stageBackground: Color(red: 0.972, green: 0.970, blue: 0.964),
            cardBackground: Color(red: 0.989, green: 0.987, blue: 0.982),
            cardBorder: Color.black.opacity(0.048),
            divider: Color.black.opacity(0.05),
            shadow: Color.black.opacity(0.028),
            primaryText: Color(red: 0.19, green: 0.19, blue: 0.18),
            secondaryText: Color(red: 0.43, green: 0.43, blue: 0.42),
            tertiaryText: Color(red: 0.60, green: 0.60, blue: 0.58),
            quaternaryText: Color(red: 0.72, green: 0.72, blue: 0.70),
            translationText: Color(red: 0.54, green: 0.50, blue: 0.44),
            accent: Color(red: 0.49, green: 0.56, blue: 0.64),
            success: Color(red: 0.50, green: 0.64, blue: 0.50),
            destructive: Color(red: 0.73, green: 0.49, blue: 0.46),
            highlightMark: Color(red: 0.90, green: 0.84, blue: 0.57),
            mutedFill: Color.black.opacity(0.035),
            link: Color(red: 0.47, green: 0.56, blue: 0.67)
        ),
        typography: baseTypography,
        radii: baseRadii,
        spacing: baseSpacing
    )
}

private struct VocabSkinEnvironmentKey: EnvironmentKey {
    static let defaultValue = VocabSkin.themed(.light)
}

extension EnvironmentValues {
    var vocabSkin: VocabSkin {
        get { self[VocabSkinEnvironmentKey.self] }
        set { self[VocabSkinEnvironmentKey.self] = newValue }
    }
}

extension View {
    func vocabSkin(_ skin: VocabSkin) -> some View {
        environment(\.vocabSkin, skin)
    }
}
