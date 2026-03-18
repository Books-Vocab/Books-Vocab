//
//  BackgroundSyncActor.swift
//  BooksBrowser
//
//  Created for safe off-main-thread SwiftData operations during sync.
//

import Foundation
import SwiftData
import os

@ModelActor
actor BackgroundSyncActor {

    // MARK: - Cached Date Formatters

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let isoFormatterNoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static func parseISO8601(_ string: String) -> Date? {
        isoFormatter.date(from: string) ?? isoFormatterNoFractional.date(from: string)
    }

    /// Fetch all cards from KG API and merge them into local SwiftData VocabularyEntry items
    /// This makes all KG words available offline (for underlining and browsing).
    func pullCardsToLocal(
        fetchedCards: [KGCard],
        isIncremental: Bool,
        progress: @Sendable @escaping (String, Int, Int) -> Void,
        notebookId: String = "default"
    ) throws {
        // Fetch all current local entries
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let localEntries = try modelContext.fetch(descriptor)

        // Create a fast lookup dictionary keyed by (word, notebookId) to
        // correctly handle same word in different notebooks.
        var localDict = [String: VocabularyEntry]()
        for entry in localEntries {
            let key = "\(entry.word.lowercased())|\(entry.notebookId)"
            localDict[key] = entry
        }

        // Keep track of fetched card keys to detect orphans later
        var fetchedCardKeys = Set<String>()

        // 1. Merge into local DB
        let totalCards = fetchedCards.count
        for (index, card) in fetchedCards.enumerated() {
            if index % 50 == 0 {
                progress(L10n.string("同步最新卡片..."), index, totalCards)
            }
            let cardNotebookId = card.notebookId ?? notebookId
            let mergeKey = "\(card.content.lowercased())|\(cardNotebookId)"
            fetchedCardKeys.insert(mergeKey)

            if let existingEntry = localDict[mergeKey] {
                // Delete if marked as soft-deleted
                if card.isDeleted == true {
                    AppLog.sync.info("Remote soft-delete received: \(existingEntry.word)")
                    modelContext.delete(existingEntry)
                    continue
                }

                if existingEntry.syncAction == .delete {
                    // 本地標記為待刪除，不更新任何欄位，保留 syncStatus=0 讓 SyncView 可以 push
                } else {
                    // Update existing record
                    existingEntry.translation = card.meaning
                    existingEntry.partOfSpeech = card.pos
                    existingEntry.explanation = card.note
                    existingEntry.difficultyTier = card.difficultyTier
                    existingEntry.kgCardId = card.id
                    existingEntry.inflections = card.inflections ?? []
                    existingEntry.collocations = card.collocations ?? []
                    existingEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                    existingEntry.reviewExamples = card.examples
                    existingEntry.graphLinksByKind = card.linksByKind ?? [:]
                    existingEntry.isArchived = card.isArchived ?? false
                    if let cardNotebookId = card.notebookId {
                        existingEntry.notebookId = cardNotebookId
                    }
                    existingEntry.markSynced()

                    // Merge review state from server (server newer wins)
                    Self.mergeReviewState(from: card, into: existingEntry)
                }
            } else {
                // If it's softly deleted but we don't have it locally, ignore it
                if card.isDeleted == true { continue }

                // Create new record
                let newEntry = VocabularyEntry(
                    word: card.content,
                    translation: card.meaning,
                    context: card.examples.first ?? "",
                    explanation: card.note,
                    partOfSpeech: card.pos,
                    bookTitle: "Knowledge Graph"
                )
                newEntry.difficultyTier = card.difficultyTier
                newEntry.kgCardId = card.id
                newEntry.inflections = card.inflections ?? []
                newEntry.collocations = card.collocations ?? []
                newEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                newEntry.reviewExamples = card.examples
                newEntry.graphLinksByKind = card.linksByKind ?? [:]
                newEntry.isArchived = card.isArchived ?? false
                newEntry.notebookId = card.notebookId ?? notebookId
                newEntry.markSynced()

                // Apply server review state to new entry
                Self.mergeReviewState(from: card, into: newEntry)

                modelContext.insert(newEntry)
                localDict[mergeKey] = newEntry
            }
        }

        // 2. Cleanup orphans (Only for FULL sync)
        // Any local entry that has `syncStatus == 1` but is MISSING from the remote fetched list
        // means it was deleted remotely before soft-deletes were implemented.
        if !isIncremental {
            progress(L10n.string("清理無效卡片..."), totalCards, totalCards)
            for entry in localEntries {
                if entry.shouldAppearInKnowledgeList {
                    let orphanKey = "\(entry.word.lowercased())|\(entry.notebookId)"
                    if !fetchedCardKeys.contains(orphanKey) {
                        AppLog.sync.info("Cleaning up remote orphan: \(entry.word)")
                        modelContext.delete(entry)
                    }
                }
            }
        }

        try modelContext.save()
        AppLog.sync.info("pullCardsToLocal completed. Merged \(fetchedCards.count) remote cards.")
    }

    /// Deletes all vocabulary entries and review records from local SwiftData storage.
    /// Used during logout or account switch for data isolation.
    func clearVocabularyData(reason: String) throws {
        AppLog.sync.info("Clearing all local vocabulary + review + notebook data... reason=\(reason)")
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        for entry in entries {
            modelContext.delete(entry)
        }
        let reviews = try modelContext.fetch(FetchDescriptor<ReviewRecord>())
        for record in reviews {
            modelContext.delete(record)
        }
        let notebooks = try modelContext.fetch(FetchDescriptor<Notebook>())
        for notebook in notebooks {
            modelContext.delete(notebook)
        }
        try modelContext.save()
        AppLog.sync.info("Local data cleared. Deleted \(entries.count) vocab + \(reviews.count) review + \(notebooks.count) notebooks. reason=\(reason)")
    }

    /// Deletes only server-synced entries (syncStatus == 1).
    /// Used on startup when not logged in to remove stale KG data
    /// while preserving locally-created pending words (syncStatus == 0).
    func clearSyncedData() throws {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        let entries = try modelContext.fetch(descriptor)
        guard !entries.isEmpty else { return }
        entries.forEach { modelContext.delete($0) }
        try modelContext.save()
        AppLog.sync.info("Cleared \(entries.count) stale synced entries on startup.")
    }

    /// Build the payload for pushing review states to the backend.
    func buildReviewStatePushPayload() throws -> [[String: Any]] {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        let entries = try modelContext.fetch(descriptor)

        var payload: [[String: Any]] = []
        for entry in entries {
            let lastReviewed = entry.lastReviewedAt ?? entry.dateAdded
            payload.append([
                "word": entry.word,
                "review_interval_hours": entry.reviewIntervalHours,
                "next_review_at": Self.isoFormatter.string(from: entry.nextReviewAt),
                "last_reviewed_at": Self.isoFormatter.string(from: lastReviewed),
                "review_count": entry.reviewCount,
                "lapse_count": entry.lapseCount,
                "review_streak": entry.reviewStreak,
                "last_review_feedback": entry.lastReviewFeedbackRaw,
            ])
        }
        return payload
    }

    // MARK: - Daily Review Stats Sync

    /// Build daily aggregated review stats from local ReviewRecords for pushing to backend.
    func buildDailyStatsPushPayload() throws -> [[String: Any]] {
        let descriptor = FetchDescriptor<ReviewRecord>()
        let records = try modelContext.fetch(descriptor)
        guard !records.isEmpty else { return [] }

        // Group by dayKey
        var grouped: [String: (total: Int, remembered: Int, forgot: Int)] = [:]
        for record in records {
            var stat = grouped[record.dayKey] ?? (0, 0, 0)
            stat.total += 1
            if record.feedback == 1 {
                stat.remembered += 1
            } else {
                stat.forgot += 1
            }
            grouped[record.dayKey] = stat
        }

        return grouped.map { dayKey, stat in
            [
                "day_key": dayKey,
                "total": stat.total,
                "remembered": stat.remembered,
                "forgot": stat.forgot,
            ] as [String: Any]
        }
    }

    /// Merge remote daily stats into local ReviewRecords.
    /// For days where remote has data but local doesn't, create placeholder records.
    /// For days where local already has data, remote is ignored (local is authoritative for detail).
    func mergeDailyStats(_ remoteStats: [[String: Any]]) throws {
        let descriptor = FetchDescriptor<ReviewRecord>()
        let allRecords = try modelContext.fetch(descriptor)

        // Count local records per day
        var localDayCounts: [String: Int] = [:]
        for record in allRecords {
            localDayCounts[record.dayKey, default: 0] += 1
        }

        var inserted = 0
        for stat in remoteStats {
            guard let dayKey = stat["day_key"] as? String,
                  let total = stat["total"] as? Int,
                  let remembered = stat["remembered"] as? Int else { continue }
            let forgot = (stat["forgot"] as? Int) ?? (total - remembered)

            let localCount = localDayCounts[dayKey] ?? 0
            if localCount >= total {
                // Local already has equal or more records for this day — skip
                continue
            }

            // Need to create (total - localCount) placeholder records
            let deficit = total - localCount
            // Distribute: fill remembered first, then forgot
            let localRemembered = allRecords.filter { $0.dayKey == dayKey && $0.feedback == 1 }.count
            let localForgot = allRecords.filter { $0.dayKey == dayKey && $0.feedback == 0 }.count
            let needRemembered = max(0, remembered - localRemembered)
            let needForgot = max(0, forgot - localForgot)
            let toCreate = min(deficit, needRemembered + needForgot)

            guard toCreate > 0, let date = Self.dayFormatter.date(from: dayKey) else { continue }

            for i in 0..<toCreate {
                let feedback = i < needRemembered ? 1 : 0
                let record = ReviewRecord(
                    word: "（跨裝置同步）",
                    entryID: nil,
                    feedback: feedback,
                    reviewedAt: date
                )
                modelContext.insert(record)
                inserted += 1
            }
        }

        if inserted > 0 {
            try modelContext.save()
            AppLog.sync.info("mergeDailyStats: inserted \(inserted) placeholder records from remote")
        }
    }

    func distinctNotebookIds() throws -> [String] {
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let entries = try modelContext.fetch(descriptor)
        return Array(Set(entries.map(\.notebookId)))
    }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    // MARK: - Review State Merge Helper

    private static func mergeReviewState(from card: KGCard, into entry: VocabularyEntry) {
        guard let serverLastStr = card.lastReviewedAt,
              let serverLast = parseISO8601(serverLastStr) else { return }

        let localLast = entry.lastReviewedAt ?? .distantPast
        if serverLast >= localLast {
            if localLast != .distantPast {
                AppLog.sync.info("Review merge: server wins for '\(entry.word)' (server=\(serverLastStr), local=\(isoFormatter.string(from: localLast)))")
            }
            entry.reviewIntervalHours = card.reviewIntervalHours ?? entry.reviewIntervalHours
            if let nextStr = card.nextReviewAt, let nextDate = parseISO8601(nextStr) {
                entry.nextReviewAt = nextDate
            }
            entry.lastReviewedAt = serverLast
            entry.reviewCount = max(entry.reviewCount, card.reviewCount ?? 0)
            entry.lapseCount = max(entry.lapseCount, card.lapseCount ?? 0)
            entry.reviewStreak = max(entry.reviewStreak, card.reviewStreak ?? 0)
            entry.lastReviewFeedbackRaw = card.lastReviewFeedback ?? entry.lastReviewFeedbackRaw
        } else if localLast > serverLast {
            AppLog.sync.info("Review merge: local wins for '\(entry.word)' (local=\(isoFormatter.string(from: localLast)), server=\(serverLastStr)), local review preserved")
        }
    }
}
