//
//  AppMetrics.swift
//  BooksBrowser
//
//  統一的間距、圓角與陰影參數 (Design System Tokens)
//

import SwiftUI

enum AppMetrics {
    // ── Spacing (留白與呼吸感) ────────────────────────────────────────────────────
    static let spacingMicro: CGFloat = 2
    static let spacingTiny: CGFloat = 3
    static let spacingExtraSmall: CGFloat = 4
    static let spacingSmall: CGFloat = 8
    static let spacingCompact: CGFloat = 12

    // ── Divider / Separator ───────────────────────────────────────────────────
    static let dividerThin: CGFloat = 0.5
    static let dividerStandard: CGFloat = 1
    static let spacingMedium: CGFloat = 16
    static let spacingLarge: CGFloat = 24
    static let spacingExtraLarge: CGFloat = 32
    static let spacingXXL: CGFloat = 48
    
    // ── Glass Stroke (iOS <26 fallback) ─────────────────────────────────────────
    static let glassStrokeOpacity: Double = 0.12

    // ── Corner Radius (圓角) ───────────────────────────────────────────────────
    static let cornerRadiusSmall: CGFloat = 8
    static let cornerRadiusMedium: CGFloat = 12
    static let cornerRadiusLarge: CGFloat = 16
    static let cornerRadiusXLarge: CGFloat = 18
    static let cornerRadiusExtraLarge: CGFloat = 24
    static let cornerRadiusGlass: CGFloat = 30

    // ── Control Dimensions ──────────────────────────────────────────────────────
    static let iconButtonSize: CGFloat = 52

    // ── Loading Indicator ─────────────────────────────────────────────────
    static let loadingIndicatorScaleMedium: CGFloat = 0.8
    static let loadingIndicatorScaleSmall: CGFloat = 0.7

    // ── Card Dimensions ─────────────────────────────────────────────────────────
    static let cardMinHeight: CGFloat = 420
    static let heroCardPadding: CGFloat = 34
    static let sectionInset: CGFloat = 20
}

extension AppMetrics {
    enum MacDetailPanel {
        static let defaultWidth: CGFloat = 420
        static let minWidth: CGFloat = 280
        static let maxWidth: CGFloat = 600
        static let leftMinWidth: CGFloat = 300
        static let hitAreaWidth: CGFloat = 8
    }
}

enum AppTagMetrics {
    static let horizontalPadding: CGFloat = 10
    static let verticalPadding: CGFloat = 5
    static let cornerRadius: CGFloat = 6
}

enum AppGhostButtonMetrics {
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 10
}

enum AppBannerMetrics {
    static let spacing: CGFloat = 10
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 8
    static let borderOpacity: Double = 0.2
    static let backgroundOpacity: Double = 0.08
}

enum AppWelcomeMetrics {
    static let iconBottomPadding: CGFloat = 12
    static let pageHeight: CGFloat = 240
    static let featureIconFrame: CGFloat = 64
    static let subtitleHorizontalPadding: CGFloat = 40
    static let bottomPadding: CGFloat = 40
}

enum AppBookshelfMetrics {
    static let placeholderTitleHorizontalPadding: CGFloat = 12
    static let coverHeightCompact: CGFloat = 210
    static let coverHeightRegular: CGFloat = 260
    static let coverCornerRadius: CGFloat = 6
    static let coverShadowOpacity: Double = 0.10
    static let coverShadowRadius: CGFloat = 6
    static let coverShadowY: CGFloat = 3
    static let progressBarHeight: CGFloat = 4
    static let progressBarAccentOpacity: Double = 0.55
    static let progressBarSpacing: CGFloat = 6
    static let loadingOverlayPadding: CGFloat = 28
    static let badgePadding: CGFloat = 6
    static let badgeForeground: Color = .white
}

enum AppSettingsMetrics {
    static let accountHeroSpacing: CGFloat = 10
    static let accountActionSpacing: CGFloat = 10
    static let accountButtonSpacing: CGFloat = 12
    static let accountRowSpacing: CGFloat = 14
    static let accountAvatarSize: CGFloat = 46
    static let socialBadgeSize: CGFloat = 22
    static let reviewModeTileGap: CGFloat = 10
    static let reviewStepperGap: CGFloat = 12
    static let reviewValueMinWidth: CGFloat = 52
}

enum AppOverlayMetrics {
    static let linkedCardLayerOffsetX: CGFloat = 8
    static let linkedCardLayerOffsetY: CGFloat = 10
    static let linkedCardLayerShrinkStep: CGFloat = 18
}

