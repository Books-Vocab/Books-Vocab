//
//  AppSkin.swift
//  BooksBrowser
//
//  全 app 共用的 feature-level UI Token 層（顏色、字型、圓角、間距、metrics）。
//  ─────────────────────────────────────────────────────────────────────
//  定位：AppSkin 是 AppTheme 的 feature 擴充層 —— Palette facade（passthrough
//  AppTheme.Palette + feature 色）＋ Typography / Radii / Spacing / Metrics。
//  涵蓋範圍不限 Vocabulary：Reader / Settings / Podcast 等 feature 皆透過
//  @Environment(\.appSkin) 取用（前身為 VocabSkin，已正名以符實際 scope）。
//
//  使用方式：
//    組件透過 @Environment(\.appSkin) 讀取，不應直接用 AppColors 或硬編碼色彩。
//
//  組裝來源有兩種：
//    1. AppSkin.themed(appTheme)  — 由 AppTheme（Light/Dark）組裝，
//       99% 情況下使用這個，可隨系統深淺色模式自動切換。
//    2. AppSkin.previewNeutral   — 由 themed(.light) 組裝的固定淺色 skin，
//       僅用於 SwiftUI Preview 或特定固定場景，不受系統深淺色影響。
//
//  設計哲學：Morandi 紙本排版
//    低飽和度、紙張質感，typography 以 monospaced 為主視覺重心。
//  ─────────────────────────────────────────────────────────────────────

import SwiftUI

/// AppSkin 專屬色票 —— `AppTheme.Palette` 未涵蓋的 feature 色。
/// 與 `AppColors`（Reader + 全域）分離：此 enum 僅供 `AppSkin.themed()` 組裝取用。
/// scheme-aware 色給 light/dark 一對；固定色（不隨深淺色）為單值。
enum AppSkinColors {
    // ── 連結文字 ──
    static let linkLight = Color(red: 0.47, green: 0.56, blue: 0.67)
    static let linkDark  = Color(red: 0.62, green: 0.71, blue: 0.84)

    // ── 翻譯文字（栗棕）──
    static let translationLight = Color(red: 0.54, green: 0.50, blue: 0.44)
    static let translationDark  = Color(red: 0.80, green: 0.72, blue: 0.64)

    // ── 難度 Tier（固定色，不隨系統深淺色 — 與 themed() 既有行為一致）──
    static let tierIntermediate = Color(red: 0.72, green: 0.63, blue: 0.36)
    static let tierAdvanced     = Color(red: 0.84, green: 0.54, blue: 0.28)

    // ── 重試提示（琥珀）──
    static let retryLight = Color(hue: 0.08, saturation: 0.55, brightness: 0.68)
    static let retryDark  = Color(hue: 0.08, saturation: 0.45, brightness: 0.78)

    // ── 逾期（霧紫）──
    static let overdueLight = Color(red: 0.56, green: 0.40, blue: 0.66)
    static let overdueDark  = Color(red: 0.62, green: 0.48, blue: 0.72)

    // ── 例句高光（紙感螢光筆）──
    static let highlightMarkLight = Color(red: 0.90, green: 0.84, blue: 0.57)
    static let highlightMarkDark  = Color(red: 0.73, green: 0.66, blue: 0.33)

    // ── Reader 主題色票（固定，不隨系統深淺色）──
    static let readerThemeLightSwatch = Color(red: 0.90, green: 0.90, blue: 0.88)
    static let readerThemeSepiaSwatch = Color(red: 0.82, green: 0.73, blue: 0.58)
    static let readerThemeDarkSwatch  = Color(red: 0.34, green: 0.35, blue: 0.38)
}

struct AppSkin {
    /// Vocabulary skin 色票 —— facade 結構，非平行設計系統。
    /// - 與 `AppTheme.Palette` 同義的欄位為 computed forwarder，唯一真相在 `base`：
    ///   AppTheme 改色自動穿透，不可能漂移。
    /// - feature-own 色（tier / link / retry / overdue / highlightMark / translation
    ///   / readerThemeSwatch）為 stored，由 `themed()` 注入。
    /// - 衍生欄位（*Muted / *Faint / *Subtle）為 computed，不另存複本。
    struct Palette {
        /// 全域 AppTheme 色票 —— 所有 passthrough 欄位的唯一真相。
        let base: AppTheme.Palette

        // ── feature-own stored 色 ──
        let translationText: Color
        let tierIntermediate: Color
        let tierAdvanced: Color
        let retry: Color
        let overdue: Color
        let highlightMark: Color
        let link: Color
        let readerThemeLightSwatch: Color
        let readerThemeSepiaSwatch: Color
        let readerThemeDarkSwatch: Color

