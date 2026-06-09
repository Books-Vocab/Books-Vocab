//
//  CompactTimeFormatting.swift
//  Books & Vocab
//
//  詞彙複習進度的緊湊時間標籤格式化 —
//  WordRowPresentation 與 WordDetailPresentation 共用，避免兩處邏輯 drift。
//

import Foundation

extension TimeInterval {
    /// 緊湊複習進度標籤：< 1h → "Nm"（至少 1m）；< 1d → "N.Nh"/"Nh"；否則 "N.Nd"/"Nd"。
    var compactReviewLabel: String {
        let seconds = max(0, self)
        let minute: TimeInterval = 60
        let hour: TimeInterval = 3600
        let day: TimeInterval = 86_400

        if seconds < hour {
            let minutes = max(1, Int((seconds / minute).rounded()))
            return "\(minutes)m"
        }
        if seconds < day {
            let hours = seconds / hour
            return hours < 10 ? hours.singleDecimalString + "h" : "\(Int(hours.rounded()))h"
        }
        let days = seconds / day
        return days < 10 ? days.singleDecimalString + "d" : "\(Int(days.rounded()))d"
    }
}

extension Double {
    /// 以「小時」為單位的緊湊標籤（小時數 → compactReviewLabel）。
    var compactHourLabel: String {
        (self * 3600).compactReviewLabel
    }

    /// 一位小數字串；整數則去除小數點（如 2.0 → "2"、2.5 → "2.5"）。
    var singleDecimalString: String {
        let rounded = (self * 10).rounded() / 10
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(format: "%.1f", rounded)
    }
}