enum AppMotion {
    static let quickEaseOut = Animation.easeOut(duration: 0.15)
    static let controlEaseOut = Animation.easeOut(duration: 0.14)
    static let chipSelectionEaseOut = Animation.easeOut(duration: 0.18)
    static let progressLinear = Animation.linear(duration: 0.1)
    static let standardSpring = Animation.spring(response: 0.3, dampingFraction: 0.75)
    static let emphasizedSpring = Animation.spring(response: 0.35, dampingFraction: 0.8)
    static let relaxedSpring = Animation.spring(response: 0.4, dampingFraction: 0.8)
    static let systemSpring = Animation.spring()
    static let modalSwapSpring = Animation.spring(response: 0.45, dampingFraction: 0.85)
    static let buttonSpring = Animation.spring(response: 0.35, dampingFraction: 0.7, blendDuration: 0)
    static let breathing = Animation.easeInOut(duration: 2.8).repeatForever(autoreverses: true)
    static let reviewRevealSpring = Animation.spring(response: 0.42, dampingFraction: 0.88)
    static let reviewNavigationSpring = Animation.spring(response: 0.32, dampingFraction: 0.86)
    static let reviewCardSwapSpring = Animation.spring(response: 0.34, dampingFraction: 0.84)
    static let stackPromotionSpring = Animation.spring(response: 0.25, dampingFraction: 0.78)

    // Swipe gesture
    static let swipeDismissSpring = Animation.spring(response: 0.35, dampingFraction: 0.78)
    static let swipeSnapBackSpring = Animation.spring(response: 0.4, dampingFraction: 0.82)

    // MARK: - Micro-interaction Springs
    /// 卡片甩出畫面（高剛性快速飛離）
    static let swipeFlingSpring = Animation.interpolatingSpring(stiffness: 500, damping: 28)
    /// 回饋按鈕跟隨 swipe 強度（快速貼合手勢）
    static let feedbackButtonSpring = Animation.spring(response: 0.22, dampingFraction: 0.72)
    /// 拖拽中卡片跟手（極低延遲、高阻尼，貼合手指）
    static let swipeTrackingSpring = Animation.interactiveSpring(response: 0.14, dampingFraction: 0.86)

    // --- Visual polish tokens ---
    static let pressFeedback: Animation = .spring(response: 0.25, dampingFraction: 0.65)
    static let contentReveal: Animation = .spring(response: 0.35, dampingFraction: 0.82)
    static let celebrationBounce: Animation = .spring(response: 0.4, dampingFraction: 0.55)
    static let sheetContentAppear: Animation = .spring(response: 0.3, dampingFraction: 0.78)
    static let swipeRowSnap: Animation = .spring(response: 0.3, dampingFraction: 0.75)

    // Semantic motion tokens for shared interaction patterns.
    static let panelState = standardSpring
    static let panelSnapBack = standardSpring
    static let headerState = relaxedSpring
    static let phaseChange = emphasizedSpring
    static let feedbackPulse = systemSpring
    static let contentFade = quickEaseOut
    static let loadingState = quickEaseOut
    static let listReorder = standardSpring
    static let chipSelect = chipSelectionEaseOut
}

extension AnyTransition {
    static let overlayFade = AnyTransition.opacity
    static let readerPanelReveal = AnyTransition.move(edge: .bottom).combined(with: .opacity)
    static let headerSwap = AnyTransition.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity)
    static let feedbackBadge = AnyTransition.scale(scale: 0.8).combined(with: .opacity)
    static let linkedOverlayCard = AnyTransition.scale(scale: 0.96).combined(with: .opacity)
    static let modalSwap = AnyTransition.asymmetric(
        insertion: .scale(scale: 0.97).combined(with: .opacity),
        removal: .opacity
    )
    static let statusRowReveal = AnyTransition.move(edge: .top).combined(with: .opacity)
    /// 內容替換（適用於 list item、card 內容切換）
    static let contentSwap: AnyTransition = .opacity.combined(with: .scale(scale: 0.97))
    /// Banner / toast 從頂部滑入
    static let bannerReveal: AnyTransition = .move(edge: .top).combined(with: .opacity)
    /// 書架卡片進出（微縮放 + 淡出）
    static let bookshelfCard: AnyTransition = .opacity.combined(with: .scale(scale: 0.96))
    /// 列表項目簡潔過渡
    static let listItemFade: AnyTransition = .opacity.animation(AppMotion.contentFade)
    static let listInsert: AnyTransition = .opacity.combined(with: .offset(y: 8))
    static let listRemove: AnyTransition = .opacity
    /// Sync phase 切換（blur replace）
    static let phaseBlurSwap: AnyTransition = .init(.blurReplace)
    /// 選取模式 checkbox 顯現
    static let selectionReveal: AnyTransition = .scale.combined(with: .opacity)
}

