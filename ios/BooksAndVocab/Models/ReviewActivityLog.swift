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
        clock: ReviewCalendarClock,
        notebookId: String = "default"
    ) {
        let record = ReviewRecord(
            word: word,
            entryID: entryID,
            feedback: feedback == .remembered ? 1 : 0,
            reviewedAt: clock.now
        )
        record.dayKey = clock.dayKey(for: clock.now)
        record.notebookId = notebookId
        context.insert(record)
    }

    // MARK: - Queries (from SwiftData)

    static func activity(
        for days: Int = 180,
        records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> [String: Int] {
        let cutoff = clock.cutoff(days: days)
        var result: [String: Int] = [:]
        for record in records where record.reviewedAt >= cutoff {
            result[clock.dayKey(for: record.reviewedAt), default: 0] += 1
        }
        return result
    }

    /// Compute both streaks in a single pass over the records (one `groupByDay`).
    static func streaks(
        records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> (current: Int, longest: Int) {
        let grouped = groupByDay(records, clock: clock)
        return (
            current: computeCurrentStreak(grouped: grouped, clock: clock),
            longest: computeLongestStreak(grouped: grouped, clock: clock)
        )
    }

    // MARK: - Streak internals

    private static func computeCurrentStreak(
        grouped: [String: Int],
        clock: ReviewCalendarClock
    ) -> Int {
        var streak = 0
        for offset in 0... {
            guard let date = clock.calendar.date(
                byAdding: .day,
                value: -offset,
                to: clock.startOfToday
            ) else { break }
            let key = clock.dayKey(for: date)
            if let count = grouped[key], count > 0 {
                streak += 1
            } else {
                if offset == 0 { continue }
                break
            }
        }
        return streak
    }

    private static func computeLongestStreak(
        grouped: [String: Int],
        clock: ReviewCalendarClock
    ) -> Int {
        guard !grouped.isEmpty else { return 0 }

        let sortedDays = grouped.keys.sorted()
        guard let firstDate = date(forDayKey: sortedDays[0], clock: clock),
              let lastDate = date(forDayKey: sortedDays[sortedDays.count - 1], clock: clock)
        else { return 0 }

        let totalDays = clock.calendar.dateComponents(
            [.day],
            from: firstDate,
            to: lastDate
        ).day ?? 0
        var longest = 0
        var current = 0
        for offset in 0...totalDays {
            guard let date = clock.calendar.date(
                byAdding: .day,
                value: offset,
                to: firstDate
            ) else { continue }
            let key = clock.dayKey(for: date)
            if let count = grouped[key], count > 0 {
                current += 1
                longest = max(longest, current)
            } else {
                current = 0
            }
        }
        return longest
    }

    private static func date(
        forDayKey key: String,
        clock: ReviewCalendarClock
    ) -> Date? {
        let components = key.split(separator: "-").compactMap { Int($0) }
        guard components.count == 3 else { return nil }
        var dateComponents = DateComponents()
        dateComponents.year = components[0]
        dateComponents.month = components[1]
        dateComponents.day = components[2]
        return clock.calendar.date(from: dateComponents)
    }

    // MARK: - Day queries

    static func reviewedToday(
        records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> Int {
        let todayKey = clock.dayKey(for: clock.now)
        return records.filter { clock.dayKey(for: $0.reviewedAt) == todayKey }.count
    }

    static func recordsForDay(
        _ dayKey: String,
        from records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> [ReviewRecord] {
        records
            .filter { clock.dayKey(for: $0.reviewedAt) == dayKey }
            .sorted { $0.reviewedAt > $1.reviewedAt }
    }

    // MARK: - Helpers

    private static func groupByDay(
        _ records: [ReviewRecord],
        clock: ReviewCalendarClock
    ) -> [String: Int] {
        var result: [String: Int] = [:]
        for record in records {
            result[clock.dayKey(for: record.reviewedAt), default: 0] += 1
        }
        return result
    }
}
