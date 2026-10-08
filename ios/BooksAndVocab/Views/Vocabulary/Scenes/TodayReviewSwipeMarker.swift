import Foundation

// MARK: - Swipe Marker 的 UITest 契約（#2045 — 純邏輯）
//
// 方向標記本體在 `TodayReviewSwipeDeck.swift`（`swipeMarkers`）。這裡只放 id 與強度值
// 的格式，讓 App 與 UITest page object 對同一份契約，且可被單元測試鎖定。

/// 卡面上的兩個方向標記。
enum TodayReviewSwipeMarkerKind: String, CaseIterable {
    case remembered
    case forgot

    var accessibilityID: String { "todayReview.swipeMarker.\(rawValue)" }

    /// accessibilityValue = 當下不透明度（0 … 1），固定兩位小數。UITest 以數值解析；
    /// 固定格式讓「歸 0 無殘影」可用 `"0.00"` 精確比對。
    static func accessibilityValue(opacity: Double) -> String {
        String(format: "%.2f", max(0, min(opacity, 1)))
    }
}