enum TodayReviewMetrics {
    // ── Stack 動畫 ──────────────────────────────────────────────────
    /// 卡片升起時的 Y 偏移（promote 動畫）
    static let promoteYOffset: CGFloat = 22
    /// 卡片升起時的縮放比例
    static let promoteScale: CGFloat = 0.96

    // ── 展開提示 ───────────────────────────────────────────────────
    /// 展開提示出現時，卡片右側的內縮量（為提示圖示騰出空間）
    static let expandHintTrailingPadding: CGFloat = 40

    // ── Tag / Chip ──────────────────────────────────────────────────
    /// 字數徽章水平 padding（對齊 AppTagMetrics）
    static let tagHorizontalPadding: CGFloat = AppTagMetrics.horizontalPadding
    /// 字數徽章垂直 padding（對齊 AppTagMetrics）
    static let tagVerticalPadding: CGFloat = AppTagMetrics.verticalPadding
    /// 字數徽章圓角
    static let tagCornerRadius: CGFloat = 6

    // ── Opacity ─────────────────────────────────────────────────────
    /// 卡片邊框線條透明度（idle 狀態）
    static let cardBorderOpacity: Double = 0.45
    /// 卡片邊框線條透明度（fold 狀態 / active）
    static let cardBorderActiveOpacity: Double = 0.72
    /// 淡化文字透明度（quaternaryText 用）
    static let dimTextOpacity: Double = 0.72
    /// 填充色透明度（divider 用）
    static let dividerFillOpacity: Double = 0.85

    // ── Font Size ───────────────────────────────────────────────────
    /// 字數 > 20 時的字體大小
    static let counterFontSizeCompact: CGFloat = 22
    /// 字數 > 12 時的字體大小
    static let counterFontSizeMedium: CGFloat = 26
    /// 字數 ≤ 12 時的字體大小（最大）
    static let counterFontSizeLarge: CGFloat = 28

    // ── Swipe Hint ──────────────────────────────────────────────────
    /// Swipe hint 標籤字體大小（忘記/記得）
    static let swipeHintFontSize: CGFloat = 34

    // ── Fold Geometry ──────────────────────────────────────────────
    /// 摺頁接合處的圓角（非首尾段的內側圓角）
    static let foldJoinRadius: CGFloat = 4
    /// 摺頁動畫的 Y 軸偏移量
    static let paperFoldOffsetY: CGFloat = 12

    // ── Micro Adjustment ────────────────────────────────────────────
    /// 卡片疊層微調（消除 1pt 視覺縫隙）
    static let stackLayerMicroOffset: CGFloat = -1
    /// 答案展開提示區塊的頂部微調
    static let answerHintTopPadding: CGFloat = 2
}

enum AppShadows {
    // ── iOS 26 Liquid Glass & Morandi Paper Shadows ───────────────────────────
    // 極低對比度的大範圍陰影，模擬實體紙張微微浮起的效果
    static let paperFloatOpacity: Double = 0.04
    static let paperFloatRadius: CGFloat = 20
    static let paperFloatY: CGFloat = 8
    
    // 輕微的按下或緊貼陰影
    static let paperPressedOpacity: Double = 0.02
    static let paperPressedRadius: CGFloat = 4
    static let paperPressedY: CGFloat = 2

    // MARK: - 封面/卡片微陰影（書架封面、小卡片）
    static let coverOpacity: Double = 0.06
    static let coverRadius: CGFloat = 4
    static let coverY: CGFloat = 2

    // MARK: - 控制元件微陰影（Badge、小按鈕）
    static let controlOpacity: Double = 0.18
    static let controlRadius: CGFloat = 2
    static let controlY: CGFloat = 1

    // MARK: - 工具列陰影（SelectionToolbar 等浮動 bar）
    static let toolbarDropOpacity: Double = 0.10
    static let toolbarDropRadius: CGFloat = 8
    static let toolbarDropY: CGFloat = -2

    // MARK: - 面板陰影（Reader overlay、大面板）
    static let panelOpacity: Double = 0.70
    static let panelRadius: CGFloat = 28
    static let panelY: CGFloat = 14

    // MARK: - Toast 微陰影（頂部浮動膠囊）
    static let toastOpacity: Double = 0.08
    static let toastRadius: CGFloat = 8
    static let toastY: CGFloat = 4
}

// MARK: - AppMotion Convenience Modifiers
extension View {
    func animatePhaseChange<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.phaseChange, value: value)
    }
    func animateSpring<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.standardSpring, value: value)
    }
    func animateContentFade<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.contentFade, value: value)
    }
    func animateControl<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.controlEaseOut, value: value)
    }
}
