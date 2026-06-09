//
//  AppDateFormatters.swift
//  Books & Vocab
//
//  統一的 DateFormatter / ISO8601DateFormatter 定義，避免重複建立。
//
//  i18n-allow: locale-neutral
//  All formatters here pin Locale to en_US_POSIX with ASCII-only format
//  tokens (yyyy-MM-dd, HH:mm:ss) or use ISO8601DateFormatter (wire format).
//  Output is intentionally locale-invariant — used for day keys, internal
//  storage keys, and wire serialization, never for user-facing display.
//

import Foundation

enum AppDateFormatters {

    // MARK: - Time Only (HH:mm:ss)

    static let hhmmss: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

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
