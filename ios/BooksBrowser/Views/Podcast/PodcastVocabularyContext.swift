#if os(iOS)
import Foundation
import SwiftData
import os

@MainActor
struct PodcastVocabularyContext: VocabularyContextProtocol {
    let vocabulary: [VocabularyEntry]
    let modelContext: ModelContext
    let series: PodcastSeries
    let episode: PodcastEpisode
    let notebookId: String
    let toastCoordinator: AppToastCoordinator

    func existingEntry(matching word: String) -> VocabularyEntry? {
        let wordLower = word.lowercased()
        let scope = notebookId
        return vocabulary.first { entry in
            guard entry.notebookId == scope else { return false }
            let normalized = entry.word.lowercased()
            if normalized == wordLower { return true }
            if entry.rootForm?.lowercased() == wordLower { return true }
            return entry.inflections.contains { $0.lowercased() == wordLower }
        }
    }

    func deleteEntry(matching word: String) {
        let entry = existingEntry(matching: word) ?? fetchEntryFromContext(matching: word)
        guard let entry else { return }
        if entry.isSynced {
            entry.queueDelete()
            AppLog.reader.info("Queued KG delete (podcast) for: \(word)")
        } else {
            modelContext.delete(entry)
            AppLog.reader.info("Deleted local podcast entry: \(word)")
        }
        modelContext.safeSaveWithToast(toastCoordinator)
    }

    private func fetchEntryFromContext(matching word: String) -> VocabularyEntry? {
        let nbId = notebookId
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.notebookId == nbId }
        )
        guard let candidates = try? modelContext.fetch(descriptor) else { return nil }
        let wordLower = word.lowercased()
        return candidates.first { entry in
            let normalized = entry.word.lowercased()
            if normalized == wordLower { return true }
            if entry.rootForm?.lowercased() == wordLower { return true }
            return entry.inflections.contains { $0.lowercased() == wordLower }
        }
    }

    func saveEntry(
        selection: WordSelection,
        translation: String,
        rootForm: String?
    ) -> Bool {
        if let existing = existingEntry(matching: selection.word) {
            if existing.syncAction == .delete {
                existing.restorePendingEntry()
                existing.translation = translation
                if let rootForm { existing.rootForm = rootForm }
                modelContext.safeSaveWithToast(toastCoordinator)
                return true
            }
            return false
        }

        let entry = VocabularyEntry(
            word: selection.word,
            translation: translation,
            context: selection.context,
            explanation: nil,
            partOfSpeech: nil,
            bookTitle: series.title,
            chapterTitle: episode.displayTitle
        )
        entry.rootForm = rootForm
        entry.notebookId = VocabularyEntry.resolveNotebookId(notebookId, in: modelContext)
        modelContext.insert(entry)
        DispatchQueue.main.async {
            modelContext.safeSaveWithToast(toastCoordinator)
        }
        return true
    }
}
#endif
