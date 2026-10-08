import CoreGraphics
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

    /// 峰值探針的 id（見 `TodayReviewSwipeMarkerPeak`）。
    var peakAccessibilityID: String { "todayReview.swipeMarkerPeak.\(rawValue)" }

    /// 對應 `TodayReviewFling.markerOpacity` 的方向符號（右滑記得 +1、左滑忘記 -1）。
    var direction: CGFloat { self == .remembered ? 1 : -1 }

    /// accessibilityValue = 當下不透明度（0 … 1），固定兩位小數。UITest 以數值解析；
    /// 固定格式讓「歸 0 無殘影」可用 `"0.00"` 精確比對。
    static func accessibilityValue(opacity: Double) -> String {
        String(format: "%.2f", max(0, min(opacity, 1)))
    }
}

/// 一次手勢（拖動 → 放開 → 回彈 / 飛出，或按鈕 fling）期間各標記達到的最大強度。
///
/// 存在理由：XCUITest 的 press-drag 在手指放開後才返回，UITest 無法在「按住」時取樣標記；
/// 放開後標記已歸 0（或隨卡片飛出），單看終態的斷言對「標記從未出現」同樣綠燈。峰值在手勢
/// 入口（`DragGesture.onChanged` 與 `flingCard`）累計、放開後保留到下一次手勢開始，
/// UITest 於放開後讀取即可斷言「曾出現多強」，與終態歸 0 搭配成完整的出現 → 消失判準。
/// 只在 UITest 進程累計與暴露；純值，由單元測試鎖定。
struct TodayReviewSwipeMarkerPeak: Equatable {
    var remembered: Double = 0
    var forgot: Double = 0

    static let zero = TodayReviewSwipeMarkerPeak()

    func value(for kind: TodayReviewSwipeMarkerKind) -> Double {
        kind == .remembered ? remembered : forgot
    }

    /// 記錄 offset 由 `previousOffset` 走到 `newOffset`。`previousOffset == 0` 視為新手勢起點
    /// （拖動首幀、按鈕 fling）→ 先清空再累計；手勢中途（拖動後放開 fling）則沿用累計取 max。
    func recording(from previousOffset: CGFloat, to newOffset: CGFloat, threshold: CGFloat) -> TodayReviewSwipeMarkerPeak {
        var next = previousOffset == 0 ? .zero : self
        next.remembered = max(next.remembered, TodayReviewFling.markerOpacity(swipeOffset: newOffset, threshold: threshold, direction: 1))
        next.forgot = max(next.forgot, TodayReviewFling.markerOpacity(swipeOffset: newOffset, threshold: threshold, direction: -1))
        return next
    }
}
