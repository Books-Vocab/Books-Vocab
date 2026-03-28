//
//  AppDateFormatters.swift
//  BooksBrowser
//
//  統一的 DateFormatter / ISO8601DateFormatter 定義，避免重複建立。
//

import Foundation

enum AppDateFormatters {

    // MARK: - Day Key (yyyy-MM-dd)

    /// "yyyy-MM-dd" 格式，用於 ReviewRecord.dayKey、活動統計、日曆等。
    static let dayKey: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    // MARK: - ISO 8601

    /// ISO 8601 含小數秒（withInternetDateTime + withFractionalSeconds）。
    static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// ISO 8601 不含小數秒（withInternetDateTime only），作為解析 fallback。
    static let iso8601Simple: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// 先嘗試含小數秒，再 fallback 不含小數秒。
    static func parseISO8601(_ string: String) -> Date? {
        iso8601.date(from: string) ?? iso8601Simple.date(from: string)
    }
}
