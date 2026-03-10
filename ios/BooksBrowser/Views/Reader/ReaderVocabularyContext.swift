import Foundation
import SwiftData
import ReadiumShared

@MainActor
struct ReaderVocabularyContext {
    let vocabulary: [VocabularyEntry]
    let modelContext: ModelContext
    let book: Book
    let currentLocator: Locator?

    func existingEntry(matching word: String) -> VocabularyEntry? {
        let wordLower = word.lowercased()
        return vocabulary.first { entry in
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
            print("🗑️ Queued KG delete action for: \(word)")
        } else {
            modelContext.delete(entry)
            print("🗑️ Deleted local entry: \(word)")
        }
        try? modelContext.save()
    }

    func saveEntry(
        selection: WordSelection,
        translation: String,
        pronunciation: String?,
        rootForm: String? = nil
    ) -> Bool {
        let wordLower = selection.word.lowercased()
        let alreadyExists = vocabulary.contains { $0.word.lowercased() == wordLower }
        guard !alreadyExists else { return false }

        let entry = VocabularyEntry(
            word: selection.word,
            translation: translation,
            context: selection.context,
            explanation: nil,
            partOfSpeech: nil,
            pronunciation: pronunciation,
            bookTitle: book.title,
            chapterTitle: currentLocator?.title
        )
        entry.rootForm = rootForm
        entry.bookId = book.id
        modelContext.insert(entry)
        try? modelContext.save()
        return true
    }

    static func lookedUpWords(from vocabulary: [VocabularyEntry]) -> [String] {
        vocabulary.flatMap { entry in
            var all = Set([entry.word.lowercased()] + entry.inflections.map { $0.lowercased() })
            if let root = entry.rootForm?.lowercased() { all.insert(root) }
            return Array(all)
        }
    }
}
