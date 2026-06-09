#if os(iOS)
import Foundation
import SwiftData
import os

@MainActor
struct PodcastVocabularyContext: VocabularyContextStore {
    let vocabulary: [VocabularyEntry]
    let modelContext: ModelContext
    let series: PodcastSeries
    let episode: PodcastEpisode
    let notebookId: String
    let toastCoordinator: AppToastCoordinator
    let queuedDeleteLogPrefix = "Queued KG delete (podcast) for"
    let localDeleteLogPrefix = "Deleted local podcast entry"

    func saveEntry(
        selection: WordSelection,
        translation: String,
        rootForm: String?
    ) -> Bool {
        if let restored = restoreExistingEntryForSave(
            matching: selection.word,
            translation: translation,
            rootForm: rootForm
        ) {
            return restored
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
        deferSave()
        return true
    }
}
#endif
