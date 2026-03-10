//
//  ReviewActivityLog.swift
//  BooksBrowser
//
//  複習活動查詢工具。資料來源為 SwiftData ReviewRecord。
//  保留舊 UserDefaults 資料的一次性遷移邏輯。
//

import Foundation
import SwiftData

enum ReviewActivityLog {
    private static let legacyStorageKey = "review_activity_log"
    private static let migrationDoneKey = "review_activity_migrated_to_swiftdata"
    private static let calendar = Calendar.current

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    // MARK: - Record

    @MainActor
    static func recordReview(
        word: String,
        entryID: UUID?,
        feedback: ReviewFeedback,
        context: ModelContext
    ) {
        let record = ReviewRecord(
            word: word,
            entryID: entryID,
            feedback: feedback == .remembered ? 1 : 0
        )
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

    static func currentStreak(records: [ReviewRecord]) -> Int {
        let grouped = groupByDay(records)
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

    static func longestStreak(records: [ReviewRecord]) -> Int {
        let grouped = groupByDay(records)
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

    // MARK: - Migration

    @MainActor
    static func migrateFromUserDefaultsIfNeeded(context: ModelContext) {
        guard !UserDefaults.standard.bool(forKey: migrationDoneKey) else { return }
        guard let legacy = UserDefaults.standard.dictionary(forKey: legacyStorageKey) as? [String: Int],
              !legacy.isEmpty else {
            UserDefaults.standard.set(true, forKey: migrationDoneKey)
            return
        }

        for (dayKey, count) in legacy {
            guard let date = dayFormatter.date(from: dayKey) else { continue }
            // 建立 placeholder records（無法還原具體單字）
            for _ in 0..<count {
                let record = ReviewRecord(
                    word: "（遷移資料）",
                    entryID: nil,
                    feedback: 1,
                    reviewedAt: date
                )
                context.insert(record)
            }
        }

        try? context.save()
        UserDefaults.standard.removeObject(forKey: legacyStorageKey)
        UserDefaults.standard.set(true, forKey: migrationDoneKey)
    }

    // MARK: - Helpers

    private static func groupByDay(_ records: [ReviewRecord]) -> [String: Int] {
        var result: [String: Int] = [:]
        for record in records {
            result[record.dayKey, default: 0] += 1
        }
        return result
    }
}
