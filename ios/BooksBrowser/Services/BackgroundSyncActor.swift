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
        progress: @Sendable @escaping (String, Int, Int) -> Void
    ) throws {
        // Fetch all current local entries
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let localEntries = try modelContext.fetch(descriptor)

        // Create a fast lookup dictionary (lowercase word -> entry)
        var localDict = [String: VocabularyEntry]()
        for entry in localEntries {
            localDict[entry.word.lowercased()] = entry
        }

        // Keep track of fetched card words to detect orphans later
        var fetchedCardWords = Set<String>()

        // 1. Merge into local DB
        let totalCards = fetchedCards.count
        for (index, card) in fetchedCards.enumerated() {
            if index % 50 == 0 {
                progress(L10n.string("同步最新卡片..."), index, totalCards)
            }
            let lowerContent = card.content.lowercased()
            fetchedCardWords.insert(lowerContent)

            if let existingEntry = localDict[lowerContent] {
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
                    existingEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                    existingEntry.reviewExamples = card.examples
                    existingEntry.graphLinksByKind = card.linksByKind ?? [:]
                    if let serverPron = card.pronunciation, existingEntry.pronunciation == nil {
                        existingEntry.pronunciation = serverPron
                    }
                    existingEntry.isArchived = card.isArchived ?? false
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
                    pronunciation: card.pronunciation,
                    bookTitle: "Knowledge Graph"
                )
                newEntry.difficultyTier = card.difficultyTier
                newEntry.kgCardId = card.id
                newEntry.inflections = card.inflections ?? []
                newEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                newEntry.reviewExamples = card.examples
                newEntry.graphLinksByKind = card.linksByKind ?? [:]
                newEntry.isArchived = card.isArchived ?? false
                newEntry.markSynced()

                // Apply server review state to new entry
                Self.mergeReviewState(from: card, into: newEntry)

                modelContext.insert(newEntry)
                localDict[lowerContent] = newEntry
            }
        }

        // 2. Cleanup orphans (Only for FULL sync)
        // Any local entry that has `syncStatus == 1` but is MISSING from the remote fetched list
        // means it was deleted remotely before soft-deletes were implemented.
        if !isIncremental {
            progress(L10n.string("清理無效卡片..."), totalCards, totalCards)
            for entry in localEntries {
                if entry.shouldAppearInKnowledgeList {
                    if !fetchedCardWords.contains(entry.word.lowercased()) {
                        AppLog.sync.info("Cleaning up remote orphan: \(entry.word)")
                        modelContext.delete(entry)
                    }
                }
            }
        }

        try modelContext.save()
        AppLog.sync.info("pullCardsToLocal completed. Merged \(fetchedCards.count) remote cards.")
    }

    /// Back-fill pronunciations for synced entries that are missing them.
    /// Fetches from the free dictionary API (no LLM cost).
    func backfillPronunciations(batchLimit: Int = 30) async throws {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        let allSynced = try modelContext.fetch(descriptor)
        let needsPron = allSynced.filter {
            $0.pronunciation == nil && !$0.word.contains(" ")
        }
        guard !needsPron.isEmpty else { return }

        let batch = Array(needsPron.prefix(batchLimit))
        AppLog.sync.info("Backfilling pronunciations for \(batch.count)/\(needsPron.count) entries")

        var updated = 0
        for entry in batch {
            if let pron = await DictionaryService.fetchPronunciation(word: entry.word) {
                entry.pronunciation = pron
                updated += 1
            }
            try? await Task.sleep(for: .milliseconds(50))
        }

        if updated > 0 {
            try modelContext.save()
            AppLog.sync.info("Backfilled \(updated) pronunciations")
        }
    }

    /// Deletes all vocabulary entries from local SwiftData storage.
    /// Used during logout or account switch for data isolation.
    func clearVocabularyData(reason: String) throws {
        AppLog.sync.info("Clearing all local vocabulary entries... reason=\(reason)")
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        for entry in entries {
            modelContext.delete(entry)
        }
        try modelContext.save()
        AppLog.sync.info("Core data cleared successfully. Deleted \(entries.count) entries. reason=\(reason)")
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
            guard let lastReviewed = entry.lastReviewedAt else { continue }
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

    // MARK: - Review State Merge Helper

    private static func mergeReviewState(from card: KGCard, into entry: VocabularyEntry) {
        guard let serverLastStr = card.lastReviewedAt,
              let serverLast = parseISO8601(serverLastStr) else { return }

        let localLast = entry.lastReviewedAt ?? .distantPast
        if serverLast > localLast {
            entry.reviewIntervalHours = card.reviewIntervalHours ?? entry.reviewIntervalHours
            if let nextStr = card.nextReviewAt, let nextDate = parseISO8601(nextStr) {
                entry.nextReviewAt = nextDate
            }
            entry.lastReviewedAt = serverLast
            entry.reviewCount = max(entry.reviewCount, card.reviewCount ?? 0)
            entry.lapseCount = max(entry.lapseCount, card.lapseCount ?? 0)
            entry.reviewStreak = max(entry.reviewStreak, card.reviewStreak ?? 0)
            entry.lastReviewFeedbackRaw = card.lastReviewFeedback ?? entry.lastReviewFeedbackRaw
        }
    }
}
