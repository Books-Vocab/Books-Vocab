//
//  StatsPresentation.swift
//  BooksBrowser
//
//  統計頁面的資料計算邏輯。
//

import Foundation

enum StatsPresentation {
    struct ForecastBucket: Identifiable {
        let id: String   // 日期 key 或 label
        let label: String
        let count: Int
    }

    struct Summary {
        let totalCards: Int
        let reviewedToday: Int
        let dueToday: Int
        let currentStreak: Int
        let longestStreak: Int
        let activity: [String: Int]       // "yyyy-MM-dd" -> count
        let forecast: [ForecastBucket]
    }

    private static let calendar = Calendar.current

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    static func buildSummary(from entries: [VocabularyEntry]) -> Summary {
        let synced = entries.filter { $0.isSynced && $0.syncAction != .delete }
        let now = Date()

        // Forecast: group nextReviewAt into daily buckets for next 14 days
        var forecastMap: [String: Int] = [:]
        let todayKey = dayFormatter.string(from: now)
        for entry in synced {
            let reviewDate = entry.nextReviewAt
            let key = dayFormatter.string(from: reviewDate)
            if key <= todayKey {
                forecastMap[todayKey, default: 0] += 1
            } else {
                forecastMap[key, default: 0] += 1
            }
        }

        let forecastDays = 14
        var forecast: [ForecastBucket] = []
        for offset in 0..<forecastDays {
            guard let date = calendar.date(byAdding: .day, value: offset, to: now) else { continue }
            let key = dayFormatter.string(from: date)
            let label: String
            switch offset {
            case 0: label = "今天"
            case 1: label = "明天"
            default:
                let f = DateFormatter()
                f.dateFormat = "M/d"
                label = f.string(from: date)
            }
            forecast.append(ForecastBucket(
                id: key,
                label: label,
                count: forecastMap[key] ?? 0
            ))
        }

        let dueToday = forecastMap[todayKey] ?? 0
        let activity = ReviewActivityLog.activity(for: 180)

        return Summary(
            totalCards: synced.count,
            reviewedToday: ReviewActivityLog.reviewedToday(),
            dueToday: dueToday,
            currentStreak: ReviewActivityLog.currentStreak(),
            longestStreak: ReviewActivityLog.longestStreak(),
            activity: activity,
            forecast: forecast
        )
    }
}
