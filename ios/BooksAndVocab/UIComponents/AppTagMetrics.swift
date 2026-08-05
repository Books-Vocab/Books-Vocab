import SwiftUI

/// Tag / chip 內距 — shell 層共用（AppTag、TodayReview 字數徽章）。
/// 形狀不在此定義：tag 一律走 `AppRoundedRect(roundness: AppRoundness.pill)`。
enum AppTagMetrics {
    static let horizontalPadding: CGFloat = 10
    static let verticalPadding: CGFloat = 5
}
