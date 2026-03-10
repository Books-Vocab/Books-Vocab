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
        let tierIntermediate: Color
        let tierAdvanced: Color
        let warning: Color
        let retry: Color
        let info: Color
        let destructive: Color
        let highlightMark: Color
        let mutedFill: Color
        let link: Color
        let overlayScrim: Color
        let readerThemeLightSwatch: Color
        let readerThemeSepiaSwatch: Color
        let readerThemeDarkSwatch: Color
        let overlayFill: Color
        let highlightMarkSubtle: Color
        let primaryTextMuted: Color
        let quaternaryTextFaint: Color
        let progressBarBackground: Color
        let buttonIdleFill: Color
        let buttonPressedFill: Color
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
        let detailExampleSerif: Font
        let detailExampleSerifStrong: Font
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
        let settingsFontSizeDisplay: Font
        let settingsAdjustSmall: Font
        let settingsAdjustLarge: Font
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
        let microGap: CGFloat
        let chipHorizontalPadding: CGFloat
        let chipVerticalPadding: CGFloat
        let prominentChipHorizontalPadding: CGFloat
        let prominentChipVerticalPadding: CGFloat
        let compactChipHorizontalPadding: CGFloat
        let compactChipVerticalPadding: CGFloat
        let compactRowVerticalPadding: CGFloat
        let compactRowAccessoryTopInset: CGFloat
        let heroDescriptionHorizontalInset: CGFloat
        let actionButtonHorizontalPadding: CGFloat
        let actionButtonVerticalPadding: CGFloat
        let wordRowHorizontalGap: CGFloat
        let wordRowVerticalGap: CGFloat
        let wordRowBaselineGap: CGFloat
        let metadataGap: CGFloat
        let reviewProgressGap: CGFloat
        let reviewProgressBarGap: CGFloat
        let statusHeroGap: CGFloat
        let timelineRowGap: CGFloat
        let timelineDetailGap: CGFloat
        let heroBaselineGap: CGFloat
        let sourceMetadataGap: CGFloat
        let blockGap: CGFloat
        let chipHorizontalPaddingOuter: CGFloat
        // Settings sheet
        let sheetSectionSpacing: CGFloat
        let sheetPadding: CGFloat
        let sheetPaddingCompact: CGFloat
        let controlGap: CGFloat
        let rowContentSpacing: CGFloat
        let controlVerticalPadding: CGFloat
        let controlHorizontalPadding: CGFloat
        let badgeHorizontalPadding: CGFloat
        let tinyGap: CGFloat
        let lineSpacingRelaxed: CGFloat
    }

    struct Metrics {
        let pageHorizontalInset: CGFloat
        let pageTopInset: CGFloat
        let pageBottomInset: CGFloat
        let pageSectionVerticalInset: CGFloat
        let sectionHeaderGap: CGFloat
        let listRowHorizontalInset: CGFloat
        let listDividerInset: CGFloat
        let heroSectionSpacing: CGFloat
        let accessoryTopOffset: CGFloat
        let overlayHorizontalInset: CGFloat
        let overlayVerticalInset: CGFloat
        let summaryHorizontalInset: CGFloat
        let reviewCardHorizontalInset: CGFloat
        let reviewCardTopInset: CGFloat
        let reviewCardBottomInset: CGFloat
        let reviewTopBarHorizontalInset: CGFloat
        let reviewTopBarTopInset: CGFloat
        let reviewTopBarBottomInset: CGFloat
        let reviewToolbarHorizontalInset: CGFloat
        let reviewToolbarVerticalInset: CGFloat
        let reviewFoldPadding: CGFloat
        let reviewFoldSectionSpacing: CGFloat
        let reviewFoldHintBottomInset: CGFloat
        let reviewFoldHintTopInset: CGFloat
        let reviewFrontMinHeight: CGFloat
        let reviewAnswerMinHeight: CGFloat
        let reviewActionMinWidth: CGFloat
        let reviewChevronButtonSize: CGFloat
        let reviewHintCapsuleWidth: CGFloat
        let chromeButtonSize: CGFloat
        let overlayHeaderHorizontalInset: CGFloat
        let overlayHeaderVerticalInset: CGFloat
        let listCardHeaderTopInset: CGFloat
        let listCardHeaderBottomInset: CGFloat
        let readerPanelHorizontalInset: CGFloat
        let readerPanelBottomInset: CGFloat
        let readerPanelHandleWidth: CGFloat
        let readerPanelHandleHeight: CGFloat
        let readerPanelHandleTopInset: CGFloat
        let readerPanelHandleBottomInset: CGFloat
        let readerSettingsHandleWidth: CGFloat
        let readerSettingsHandleHeight: CGFloat
        let readerSettingsHandleTopInset: CGFloat
        let readerSettingsHandleBottomInset: CGFloat
        let readerPanelShadowOpacity: Double
        let readerPanelShadowRadius: CGFloat
        let readerPanelShadowY: CGFloat
        let readerSettingsSectionSpacing: CGFloat
        let readerSettingsHorizontalInset: CGFloat
        let readerSettingsBottomInset: CGFloat
        let readerSettingsHeaderSpacing: CGFloat
        let readerSettingsHeaderBottomInset: CGFloat
        let readerSettingsHeaderMicroInset: CGFloat
        let readerSettingsCardPadding: CGFloat
        let readerSettingsControlHorizontalPadding: CGFloat
        let readerSettingsControlVerticalPadding: CGFloat
        let readerSettingsOptionHorizontalPadding: CGFloat
        let readerSettingsOptionVerticalPadding: CGFloat
        let readerSettingsHighlightPreviewTrailingInset: CGFloat
        let readerSettingsModeMinHeight: CGFloat
        let readerSettingsHighlightMinHeight: CGFloat
        let overlayCompactDividerInset: CGFloat
        let overlayDrawerHorizontalInset: CGFloat
        let overlayDrawerBottomInset: CGFloat
        let emptyStateOuterInset: CGFloat
        let listEmptyStateVerticalInset: CGFloat
        let reviewToolbarShadowOpacity: Double
        let reviewToolbarShadowRadius: CGFloat
        let reviewToolbarShadowY: CGFloat
        let cardBlockPadding: CGFloat
        let cardBlockContentGap: CGFloat
        let cardBlockInnerGap: CGFloat
        let cardDividerHorizontalPadding: CGFloat
        let linkRowVerticalPadding: CGFloat
        let linkRowHorizontalGap: CGFloat
        let linkDetailGap: CGFloat
        let metadataFooterGap: CGFloat
        let metadataFooterItemGap: CGFloat
        let tabSelectorHeight: CGFloat
        let progressBarWidth: CGFloat
        let progressBarHeight: CGFloat
        let paragraphLineSpacing: CGFloat
        let detailLineSpacing: CGFloat
        let exampleTruncateRadius: Int
        let reviewFrontHeightRatio: CGFloat
        let reviewCompletionHeightRatio: CGFloat
        let labelTracking: CGFloat
        let reviewSwipeThreshold: CGFloat
        let reviewSwipeMaxRotation: Double
        let reviewSwipeOpacityFloor: Double
        let panelHandleOpacity: Double
    }

    let palette: Palette
    let typography: Typography
    let radii: Radii
    let spacing: Spacing
    let metrics: Metrics

    func tierColor(for tier: String?) -> Color {
        switch tier {
        case "core":
            return palette.success
        case "intermediate":
            return palette.tierIntermediate
        case "advanced":
            return palette.tierAdvanced
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
        detailExampleSerif: .custom("CormorantGaramond-Italic", size: 22),
        detailExampleSerifStrong: .custom("CormorantGaramond-BoldItalic", size: 22),
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
        symbolHero: .system(size: 44, weight: .light, design: .default),
        settingsFontSizeDisplay: .system(size: 28, weight: .semibold, design: .monospaced),
        settingsAdjustSmall: .system(size: 15, weight: .medium, design: .default),
        settingsAdjustLarge: .system(size: 28, weight: .medium, design: .default)
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
        rowPadding: 9,
        microGap: 6,
        chipHorizontalPadding: 10,
        chipVerticalPadding: 6,
        prominentChipHorizontalPadding: 8,
        prominentChipVerticalPadding: 4,
        compactChipHorizontalPadding: 6,
        compactChipVerticalPadding: 3,
        compactRowVerticalPadding: 7,
        compactRowAccessoryTopInset: 2,
        heroDescriptionHorizontalInset: 40,
        actionButtonHorizontalPadding: 16,
        actionButtonVerticalPadding: 13,
        wordRowHorizontalGap: 10,
        wordRowVerticalGap: 4,
        wordRowBaselineGap: 6,
        metadataGap: 4,
        reviewProgressGap: 12,
        reviewProgressBarGap: 5,
        statusHeroGap: 12,
        timelineRowGap: 12,
        timelineDetailGap: 2,
        heroBaselineGap: 8,
        sourceMetadataGap: 6,
        blockGap: 12,
        chipHorizontalPaddingOuter: 12,
        sheetSectionSpacing: 20,
        sheetPadding: 24,
        sheetPaddingCompact: 20,
        controlGap: 10,
        rowContentSpacing: 12,
        controlVerticalPadding: 12,
        controlHorizontalPadding: 14,
        badgeHorizontalPadding: 9,
        tinyGap: 4,
        lineSpacingRelaxed: 6
    )

    static let baseMetrics = Metrics(
        pageHorizontalInset: AppShellMetrics.pageHorizontalPadding,
        pageTopInset: 16,
        pageBottomInset: 120,
        pageSectionVerticalInset: AppMetrics.spacingSmall,
        sectionHeaderGap: 10,
        listRowHorizontalInset: 16,
        listDividerInset: 16,
        heroSectionSpacing: 16,
        accessoryTopOffset: 10,
        overlayHorizontalInset: 20,
        overlayVerticalInset: 20,
        summaryHorizontalInset: 24,
        reviewCardHorizontalInset: AppMetrics.spacingLarge,
        reviewCardTopInset: AppMetrics.spacingMedium,
        reviewCardBottomInset: AppMetrics.spacingXXL,
        reviewTopBarHorizontalInset: 20,
        reviewTopBarTopInset: 10,
        reviewTopBarBottomInset: 6,
        reviewToolbarHorizontalInset: 20,
        reviewToolbarVerticalInset: 12,
        reviewFoldPadding: 24,
        reviewFoldSectionSpacing: 16,
        reviewFoldHintBottomInset: 18,
        reviewFoldHintTopInset: 18,
        reviewFrontMinHeight: 208,
        reviewAnswerMinHeight: 188,
        reviewActionMinWidth: 92,
        reviewChevronButtonSize: 30,
        reviewHintCapsuleWidth: 42,
        chromeButtonSize: 32,
        overlayHeaderHorizontalInset: 16,
        overlayHeaderVerticalInset: 12,
        listCardHeaderTopInset: 14,
        listCardHeaderBottomInset: 12,
        readerPanelHorizontalInset: 18,
        readerPanelBottomInset: 16,
        readerPanelHandleWidth: 32,
        readerPanelHandleHeight: 4,
        readerPanelHandleTopInset: 10,
        readerPanelHandleBottomInset: 12,
        readerSettingsHandleWidth: 48,
        readerSettingsHandleHeight: 5,
        readerSettingsHandleTopInset: 12,
        readerSettingsHandleBottomInset: 14,
        readerPanelShadowOpacity: 0.72,
        readerPanelShadowRadius: 10,
        readerPanelShadowY: -3,
        readerSettingsSectionSpacing: 18,
        readerSettingsHorizontalInset: 18,
        readerSettingsBottomInset: 20,
        readerSettingsHeaderSpacing: 14,
        readerSettingsHeaderBottomInset: 16,
        readerSettingsHeaderMicroInset: 4,
        readerSettingsCardPadding: 16,
        readerSettingsControlHorizontalPadding: 14,
        readerSettingsControlVerticalPadding: 14,
        readerSettingsOptionHorizontalPadding: 12,
        readerSettingsOptionVerticalPadding: 12,
        readerSettingsHighlightPreviewTrailingInset: 22,
        readerSettingsModeMinHeight: 112,
        readerSettingsHighlightMinHeight: 78,
        overlayCompactDividerInset: 8,
        overlayDrawerHorizontalInset: 12,
        overlayDrawerBottomInset: 8,
        emptyStateOuterInset: 20,
        listEmptyStateVerticalInset: 4,
        reviewToolbarShadowOpacity: 1.1,
        reviewToolbarShadowRadius: 6,
        reviewToolbarShadowY: -2,
        cardBlockPadding: 24,
        cardBlockContentGap: 16,
        cardBlockInnerGap: 8,
        cardDividerHorizontalPadding: 24,
        linkRowVerticalPadding: 8,
        linkRowHorizontalGap: 8,
        linkDetailGap: 3,
        metadataFooterGap: 24,
        metadataFooterItemGap: 4,
        tabSelectorHeight: 32,
        progressBarWidth: 104,
        progressBarHeight: 5,
        paragraphLineSpacing: 4,
        detailLineSpacing: 5,
        exampleTruncateRadius: 5,
        reviewFrontHeightRatio: 0.28,
        reviewCompletionHeightRatio: 0.22,
        labelTracking: 0.5,
        reviewSwipeThreshold: 100,
        reviewSwipeMaxRotation: 12,
        reviewSwipeOpacityFloor: 0.3,
        panelHandleOpacity: 0.24
    )

    /// 由 AppTheme 組裝的 VocabSkin，隨系統深淺色模式自動切換。
    /// 這是正常使用的工廠方法，請在注入 @Environment(\.vocabSkin) 時呼叫此方法。
    static func themed(_ theme: AppTheme) -> VocabSkin {
        let link = theme.colorScheme == .dark
            ? Color(red: 0.62, green: 0.71, blue: 0.84)
            : Color(red: 0.47, green: 0.56, blue: 0.67)

        return VocabSkin(
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
                tierIntermediate: Color(red: 0.72, green: 0.63, blue: 0.36),
                tierAdvanced: Color(red: 0.84, green: 0.54, blue: 0.28),
                warning: theme.palette.warning,
                retry: theme.colorScheme == .dark
                    ? Color(hue: 0.08, saturation: 0.45, brightness: 0.78)
                    : Color(hue: 0.08, saturation: 0.55, brightness: 0.68),
                info: link,
                destructive: theme.palette.destructive,
                highlightMark: theme.colorScheme == .dark
                    ? Color(red: 0.73, green: 0.66, blue: 0.33)
                    : Color(red: 0.90, green: 0.84, blue: 0.57),
                mutedFill: theme.palette.mutedFill,
                link: link,
                overlayScrim: theme.palette.scrim,
                readerThemeLightSwatch: Color(red: 0.90, green: 0.90, blue: 0.88),
                readerThemeSepiaSwatch: Color(red: 0.82, green: 0.73, blue: 0.58),
                readerThemeDarkSwatch: Color(red: 0.34, green: 0.35, blue: 0.38),
                overlayFill: theme.colorScheme == .dark
                    ? Color.white.opacity(0.15)
                    : Color.white.opacity(0.12),
                highlightMarkSubtle: theme.colorScheme == .dark
                    ? Color(red: 0.73, green: 0.66, blue: 0.33).opacity(0.68)
                    : Color(red: 0.90, green: 0.84, blue: 0.57).opacity(0.68),
                primaryTextMuted: theme.palette.primaryText.opacity(0.84),
                quaternaryTextFaint: theme.palette.quaternaryText.opacity(0.14),
                progressBarBackground: theme.colorScheme == .dark
                    ? Color.white.opacity(0.10)
                    : Color.black.opacity(0.07),
                buttonIdleFill: theme.colorScheme == .dark
                    ? Color.white.opacity(0.12)
                    : Color.black.opacity(0.07),
                buttonPressedFill: theme.colorScheme == .dark
                    ? Color.white.opacity(0.18)
                    : Color.black.opacity(0.12)
            ),
            typography: baseTypography,
            radii: baseRadii,
            spacing: baseSpacing,
            metrics: baseMetrics
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
            tertiaryText: Color(red: 0.44, green: 0.44, blue: 0.42),   // was 0.60 — improved to ~4.5:1 on pageBackground
            quaternaryText: Color(red: 0.56, green: 0.56, blue: 0.54), // was 0.72 — improved contrast
            translationText: Color(red: 0.54, green: 0.50, blue: 0.44),
            accent: Color(red: 0.49, green: 0.56, blue: 0.64),
            success: Color(red: 0.50, green: 0.64, blue: 0.50),
            tierIntermediate: Color(red: 0.72, green: 0.63, blue: 0.36),
            tierAdvanced: Color(red: 0.84, green: 0.54, blue: 0.28),
            warning: Color(hue: 0.1, saturation: 0.8, brightness: 0.8),
            retry: Color(hue: 0.08, saturation: 0.55, brightness: 0.68),
            info: Color(red: 0.47, green: 0.56, blue: 0.67),
            destructive: Color(red: 0.73, green: 0.49, blue: 0.46),
            highlightMark: Color(red: 0.90, green: 0.84, blue: 0.57),
            mutedFill: Color.black.opacity(0.035),
            link: Color(red: 0.47, green: 0.56, blue: 0.67),
            overlayScrim: Color.black.opacity(0.20),
            readerThemeLightSwatch: Color(red: 0.90, green: 0.90, blue: 0.88),
            readerThemeSepiaSwatch: Color(red: 0.82, green: 0.73, blue: 0.58),
            readerThemeDarkSwatch: Color(red: 0.34, green: 0.35, blue: 0.38),
            overlayFill: Color.white.opacity(0.12),
            highlightMarkSubtle: Color(red: 0.90, green: 0.84, blue: 0.57).opacity(0.68),
            primaryTextMuted: Color(red: 0.19, green: 0.19, blue: 0.18).opacity(0.84),
            quaternaryTextFaint: Color(red: 0.72, green: 0.72, blue: 0.70).opacity(0.14),
            progressBarBackground: Color.black.opacity(0.07),
            buttonIdleFill: Color.black.opacity(0.07),
            buttonPressedFill: Color.black.opacity(0.12)
        ),
        typography: baseTypography,
        radii: baseRadii,
        spacing: baseSpacing,
        metrics: baseMetrics
    )
}

extension VocabSkin {
    func readerThemeSwatchColor(_ theme: ReaderTheme) -> Color {
        switch theme {
        case .light:
            return palette.readerThemeLightSwatch
        case .sepia:
            return palette.readerThemeSepiaSwatch
        case .dark:
            return palette.readerThemeDarkSwatch
        }
    }
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