        // ── passthrough forwarder（唯一真相 = base）──
        var pageBackground: Color { base.pageBackground }
        var stageBackground: Color { base.stageBackground }
        var cardBackground: Color { base.cardBackground }
        var cardBorder: Color { base.cardBorder }
        var borderStrong: Color { base.borderStrong }
        var divider: Color { base.divider }
        var shadow: Color { base.shadow }
        var primaryText: Color { base.primaryText }
        var secondaryText: Color { base.secondaryText }
        var tertiaryText: Color { base.tertiaryText }
        var quaternaryText: Color { base.quaternaryText }
        var accent: Color { base.accent }
        var accentHero: Color { base.accentHero }
        var accentSubtle: Color { base.accentSubtle }
        var success: Color { base.success }
        var successBg: Color { base.successBg }
        var warning: Color { base.warning }
        var warningBg: Color { base.warningBg }
        var info: Color { base.info }
        var infoBg: Color { base.infoBg }
        var destructive: Color { base.destructive }
        var destructiveBg: Color { base.destructiveBg }
        var mutedFill: Color { base.mutedFill }
        var overlayScrim: Color { base.scrim }
        var overlayFill: Color { base.overlayFill }
        var progressBarBackground: Color { base.progressBarBackground }
        var buttonIdleFill: Color { base.buttonIdleFill }
        var buttonPressedFill: Color { base.buttonPressedFill }

        // ── 衍生欄位（由 base / feature 色計算，不另存）──
        var primaryTextMuted: Color { base.primaryText.opacity(0.84) }
        var quaternaryTextFaint: Color { base.quaternaryText.opacity(0.14) }
        var highlightMarkSubtle: Color { highlightMark.opacity(0.68) }
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
        let symbolPlayback: Font
        let settingsFontSizeDisplay: Font
        let settingsAdjustSmall: Font
        let settingsAdjustLarge: Font
    }

    /// 圓角語意 token —— 值一律取自 AppRadius scale。
    /// 名稱保留語意層：card·overlay=md(12) / control·chip·tiny=sm(8)。
    struct Radii {
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
        let chipVerticalPaddingLoose: CGFloat
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
        let syncOverlayInset: CGFloat
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
        let readerSettingsDividerOpacity: Double
        let graphDrawerBottomInset: CGFloat
    }

    /// 統一的字詞高光樣式配置（例句中 `**word**` 的視覺呈現）
    struct HighlightConfig {
        let backgroundOpacity: Double
        let underlineOpacity: Double
        let showBackground: Bool
        let showUnderline: Bool
        let fontWeight: Font.Weight

        static let `default` = HighlightConfig(
            backgroundOpacity: 0.22,
            underlineOpacity: 0.68,
            showBackground: true,
            showUnderline: false,
            fontWeight: .semibold
        )
    }

    let palette: Palette
    let typography: Typography
    let radii: Radii
    let spacing: Spacing
    let metrics: Metrics
    let highlight: HighlightConfig

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

extension AppSkin {
    private static var _cachedTypography: Typography?

    static var baseTypography: Typography {
        if let cached = _cachedTypography { return cached }
        let t = buildTypography()
        _cachedTypography = t
        return t
    }

    static func invalidateTypographyCache() {
        _cachedTypography = nil
    }

    private static func buildTypography() -> Typography {
        Typography(
            // Serif tokens — 標題 (Athelas + STSongti-TC)
            displayTitle: AppFonts.serif(size: 24, bold: true),
            sectionTitle: AppFonts.serif(size: 18, bold: true),
            detailWord: AppFonts.systemMono(size: 27, weight: .semibold),
            reviewWord: AppFonts.systemMono(size: 36, weight: .semibold),
            rowWord: AppFonts.systemMono(size: 18, weight: .semibold),
            translationTitle: AppFonts.serif(size: 21, bold: true),
            // Sans tokens — 內文 (ElmsSans + PingFang TC)
            body: AppFonts.sans(size: 15),
            example: AppFonts.sans(size: 18),
            detailExampleSerif: AppFonts.serifItalic(size: 22),
            detailExampleSerifStrong: AppFonts.serifItalic(size: 22, bold: true),
            caption: AppFonts.sans(size: 12, bold: true),
            // Mono tokens (ElmsSans + system monospaced)
            monoLabel: AppFonts.mono(size: 10, bold: true),
            monoBody: AppFonts.mono(size: 14),
            monoBodyStrong: AppFonts.mono(size: 14, bold: true),
            monoEmphasis: AppFonts.mono(size: 16, bold: true),
            numericHero: AppFonts.serif(size: 38, bold: true),
            // SF Symbols — 系統字繪製，走 AppFonts.symbol builder
            iconTiny: AppFonts.symbol(size: 10, weight: .thin),
            iconSmall: AppFonts.symbol(size: 12, weight: .medium),
            iconMedium: AppFonts.symbol(size: 14, weight: .medium),
            iconToolbar: AppFonts.symbol(size: 15, weight: .medium),
            iconNavigation: AppFonts.symbol(size: 16, weight: .thin),
            symbolLarge: AppFonts.symbol(size: 30, weight: .light),
            symbolHero: AppFonts.symbol(size: 44, weight: .light),
            symbolPlayback: AppFonts.symbol(size: 56, weight: .light),
            // Settings — mono (數值調控)
            settingsFontSizeDisplay: AppFonts.mono(size: 28, bold: true),
            settingsAdjustSmall: AppFonts.sans(size: 15, bold: true),
            settingsAdjustLarge: AppFonts.sans(size: 28, bold: true)
        )
    }

