//
//  StatsPresentation.swift
//  Books & Vocab
//
//  統計頁面的資料計算邏輯。
//

import Foundation
import SwiftUI

private struct StatsProjectionClockKey: EnvironmentKey {
    static let defaultValue = StatsProjectionClock(
        now: Date(timeIntervalSince1970: 0),
        calendar: Calendar(identifier: .gregorian)
    )
}

extension EnvironmentValues {
    var statsProjectionClock: StatsProjectionClock {
        get { self[StatsProjectionClockKey.self] }
        set { self[StatsProjectionClockKey.self] = newValue }
    }
}

enum StatsPresentation {
    struct ForecastBucket: Identifiable, Equatable {
        let id: String
        let label: String
        let count: Int
    }

    /// All values that influence the Overview projection travel through one
    /// explicit input bundle. Keeping the clock beside the records prevents a
    /// fixture from accidentally mixing seeded data with a wall-clock forecast.
    struct Inputs {
        let entries: [VocabularyEntry]
        let reviewRecords: [ReviewRecord]
        let forecastDays: Int
        let clock: StatsProjectionClock

        init(
            entries: [VocabularyEntry],
            reviewRecords: [ReviewRecord],
            forecastDays: Int = 14,
            clock: StatsProjectionClock
        ) {
            self.entries = entries
            self.reviewRecords = reviewRecords
            self.forecastDays = forecastDays
            self.clock = clock
        }
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

        func formattedCount(_ value: Int) -> String {
            LocaleAwareFormatter.shared.string(from: NSNumber(value: value))
        }
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

    private static func compactDayLabel(for date: Date) -> String {
        LocaleAwareFormatter.shared.string(from: date, template: "Md")
    }

    static func buildSummary(
        from entries: [VocabularyEntry],
        reviewRecords: [ReviewRecord],
        forecastDays: Int = 14,
        now: Date = Date()
    ) -> Summary {
        project(Inputs(
            entries: entries,
            reviewRecords: reviewRecords,
            forecastDays: forecastDays,
            clock: StatsProjectionClock(now: now, calendar: Calendar.autoupdatingCurrent)
        ))
    }

    static func buildSummary(
        from entries: [VocabularyEntry],
        reviewRecords: [ReviewRecord],
        forecastDays: Int = 14,
        clock: StatsProjectionClock
    ) -> Summary {
        project(Inputs(
            entries: entries,
            reviewRecords: reviewRecords,
            forecastDays: forecastDays,
            clock: clock
        ))
    }

    static func project(
        entries: [VocabularyEntry],
        reviewRecords: [ReviewRecord],
        forecastDays: Int = 14,
        clock: StatsProjectionClock
    ) -> Summary {
        project(Inputs(
            entries: entries,
            reviewRecords: reviewRecords,
            forecastDays: forecastDays,
            clock: clock
        ))
    }

    static func project(_ inputs: Inputs) -> Summary {
        // shouldAppearInKnowledgeList == isSynced && !delete && !isArchived.
        // Archived entries must NOT inflate the review forecast / stats.
        let synced = inputs.entries.filter(\.shouldAppearInKnowledgeList)

        // Forecast
        var forecastMap: [String: Int] = [:]
        let todayKey = inputs.clock.dayKey(inputs.clock.now)
        for entry in synced {
            let key = inputs.clock.dayKey(entry.nextReviewAt)
            if key <= todayKey {
                forecastMap[todayKey, default: 0] += 1
            } else {
                forecastMap[key, default: 0] += 1
            }
        }

        var forecast: [ForecastBucket] = []
        for offset in 0..<inputs.forecastDays {
            guard let date = inputs.clock.date(
                byAdding: .day,
                value: offset,
                to: inputs.clock.now
            ) else { continue }
            let key = inputs.clock.dayKey(date)
            let label: String
            switch offset {
            case 0: label = "今天".localized
            case 1: label = "明天".localized
            default:
                label = Self.compactDayLabel(for: date)
            }
            forecast.append(ForecastBucket(id: key, label: label, count: forecastMap[key] ?? 0))
        }

        let activity = ReviewActivityLog.activity(
            for: 180,
            records: inputs.reviewRecords,
            clock: inputs.clock
        )

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

        let streakResult = ReviewActivityLog.streaks(
            records: inputs.reviewRecords,
            clock: inputs.clock
        )

        return Summary(
            totalCards: synced.count,
            reviewedToday: ReviewActivityLog.reviewedToday(
                records: inputs.reviewRecords,
                clock: inputs.clock
            ),
            dueToday: forecastMap[todayKey] ?? 0,
            currentStreak: streakResult.current,
            longestStreak: streakResult.longest,
            activity: activity,
            forecast: forecast,
            heatmapThresholds: heatmapThresholds
        )
    }
}
