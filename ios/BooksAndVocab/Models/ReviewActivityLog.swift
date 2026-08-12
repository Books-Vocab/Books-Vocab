//
//  ReviewActivityLog.swift
//  Books & Vocab
//
//  複習活動查詢工具。資料來源為 SwiftData ReviewRecord。
//

import Foundation
import SwiftData

enum ReviewActivityLog {
    // MARK: - Record

    @MainActor
    static func recordReview(
        word: String,
        entryID: UUID?,
        feedback: ReviewFeedback,
        context: ModelContext,
        notebookId: String = "default"
    ) {
        let record = ReviewRecord(
            word: word,
            entryID: entryID,
            feedback: feedback == .remembered ? 1 : 0
        )
        record.notebookId = notebookId
        context.insert(record)
    }

    // MARK: - Queries (from SwiftData)

    /// `now` 可注入（catalog / 測試凍結時鐘）；預設牆鐘。
    static func activity(for days: Int = 180, records: [ReviewRecord], now: Date = Date()) -> [String: Int] {
        let clock = StatsProjectionClock(now: now, calendar: Calendar.autoupdatingCurrent)
        return activity(for: days, records: records, clock: clock)
    }

    static func activity(
        for days: Int = 180,
        records: [ReviewRecord],
        clock: StatsProjectionClock
    ) -> [String: Int] {
        let cutoff = clock.date(byAdding: .day, value: -days, to: clock.now) ?? clock.now
        let cutoffKey = clock.dayKey(cutoff)
        var result: [String: Int] = [:]
        for record in records {
            let key = clock.dayKey(record.reviewedAt)
            guard key >= cutoffKey else { continue }
            result[key, default: 0] += 1
        }
        return result
    }

    /// Compute both streaks in a single pass over the records (one `groupByDay`).
    /// `now` 只影響 current streak 的錨點；longest 與時鐘無關。
    static func streaks(records: [ReviewRecord], now: Date = Date()) -> (current: Int, longest: Int) {
        let clock = StatsProjectionClock(now: now, calendar: Calendar.autoupdatingCurrent)
        return streaks(records: records, clock: clock)
    }

    static func streaks(
        records: [ReviewRecord],
        clock: StatsProjectionClock
    ) -> (current: Int, longest: Int) {
        let grouped = groupByDay(records, clock: clock)
        return (
            current: computeCurrentStreak(grouped: grouped, clock: clock),
            longest: computeLongestStreak(grouped: grouped, clock: clock)
        )
    }

    // MARK: - Streak internals

    private static func computeCurrentStreak(grouped: [String: Int], clock: StatsProjectionClock) -> Int {
        let today = clock.now
        var streak = 0
        for offset in 0... {
            guard let date = clock.date(byAdding: .day, value: -offset, to: today) else { break }
            let key = clock.dayKey(date)
            if let count = grouped[key], count > 0 {
                streak += 1
            } else {
                if offset == 0 { continue }
                break
            }
        }
        return streak
    }

    private static func computeLongestStreak(grouped: [String: Int], clock: StatsProjectionClock) -> Int {
        guard !grouped.isEmpty else { return 0 }

        let sortedDays = grouped.keys.sorted()
        guard let firstDay = sortedDays.first,
              let firstDate = Self.date(from: firstDay, clock: clock),
              let lastDay = sortedDays.last,
              let lastDate = Self.date(from: lastDay, clock: clock) else { return 0 }

        let totalDays = clock.calendar.dateComponents([.day], from: firstDate, to: lastDate).day ?? 0
        var longest = 0
        var current = 0
        for offset in 0...totalDays {
            guard let date = clock.date(byAdding: .day, value: offset, to: firstDate) else { continue }
            let key = clock.dayKey(date)
            if let count = grouped[key], count > 0 {
                current += 1
                longest = max(longest, current)
            } else {
                current = 0
            }
        }
        return longest
    }

    static func reviewedToday(records: [ReviewRecord], now: Date = Date()) -> Int {
        let clock = StatsProjectionClock(now: now, calendar: Calendar.autoupdatingCurrent)
        return reviewedToday(records: records, clock: clock)
    }

    static func reviewedToday(records: [ReviewRecord], clock: StatsProjectionClock) -> Int {
        let todayKey = clock.dayKey(clock.now)
        return records.filter { clock.dayKey($0.reviewedAt) == todayKey }.count
    }

    static func recordsForDay(_ dayKey: String, from records: [ReviewRecord]) -> [ReviewRecord] {
        records.filter { $0.dayKey == dayKey }
            .sorted { $0.reviewedAt > $1.reviewedAt }
    }

    static func recordsForDay(
        _ dayKey: String,
        from records: [ReviewRecord],
        clock: StatsProjectionClock
    ) -> [ReviewRecord] {
        records.filter { clock.dayKey($0.reviewedAt) == dayKey }
            .sorted { $0.reviewedAt > $1.reviewedAt }
    }

    // MARK: - Helpers

    private static func groupByDay(_ records: [ReviewRecord], clock: StatsProjectionClock) -> [String: Int] {
        var result: [String: Int] = [:]
        for record in records {
            result[clock.dayKey(record.reviewedAt), default: 0] += 1
        }
        return result
    }

    private static func date(from key: String, clock: StatsProjectionClock) -> Date? {
        let parts = key.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return clock.calendar.date(from: DateComponents(
            calendar: clock.calendar,
            timeZone: clock.calendar.timeZone,
            year: parts[0],
            month: parts[1],
            day: parts[2]
        ))
    }
}
