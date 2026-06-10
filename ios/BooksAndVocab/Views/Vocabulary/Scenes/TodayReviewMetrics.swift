import SwiftUI

/// Today Review 功能專用版面參數（摺頁卡片、字數徽章、swipe hint）。
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
    /// 複習卡正面單字 ≤ 12 字時的字體大小
    static let counterFontSizeXLarge: CGFloat = 30

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

    // ── 從 AppSkin.Metrics 遷出(Phase 4 of boundary rectify)─────────

    // MARK: Progress(in原 baseSpacing,搬入此 feature)
    static let progressBarGap: CGFloat = 5

    // MARK: Card layout(不與既有 cardBorderOpacity / cardBorderActiveOpacity 合併語意)
    static let cardHorizontalInset: CGFloat = AppSpacing.s2
    static let cardTopInset: CGFloat = AppSpacing.s2
    static let cardBottomInset: CGFloat = AppSpacing.s2

    // MARK: TopBar
    static let topBarHorizontalInset: CGFloat = 20
    static let topBarTopInset: CGFloat = 10
    static let topBarBottomInset: CGFloat = 6

    // MARK: Toolbar
    static let toolbarHorizontalInset: CGFloat = 20
    static let toolbarVerticalInset: CGFloat = 12

    // MARK: Fold layout(不與既有 foldJoinRadius / paperFoldOffsetY 幾何欄位合併)
    static let foldPadding: CGFloat = 28
    static let foldSectionSpacing: CGFloat = 24
    static let foldHintBottomInset: CGFloat = 22

    // MARK: Card / Action min size
    static let frontMinHeight: CGFloat = 120
    static let answerMinHeight: CGFloat = 188
    static let actionMinWidth: CGFloat = 92
    static let chevronButtonSize: CGFloat = 30

    // MARK: Height ratio / Swipe geometry
    static let frontHeightRatio: CGFloat = 0.22
    static let swipeThreshold: CGFloat = 100
    static let swipeMaxRotation: Double = 12
    static let swipeOpacityFloor: Double = 0.3

    // MARK: Autoplay player
    static let autoplayProgressBarHeight: CGFloat = 4
    static let autoplayProgressBarBottomGap: CGFloat = AppSpacing.s2
    static let autoplaySpeedPillHeight: CGFloat = 28
    static let autoplaySpeedPillHorizontalPadding: CGFloat = AppSpacing.s3
}
