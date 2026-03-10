//
//  BackgroundSyncActor.swift
//  BooksBrowser
//
//  Created for safe off-main-thread SwiftData operations during sync.
//

import Foundation
import SwiftData

@ModelActor
actor BackgroundSyncActor {

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
                    print("🧹 Remote soft-delete received: \(existingEntry.word)")
                    VocabularyReviewMetaHelper.deleteReviewMeta(for: existingEntry, in: modelContext)
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
                    existingEntry.markSynced()
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
                    pronunciation: nil,
                    bookTitle: "Knowledge Graph"
                )
                newEntry.difficultyTier = card.difficultyTier
                newEntry.kgCardId = card.id
                newEntry.inflections = card.inflections ?? []
                newEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                newEntry.reviewExamples = card.examples
                newEntry.graphLinksByKind = card.linksByKind ?? [:]
                newEntry.markSynced()

                modelContext.insert(newEntry)
                localDict[lowerContent] = newEntry

                // Create corresponding VocabularyReviewMeta for CloudKit sync
                let meta = VocabularyReviewMeta(
                    id: newEntry.id,
                    wordKey: lowerContent,
                    context: card.examples.first ?? "",
                    bookTitle: "Knowledge Graph",
                    originalDateAdded: newEntry.dateAdded
                )
                modelContext.insert(meta)
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
                        print("🧹 Cleaning up remote orphan: \(entry.word)")
                        VocabularyReviewMetaHelper.deleteReviewMeta(for: entry, in: modelContext)
                        modelContext.delete(entry)
                    }
                }
            }
        }

        try modelContext.save()
        print("✅ pullCardsToLocal completed. Merged \(fetchedCards.count) remote cards.")
    }

    /// Deletes all vocabulary entries from local SwiftData storage.
    /// Used during logout or account switch for data isolation.
    func clearVocabularyData(reason: String) throws {
        print("🧹 Clearing all local vocabulary entries... reason=\(reason)")
        VocabularyReviewMetaHelper.deleteAllReviewMeta(in: modelContext)
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        for entry in entries {
            modelContext.delete(entry)
        }
        try modelContext.save()
        print("✅ Core data cleared successfully. Deleted \(entries.count) entries. reason=\(reason)")
    }

    /// Syncs review state between VocabularyReviewMeta (CloudKit) and VocabularyEntry (local).
    /// Whichever side has a newer lastReviewedAt wins; uses merge strategy for conflicts.
    func syncReviewMetaToEntries() throws {
        let allMeta = try modelContext.fetch(FetchDescriptor<VocabularyReviewMeta>())
        let allEntries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())

        var entryById = [UUID: VocabularyEntry]()
        for entry in allEntries {
            entryById[entry.id] = entry
        }

        for meta in allMeta {
            guard let entry = entryById[meta.id] else { continue }

            let metaLastReviewed = meta.lastReviewedAt ?? .distantPast
            let entryLastReviewed = entry.lastReviewedAt ?? .distantPast

            if metaLastReviewed > entryLastReviewed {
                entry.reviewIntervalHours = meta.reviewIntervalHours
                entry.nextReviewAt = meta.nextReviewAt
                entry.lastReviewedAt = meta.lastReviewedAt
                entry.reviewCount = max(entry.reviewCount, meta.reviewCount)
                entry.lapseCount = max(entry.lapseCount, meta.lapseCount)
                entry.reviewStreak = meta.reviewStreak
                entry.lastReviewFeedbackRaw = meta.lastReviewFeedbackRaw
            } else if entryLastReviewed > metaLastReviewed {
                meta.reviewIntervalHours = entry.reviewIntervalHours
                meta.nextReviewAt = entry.nextReviewAt
                meta.lastReviewedAt = entry.lastReviewedAt
                meta.reviewCount = max(meta.reviewCount, entry.reviewCount)
                meta.lapseCount = max(meta.lapseCount, entry.lapseCount)
                meta.reviewStreak = entry.reviewStreak
                meta.lastReviewFeedbackRaw = entry.lastReviewFeedbackRaw
            }
        }

        try modelContext.save()
        print("✅ syncReviewMetaToEntries completed. Synced \(allMeta.count) meta records.")
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
        for entry in entries {
            VocabularyReviewMetaHelper.deleteReviewMeta(for: entry, in: modelContext)
        }
        entries.forEach { modelContext.delete($0) }
        try modelContext.save()
        print("🧹 Cleared \(entries.count) stale synced entries on startup.")
    }
}
