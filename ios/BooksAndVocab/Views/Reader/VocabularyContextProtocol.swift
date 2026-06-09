#if os(iOS)
import Foundation

@MainActor
protocol VocabularyContextProtocol {
    var notebookId: String { get }
    func existingEntry(matching word: String) -> VocabularyEntry?
    func deleteEntry(matching word: String)
    func saveEntry(selection: WordSelection, translation: String, rootForm: String?) -> Bool
}

extension VocabularyContextProtocol {
    func saveEntry(selection: WordSelection, translation: String) -> Bool {
        saveEntry(selection: selection, translation: translation, rootForm: nil)
    }
}
#endif
