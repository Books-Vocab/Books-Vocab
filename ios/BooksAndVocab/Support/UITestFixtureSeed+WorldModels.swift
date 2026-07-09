#if os(iOS)
import Foundation
import SwiftData

enum UITestFixtureSeedMaterializationError: Error, Equatable {
    case duplicateVocabularyEntryWord(String)
    case reviewHistoryEntryMissingVocabularyEntry(String)
}

extension UITestFixtureSeed {
    static func makeVocabularyEntry(
        from seed: UIWorldVocabularyEntrySeed,
        notebookId: String
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: seed.word,
            translation: seed.translation,
            context: seed.context,
            explanation: seed.explanation,
            partOfSpeech: seed.partOfSpeech,
            bookTitle: seed.bookTitle,
            chapterTitle: seed.chapterTitle
        )
        entry.notebookId = notebookId
        entry.kgCardId = seed.kgCardId
        entry.difficultyTier = seed.difficultyTier
        entry.reviewMode = seed.reviewMode
        entry.reviewExamples = seed.reviewExamples
        entry.collocations = seed.collocations ?? []
        entry.rootForm = seed.rootForm
        entry.inflections = seed.inflections ?? []
        entry.syncStatus = seed.syncStatus
        entry.actionType = seed.actionType
        entry.isArchived = seed.isArchived
        entry.isExcludedFromReader = seed.isExcludedFromReader
        if let reviewIntervalHours = seed.reviewIntervalHours {
            entry.reviewIntervalHours = reviewIntervalHours
        }
        if let nextReviewAt = seed.nextReviewAt {
            entry.nextReviewAt = nextReviewAt
        }
        entry.lastReviewedAt = seed.lastReviewedAt
        if let reviewCount = seed.reviewCount {
            entry.reviewCount = reviewCount
        }
        if let reviewStreak = seed.reviewStreak {
            entry.reviewStreak = reviewStreak
        }
        if let lastReviewFeedbackRaw = seed.lastReviewFeedbackRaw {
            entry.lastReviewFeedbackRaw = lastReviewFeedbackRaw
        }
        entry.graphLinksByKind = seed.graphLinksByKind
        return entry
    }

    @MainActor
    static func clearVocabularyEntries(from context: ModelContext) throws {
        for entry in try context.fetch(FetchDescriptor<VocabularyEntry>()) {
            context.delete(entry)
        }
        try context.save()
    }

    private static func entriesByUniqueWord(_ entries: [VocabularyEntry]) throws -> [String: VocabularyEntry] {
        var entriesByWord: [String: VocabularyEntry] = [:]
        for entry in entries {
            if entriesByWord[entry.word] != nil {
                throw UITestFixtureSeedMaterializationError.duplicateVocabularyEntryWord(entry.word)
            }
            entriesByWord[entry.word] = entry
        }
        return entriesByWord
    }

    /// - Parameter save: When `false`, leaves inserts as pending changes in
    ///   `context` instead of committing via `ModelContext.save()`. SwiftData
    ///   fetches (and `@Query`) include pending inserts, so an in-memory catalog
    ///   scene still renders the seeded data — but no *broadcast*
    ///   `NSManagedObjectContextDidSave` is posted. That broadcast is what a
    ///   dangling `@Query` observer (from an earlier catalog scene whose
    ///   ModelContainer was already deallocated) traps on during a full catalog
    ///   run (`EXC_BREAKPOINT` in `_SwiftData_SwiftUI`). Pass `false` from
    ///   snapshot scenes that seed after many other `@Query` scenes have
    ///   rendered. See docs/sop/ios.md §Catalog Snapshot Export.
    @MainActor
    static func insertVocabularySeed(
        _ seed: UIWorldVocabularySeed,
        into context: ModelContext,
        save: Bool = true
    ) throws -> [VocabularyEntry] {
        let notebook = Notebook(remoteId: seed.notebookRemoteId, name: seed.notebookName)
        notebook.syncStatus = seed.notebookSyncStatus
        context.insert(notebook)

        let entries = seed.entries.map {
            makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
        }
        for entry in entries {
            context.insert(entry)
        }

        let entriesByWord = try entriesByUniqueWord(entries)
        for recordSeed in seed.reviewHistory {
            guard let entry = entriesByWord[recordSeed.word] else {
                throw UITestFixtureSeedMaterializationError.reviewHistoryEntryMissingVocabularyEntry(recordSeed.word)
            }
            let record = ReviewRecord(
                word: recordSeed.word,
                entryID: entry.id,
                feedback: recordSeed.feedback,
                reviewedAt: recordSeed.reviewedAt,
                kgCardId: entry.kgCardId
            )
            record.notebookId = seed.notebookRemoteId
            context.insert(record)
        }

        if save {
            try context.save()
        }
        return entries
    }

    @MainActor
    static func insertReviewDeckSeed(
        _ seed: UIWorldReviewDeckSeed,
        into context: ModelContext
    ) throws -> [VocabularyEntry] {
        let notebook = Notebook(remoteId: seed.notebookRemoteId, name: seed.notebookName)
        notebook.syncStatus = seed.notebookSyncStatus
        context.insert(notebook)

        let entries = seed.entries.map {
            makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
        }
        for entry in entries {
            context.insert(entry)
        }

        _ = try entriesByUniqueWord(entries)

        try context.save()
        return entries
    }
}
#endif
