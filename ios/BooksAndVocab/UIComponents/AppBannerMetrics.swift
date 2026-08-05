import SwiftUI

/// Inline banner 版面參數 — shell 層共用（AppBanner、Welcome）。
enum AppBannerMetrics {
    static let spacing: CGFloat = 10
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 8

    /// Banner 內容的最小高度：給 icon + 最多兩行文字留呼吸，也讓「有 action」與
    /// 「沒有 action」的 banner 維持一致量體。
    static let minHeight: CGFloat = 44

    /// Action glyph 的點擊範圍（HIG 最小 44pt）。glyph 本身仍是 caption 大小 ——
    /// 放大的是 hit area，不是視覺重量。
    static let actionHitTarget: CGFloat = 44

    /// 有 action 時右緣由 button 的 hit target 撐開，再補滿 padding 會讓 glyph
    /// 離邊過遠；沒有 action 時才補回對稱的水平留白。
    static func trailingPadding(hasActions: Bool) -> CGFloat {
        hasActions ? spacing / 2 : horizontalPadding
    }

    // `AppBanner` 自身已改吃語意 token（`successBg` / `warningBg`）＋無邊框；
    // 以下兩個 opacity 仍由 `WelcomeView` 的 accent pill 使用，故保留。
    static let borderOpacity: Double = 0.2
    static let backgroundOpacity: Double = 0.08
}
