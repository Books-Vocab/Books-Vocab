#if os(iOS)
import Foundation
import SwiftData

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

    @MainActor
    static func insertVocabularySeed(
        _ seed: UIWorldVocabularySeed,
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

        let entriesByWord = Dictionary(uniqueKeysWithValues: entries.map { ($0.word, $0) })
        for recordSeed in seed.reviewHistory {
            let entry = entriesByWord[recordSeed.word]
            let record = ReviewRecord(
                word: recordSeed.word,
                entryID: entry?.id,
                feedback: recordSeed.feedback,
                reviewedAt: recordSeed.reviewedAt,
                kgCardId: entry?.kgCardId
            )
            record.notebookId = seed.notebookRemoteId
            context.insert(record)
        }

        try context.save()
        return entries
    }
}
#endif
