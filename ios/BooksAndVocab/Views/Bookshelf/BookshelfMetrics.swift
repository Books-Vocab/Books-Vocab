import SwiftUI

/// 書架功能專用版面參數（封面、進度條、載入覆蓋、徽章）。
enum AppBookshelfMetrics {
    static let placeholderTitleHorizontalPadding: CGFloat = 12
    static let coverHeightCompact: CGFloat = 210
    static let coverHeightRegular: CGFloat = 260
    /// 書封圓度。舊值是絕對 10pt；compact 書封短邊 ≈155–165pt（grid 欄寬，
    /// 非固定 140pt——寬度由 `LayoutMode.bookshelfGridItem` 的 `.adaptive(150...200)` 決定），
    /// `card` 0.15 得 r ≈ 11.7–12.3，**比舊值圓約 20%**；iPad regular 欄寬可達 240 → r = 18。
    static let coverRoundness: CGFloat = AppRoundness.card
    static let progressBarHeight: CGFloat = 4
    static let progressBarSpacing: CGFloat = 6
    static let loadingOverlayPadding: CGFloat = 28
    static let loadingProgressWidth: CGFloat = 180
    static let badgePadding: CGFloat = 6
    static let badgeForeground: Color = .white
}
