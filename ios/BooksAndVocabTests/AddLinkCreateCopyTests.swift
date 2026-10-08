import Foundation
import Testing
@testable import BooksAndVocab

/// #2037: the create entry says the whole action ("create X and link it to Y")
/// and which notebook the new card lands in.
@Suite("Add Link create copy (#2037)", .serialized)
struct AddLinkCreateCopyTests {
    private static let languages: [AppLanguage] = [
        .english, .traditionalChinese, .simplifiedChinese, .japanese, .korean,
    ]

    @Test("the sentence carries both the new word and the source word in every locale", arguments: languages)
    func titleNamesTargetAndSource(language: AppLanguage) {
        let title = AddLinkCreateCopy.title(target: "apple", source: "banana", language: language)
        #expect(title.contains("apple"))
        #expect(title.contains("banana"))
        #expect(title != "addLink.create.title", "key must be localized")
        // Target first, then source: the sentence reads "create X ... link to Y".
        let apple = title.range(of: "apple")
        let banana = title.range(of: "banana")
        #expect(apple != nil && banana != nil && apple!.lowerBound < banana!.lowerBound)
    }

    @Test("a long word is shortened but the verb and the source word stay whole")
    func longWordIsShortened() {
        let long = String(repeating: "x", count: 80)
        let title = AddLinkCreateCopy.title(target: long, source: "banana", language: .english)
        #expect(!title.contains(long))
        #expect(title.contains("…"))
        #expect(title.contains("banana"))
        #expect(title.hasPrefix("Create"))
        #expect(title.contains("link it to"))
    }

    @Test("the limit is counted in characters the user sees, not UTF-16 units")
    func limitCountsGraphemes() {
        let emoji = String(repeating: "👨‍👩‍👧", count: AddLinkCreateCopy.wordDisplayLimit)
        #expect(AddLinkCreateCopy.displayWord(emoji) == emoji, "exactly at the limit stays verbatim")
        let over = emoji + "👨‍👩‍👧"
        let shortened = AddLinkCreateCopy.displayWord(over)
        #expect(shortened.hasSuffix("…"))
        #expect(shortened.count == AddLinkCreateCopy.wordDisplayLimit)
        #expect(shortened.dropLast().allSatisfy { $0 == "👨‍👩‍👧" }, "no grapheme is cut in half")
    }

    @Test("whitespace is trimmed and newlines/tabs fold into single spaces")
    func whitespaceIsFlattened() {
        #expect(AddLinkCreateCopy.displayWord("  apple \n pie\t") == "apple pie")
        #expect(AddLinkCreateCopy.displayWord("\n\n") == "")
    }

    @Test("quote marks inside the word cannot collide with the sentence's own quotes")
    func quoteMarksAreNeutralized() {
        let word = "a「b」c『d』e“f”g\"h"
        let shown = AddLinkCreateCopy.displayWord(word)
        #expect(shown == "a'b'c'd'e'f'g'h")
        for language in Self.languages {
            let title = AddLinkCreateCopy.title(target: word, source: "x", language: language)
            #expect(title.contains("a'b'c'd'e'f'g'h"))
        }
    }

    @Test("special and right-to-left text passes through unchanged")
    func specialCharactersSurvive() {
        #expect(AddLinkCreateCopy.displayWord("café") == "café")
        #expect(AddLinkCreateCopy.displayWord("مرحبا") == "مرحبا")
        #expect(AddLinkCreateCopy.displayWord("100% off") == "100% off")
        let title = AddLinkCreateCopy.title(target: "100% %@ off", source: "a", language: .english)
        #expect(title.contains("100% %@ off"), "arguments are substituted, never re-interpreted as a format")
    }

    @Test("the notebook line names the notebook in every locale", arguments: languages)
    func notebookLineNamesNotebook(language: AppLanguage) {
        let line = AddLinkCreateCopy.notebookLine(notebookName: "My Notebook", language: language)
        #expect(line.contains("My Notebook"))
        #expect(line != "addLink.create.notebook")
    }

    @Test("the legacy 建立 key keeps its meaning (it is also the create_card step label)")
    func legacyCreateKeyIsUntouched() {
        #expect(L10n.string("建立", language: .traditionalChinese) == "建立")
        #expect(AddLinkCreateCopy.title(target: "a", source: "b", language: .traditionalChinese) != "建立")
    }

    @Test("the entry resolves the notebook through the shared resolver and never prints an id")
    func notebookNameNeverShowsAnId() {
        let known = Notebook(remoteId: "nb-1", name: "Reading", color: nil, isDefault: false)
        let named = ReviewCardNotebookBadgeResolver.badge(for: "nb-1", notebooks: [known]).name
        #expect(AddLinkCreateCopy.notebookLine(notebookName: named, language: .english).contains("Reading"))

        let unknown = ReviewCardNotebookBadgeResolver.badge(for: "nb-unsynced-42", notebooks: []).name
        #expect(!AddLinkCreateCopy.notebookLine(notebookName: unknown, language: .english).contains("nb-unsynced-42"))

        let defaultName = ReviewCardNotebookBadgeResolver.badge(
            for: ActiveNotebookStore.defaultNotebookId,
            notebooks: []
        ).name
        #expect(defaultName == L10n.string("todayReview.card.notebook.default"))
        #expect(defaultName != ActiveNotebookStore.defaultNotebookId, "the server sentinel is never shown")
    }
}
