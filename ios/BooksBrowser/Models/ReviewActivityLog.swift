//
//  ReviewActivityLog.swift
//  BooksBrowser
//
//  輕量每日複習活動記錄，用 UserDefaults 持久化。
//  記錄每天的複習次數，用於 heatmap 和 streak 計算。
//

import Foundation

enum ReviewActivityLog {
    private static let storageKey = "review_activity_log"
    private static let calendar = Calendar.current

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    // MARK: - Public API

    static func recordReview(count: Int = 1, on date: Date = Date()) {
        var log = loadLog()
        let key = dayFormatter.string(from: date)
        log[key] = (log[key] ?? 0) + count
        saveLog(log)
    }

    static func activity(for days: Int = 180) -> [String: Int] {
        let log = loadLog()
        let today = Date()
        var result: [String: Int] = [:]
        for offset in 0..<days {
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { continue }
            let key = dayFormatter.string(from: date)
            if let count = log[key] {
                result[key] = count
            }
        }
        return result
    }

    static func currentStreak() -> Int {
        let log = loadLog()
        let today = Date()
        var streak = 0
        for offset in 0... {
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { break }
            let key = dayFormatter.string(from: date)
            if let count = log[key], count > 0 {
                streak += 1
            } else {
                // 今天還沒複習不算斷連
                if offset == 0 { continue }
                break
            }
        }
        return streak
    }

    static func longestStreak() -> Int {
        let log = loadLog()
        guard !log.isEmpty else { return 0 }

        let sortedDays = log.keys.sorted()
        guard let firstDay = sortedDays.first,
              let firstDate = dayFormatter.date(from: firstDay),
              let lastDay = sortedDays.last,
              let lastDate = dayFormatter.date(from: lastDay) else { return 0 }

        let totalDays = calendar.dateComponents([.day], from: firstDate, to: lastDate).day ?? 0
        var longest = 0
        var current = 0
        for offset in 0...totalDays {
            guard let date = calendar.date(byAdding: .day, value: offset, to: firstDate) else { continue }
            let key = dayFormatter.string(from: date)
            if let count = log[key], count > 0 {
                current += 1
                longest = max(longest, current)
            } else {
                current = 0
            }
        }
        return longest
    }

    static func reviewedToday() -> Int {
        let key = dayFormatter.string(from: Date())
        return loadLog()[key] ?? 0
    }

    // MARK: - Storage

    private static func loadLog() -> [String: Int] {
        UserDefaults.standard.dictionary(forKey: storageKey) as? [String: Int] ?? [:]
    }

    private static func saveLog(_ log: [String: Int]) {
        // 只保留最近 365 天
        let cutoff = calendar.date(byAdding: .day, value: -365, to: Date()) ?? Date()
        let cutoffKey = dayFormatter.string(from: cutoff)
        let trimmed = log.filter { $0.key >= cutoffKey }
        UserDefaults.standard.set(trimmed, forKey: storageKey)
    }
}
