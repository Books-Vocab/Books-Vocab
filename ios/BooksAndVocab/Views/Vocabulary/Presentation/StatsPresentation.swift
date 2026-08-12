//
//  StatsPresentation.swift
//  Books & Vocab
//
//  統計頁面的資料計算邏輯。
//

import Foundation

enum StatsPresentation {
    struct ForecastBucket: Identifiable {
        let id: String
        let label: String
        let count: Int
    }

    struct Summary {
        let totalCards: Int
        let reviewedToday: Int
        let dueToday: Int
        let currentStreak: Int
        let longestStreak: Int
        let activity: [String: Int]
        let forecast: [ForecastBucket]
        let heatmapThresholds: [Int]
    }

    enum GraphThumbnailBodyKind: Equatable {
        case loading
        case empty
        case graph
    }

    static func graphThumbnailBodyKind(linksLoaded: Bool, nodeCount: Int) -> GraphThumbnailBodyKind {
        guard linksLoaded else { return .loading }
        return nodeCount == 0 ? .empty : .graph
    }

    private static func compactDayLabel(
        for date: Date,
        clock: ReviewCalendarClock
    ) -> String {
        LocaleAwareFormatter.shared.string(
            from: date,
            template: "Md",
            timeZone: clock.timeZone
        )
    }

    static func buildSummary(
        from entries: [VocabularyEntry],
        reviewRecords: [ReviewRecord],
        forecastDays: Int = 14,
        clock: ReviewCalendarClock
    ) -> Summary {
        // shouldAppearInKnowledgeList == isSynced && !delete && !isArchived.
        // Archived entries must NOT inflate the review forecast / stats.
        let synced = entries.filter(\.shouldAppearInKnowledgeList)

        // Forecast
        var forecastMap: [String: Int] = [:]
        let todayKey = clock.dayKey(for: clock.now)
        for entry in synced {
            let key = clock.dayKey(for: entry.nextReviewAt)
            if key <= todayKey {
                forecastMap[todayKey, default: 0] += 1
            } else {
                forecastMap[key, default: 0] += 1
            }
        }

        var forecast: [ForecastBucket] = []
        for offset in 0..<forecastDays {
            guard let date = clock.calendar.date(
                byAdding: .day,
                value: offset,
                to: clock.startOfToday
            ) else { continue }
            let key = clock.dayKey(for: date)
            let label: String
            switch offset {
            case 0: label = "今天".localized
            case 1: label = "明天".localized
            default:
                label = Self.compactDayLabel(for: date, clock: clock)
            }
            forecast.append(ForecastBucket(id: key, label: label, count: forecastMap[key] ?? 0))
        }

        let activity = ReviewActivityLog.activity(for: 180, records: reviewRecords, clock: clock)

        // Compute adaptive heatmap thresholds from activity data
        let nonZeroCounts = activity.values.filter { $0 > 0 }.sorted()
        let heatmapThresholds: [Int]
        if nonZeroCounts.count < 4 {
            heatmapThresholds = [1, 2, 3]  // simple fallback
        } else {
            let p25 = nonZeroCounts[nonZeroCounts.count / 4]
            let p50 = nonZeroCounts[nonZeroCounts.count / 2]
            let p75 = nonZeroCounts[nonZeroCounts.count * 3 / 4]
            heatmapThresholds = [p25, p50, p75]
        }

        let streakResult = ReviewActivityLog.streaks(records: reviewRecords, clock: clock)

        return Summary(
            totalCards: synced.count,
            reviewedToday: ReviewActivityLog.reviewedToday(records: reviewRecords, clock: clock),
            dueToday: forecastMap[todayKey] ?? 0,
            currentStreak: streakResult.current,
            longestStreak: streakResult.longest,
            activity: activity,
            forecast: forecast,
            heatmapThresholds: heatmapThresholds
        )
    }

}
