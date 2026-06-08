#if os(iOS)
import Foundation
import SwiftData
import ReadiumShared
import os

@MainActor
struct ReaderVocabularyContext: VocabularyContextStore {
    let vocabulary: [VocabularyEntry]
    let modelContext: ModelContext
    let book: Book
    let currentLocator: Locator?
    let notebookId: String
    let toastCoordinator: AppToastCoordinator
    let queuedDeleteLogPrefix = "Queued KG delete action for"
    let localDeleteLogPrefix = "Deleted local entry"
    let fetchFailureLogPrefix: String? = "Vocab fetch failed"

    func saveEntry(
        selection: WordSelection,
        translation: String,
        rootForm: String? = nil
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
            bookTitle: book.title,
            chapterTitle: currentLocator?.title
        )
        entry.rootForm = rootForm
        entry.bookId = book.id
        // Defense-in-depth: 即使 ReaderView.sanitizeStaleBoundNotebook 漏網（race
        // 或 .onChange 尚未 propagate），這裡的 chokepoint 會把指向已刪 notebook
        // 的候選值 fallback 到 "default"，根除孤兒 entry。
        entry.notebookId = VocabularyEntry.resolveNotebookId(notebookId, in: modelContext)
        modelContext.insert(entry)
        deferSave()
        return true
    }
}
#endif
