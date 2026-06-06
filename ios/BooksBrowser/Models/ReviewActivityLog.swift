//
//  ReviewActivityLog.swift
//  BooksBrowser
//
//  複習活動查詢工具。資料來源為 SwiftData ReviewRecord。
//

import Foundation
import SwiftData

enum ReviewActivityLog {
    private static let calendar = Calendar.current

    private static let dayFormatter = AppDateFormatters.dayKey
    private static let syntheticRecordWords: Set<String> = [
        "\u{FF08}\u{8DE8}\u{88DD}\u{7F6E}\u{540C}\u{6B65}\u{FF09}",
        "\u{FF08}\u{9077}\u{79FB}\u{8CC7}\u{6599}\u{FF09}"
    ]

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

    static func activity(for days: Int = 180, records: [ReviewRecord]) -> [String: Int] {
        let cutoff = calendar.date(byAdding: .day, value: -days, to: Date()) ?? Date()
        let cutoffKey = dayFormatter.string(from: cutoff)
        var result: [String: Int] = [:]
        for record in records where record.dayKey >= cutoffKey {
            result[record.dayKey, default: 0] += 1
        }
        return result
    }

    /// Compute both streaks in a single pass over the records (one `groupByDay`).
    static func streaks(records: [ReviewRecord]) -> (current: Int, longest: Int) {
        let grouped = groupByDay(records)
        return (
            current: computeCurrentStreak(grouped: grouped),
            longest: computeLongestStreak(grouped: grouped)
        )
    }

    // MARK: - Streak internals

    private static func computeCurrentStreak(grouped: [String: Int]) -> Int {
        let today = Date()
        var streak = 0
        for offset in 0... {
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { break }
            let key = dayFormatter.string(from: date)
            if let count = grouped[key], count > 0 {
                streak += 1
            } else {
                if offset == 0 { continue }
                break
            }
        }
        return streak
    }

    private static func computeLongestStreak(grouped: [String: Int]) -> Int {
        guard !grouped.isEmpty else { return 0 }

        let sortedDays = grouped.keys.sorted()
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
            if let count = grouped[key], count > 0 {
                current += 1
                longest = max(longest, current)
            } else {
                current = 0
            }
        }
        return longest
    }

    static func reviewedToday(records: [ReviewRecord]) -> Int {
        let todayKey = dayFormatter.string(from: Date())
        return records.filter { $0.dayKey == todayKey }.count
    }

    static func recordsForDay(_ dayKey: String, from records: [ReviewRecord]) -> [ReviewRecord] {
        records.filter { $0.dayKey == dayKey }
            .sorted { $0.reviewedAt > $1.reviewedAt }
    }

    @MainActor
    @discardableResult
    static func removeSyntheticPlaceholderRecords(context: ModelContext) throws -> Int {
        let records = try context.fetch(FetchDescriptor<ReviewRecord>())
        var removed = 0
        for record in records where isSyntheticPlaceholderRecord(record) {
            context.delete(record)
            removed += 1
        }
        if removed > 0 {
            try context.save()
        }
        return removed
    }

    // MARK: - Helpers

    private static func groupByDay(_ records: [ReviewRecord]) -> [String: Int] {
        var result: [String: Int] = [:]
        for record in records {
            result[record.dayKey, default: 0] += 1
        }
        return result
    }

    private static func isSyntheticPlaceholderRecord(_ record: ReviewRecord) -> Bool {
        guard syntheticRecordWords.contains(record.word),
              record.entryID == nil,
              record.notebookId == "default",
              let dayStart = dayFormatter.date(from: record.dayKey) else {
            return false
        }
        return abs(record.reviewedAt.timeIntervalSince(dayStart)) < 0.001
    }
}
