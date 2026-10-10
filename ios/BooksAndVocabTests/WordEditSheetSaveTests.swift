#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("WordEditSheet save")
struct WordEditSheetSaveTests {
    private struct SaveFailure: Error {}

    private func makeSyncedEntry() -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: "ephemeral",
            translation: "短暫的",
            context: "an ephemeral joy",
            explanation: "原始筆記",
            bookTitle: "Book"
        )
        entry.syncAction = .add
        entry.syncState = .synced
        return entry
    }

    @Test func failedSaveRestoresOriginalFields() {
        let entry = makeSyncedEntry()

        #expect(throws: SaveFailure.self) {
            try WordEditSheet.commitEdit(
                entry: entry,
                translation: "  新翻譯  ",
                explanation: "新筆記",
                save: { throw SaveFailure() }
            )
        }

        #expect(entry.translation == "短暫的")
        #expect(entry.explanation == "原始筆記")
        #expect(entry.syncAction == .add)
        #expect(entry.syncState == .synced)
    }

    @Test func successfulSaveAppliesTrimmedEditAndMarksPending() throws {
        let entry = makeSyncedEntry()

        try WordEditSheet.commitEdit(
            entry: entry,
            translation: "  新翻譯  ",
            explanation: "   ",
            save: {}
        )

        #expect(entry.translation == "新翻譯")
        #expect(entry.explanation == nil)
        #expect(entry.syncAction == .edit)
        #expect(entry.syncState == .pending)
    }
}
#endif