    static let baseRadii = Radii(
        card: AppRadius.md,
        overlay: AppRadius.md,
        control: AppRadius.sm,
        chip: AppRadius.sm,
        tiny: AppRadius.sm
    )

    static let baseSpacing = Spacing(
        cardPadding: 18,
        sectionGap: 14,
        inlineGap: 8,
        rowPadding: 9,
        microGap: 6,
        chipHorizontalPadding: 10,
        chipVerticalPadding: 6,
        chipVerticalPaddingLoose: 8,
        prominentChipHorizontalPadding: 8,
        prominentChipVerticalPadding: 4,
        compactChipHorizontalPadding: 6,
        compactChipVerticalPadding: 3,
        compactRowVerticalPadding: 10,
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
        pageSectionVerticalInset: AppSpacing.s2,
        sectionHeaderGap: 10,
        listRowHorizontalInset: 16,
        listDividerInset: 16,
        heroSectionSpacing: 16,
        accessoryTopOffset: 10,
        overlayHorizontalInset: 20,
        syncOverlayInset: 32,
        overlayVerticalInset: 20,
        summaryHorizontalInset: 24,
        reviewCardHorizontalInset: AppSpacing.s2,
        reviewCardTopInset: AppSpacing.s2,
        reviewCardBottomInset: AppSpacing.s2,
        reviewTopBarHorizontalInset: 20,
        reviewTopBarTopInset: 10,
        reviewTopBarBottomInset: 6,
        reviewToolbarHorizontalInset: 20,
        reviewToolbarVerticalInset: 12,
        reviewFoldPadding: 28,
        reviewFoldSectionSpacing: 24,
        reviewFoldHintBottomInset: 22,
        reviewFoldHintTopInset: 22,
        reviewFrontMinHeight: 120,
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
        listEmptyStateVerticalInset: 24,
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
        reviewFrontHeightRatio: 0.22,
        reviewCompletionHeightRatio: 0.18,
        labelTracking: 0.5,
        reviewSwipeThreshold: 100,
        reviewSwipeMaxRotation: 12,
        reviewSwipeOpacityFloor: 0.3,
        panelHandleOpacity: 0.24,
        readerSettingsDividerOpacity: 0.6,
        graphDrawerBottomInset: 11
    )

    /// 由 AppTheme 組裝的 AppSkin，隨系統深淺色模式自動切換。
    /// 這是正常使用的工廠方法，請在注入 @Environment(\.appSkin) 時呼叫此方法。
    static func themed(_ theme: AppTheme) -> AppSkin {
        let isDark = theme.colorScheme == .dark

        return AppSkin(
            palette: .init(
                base: theme.palette,
                translationText: isDark ? AppSkinColors.translationDark : AppSkinColors.translationLight,
                tierIntermediate: AppSkinColors.tierIntermediate,
                tierAdvanced: AppSkinColors.tierAdvanced,
                retry: isDark ? AppSkinColors.retryDark : AppSkinColors.retryLight,
                overdue: isDark ? AppSkinColors.overdueDark : AppSkinColors.overdueLight,
                highlightMark: isDark ? AppSkinColors.highlightMarkDark : AppSkinColors.highlightMarkLight,
                link: isDark ? AppSkinColors.linkDark : AppSkinColors.linkLight,
                readerThemeLightSwatch: AppSkinColors.readerThemeLightSwatch,
                readerThemeSepiaSwatch: AppSkinColors.readerThemeSepiaSwatch,
                readerThemeDarkSwatch: AppSkinColors.readerThemeDarkSwatch
            ),
            typography: baseTypography,
            radii: baseRadii,
            spacing: baseSpacing,
            metrics: baseMetrics,
            highlight: .default
        )
    }

    /// 固定淺色 skin，不受系統深淺色模式影響。
    /// 僅用於 SwiftUI Preview 或特定固定呈現場景，正常業務請改用 themed()。
    /// 由 themed(.light) 組裝 — 與正式 light skin 單一真相，消除硬編碼複本漂移。
    static let previewNeutral = AppSkin.themed(.light)
}

#if os(iOS)
extension AppSkin {
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
#endif

private struct AppSkinEnvironmentKey: EnvironmentKey {
    static let defaultValue = AppSkin.themed(.light)
}

extension EnvironmentValues {
    var appSkin: AppSkin {
        get { self[AppSkinEnvironmentKey.self] }
        set { self[AppSkinEnvironmentKey.self] = newValue }
    }
}

extension View {
    func appSkin(_ skin: AppSkin) -> some View {
        environment(\.appSkin, skin)
    }
}
