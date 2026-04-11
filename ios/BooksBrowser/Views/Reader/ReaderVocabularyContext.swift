#if os(iOS)
import Foundation
import SwiftData
import ReadiumShared
import os

@MainActor
struct ReaderVocabularyContext {
    let vocabulary: [VocabularyEntry]
    let modelContext: ModelContext
    let book: Book
    let currentLocator: Locator?
    let notebookId: String
    let toastCoordinator: AppToastCoordinator

    func existingEntry(matching word: String) -> VocabularyEntry? {
        let wordLower = word.lowercased()
        let scope = notebookId
        return vocabulary.first { entry in
            guard entry.notebookId == scope else { return false }
            let normalizedWord = entry.word.lowercased()
            if normalizedWord == wordLower { return true }
            if entry.rootForm?.lowercased() == wordLower { return true }
            return entry.inflections.contains { $0.lowercased() == wordLower }
        }
    }

    func deleteEntry(matching word: String) {
        guard let entry = existingEntry(matching: word) else { return }

        if entry.isSynced {
            entry.queueDelete()
            AppLog.reader.info("Queued KG delete action for: \(word)")
        } else {
            modelContext.delete(entry)
            AppLog.reader.info("Deleted local entry: \(word)")
        }
        modelContext.safeSaveWithToast(toastCoordinator)
    }

    func saveEntry(
        selection: WordSelection,
        translation: String,
        rootForm: String? = nil
    ) -> Bool {
        // Defend against race: if entry exists but is queued for delete, restore it
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

    /// Schedule save on next run loop iteration to avoid blocking the current animation frame.
    private func deferSave() {
        let ctx = modelContext
        let toast = toastCoordinator
        DispatchQueue.main.async {
            ctx.safeSaveWithToast(toast)
        }
    }

    static func lookedUpWords(from vocabulary: [VocabularyEntry]) -> [String] {
        vocabulary.filter(\.shouldAppearInReader).flatMap { entry in
            var all = Set([entry.word.lowercased()] + entry.inflections.map { $0.lowercased() })
            if let root = entry.rootForm?.lowercased() { all.insert(root) }
            return Array(all)
        }
    }
}
#endif
