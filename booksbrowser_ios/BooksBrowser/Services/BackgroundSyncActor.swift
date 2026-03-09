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
                    modelContext.delete(existingEntry)
                    continue
                }
                
                if existingEntry.isPendingDelete {
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
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        for entry in entries {
            modelContext.delete(entry)
        }
        try modelContext.save()
        print("✅ Core data cleared successfully. Deleted \(entries.count) entries. reason=\(reason)")
    }

    /// Deletes only server-synced entries (syncStatus == 1).
    /// Used on startup when not logged in to remove stale KG data
    /// while preserving locally-created pending words (syncStatus == 0).
    func clearSyncedData() throws {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == VocabularySyncState.synced.rawValue }
        )
        let entries = try modelContext.fetch(descriptor)
        guard !entries.isEmpty else { return }
        entries.forEach { modelContext.delete($0) }
        try modelContext.save()
        print("🧹 Cleared \(entries.count) stale synced entries on startup.")
    }
}
