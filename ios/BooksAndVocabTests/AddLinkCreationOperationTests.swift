import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Missing-target Add Link operation")
struct AddLinkCreationOperationTests {
    @Test("create CTA distinguishes missing and hidden local target states")
    func localTargetGuard() {
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "new-word", sourceEntry: source, allEntries: [source]
        ) == .missing)

        let pending = Self.entry("pending", cardID: nil, notebook: "nb")
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "PENDING", sourceEntry: source, allEntries: [source, pending]
        ) == .pending)

        let failed = Self.entry("failed", cardID: nil, notebook: "nb")
        failed.syncState = .failed
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "failed", sourceEntry: source, allEntries: [source, failed]
        ) == .failed)

        let archived = Self.entry("archived", cardID: "archived", notebook: "nb")
        archived.isArchived = true
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "archived", sourceEntry: source, allEntries: [source, archived]
        ) == .archived)

        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "source", sourceEntry: source, allEntries: [source]
        ) == .source)
    }

    /// #2727 acceptance: Add Link opened from the archive list. The archived
    /// source's detail sheet is fed `knowledgeListPredicate()` entries (active,
    /// all notebooks); the coordinator must scope them to the source's notebook.
    @Test("archived source: same-notebook active word is a link candidate, other notebooks are not")
    func archivedSourceSeesOnlySameNotebookActiveWords() throws {
        let container = try ModelContainer(
            for: VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = ModelContext(container)
        let source = Self.entry("archivedword", cardID: "src", notebook: "nb")
        source.isArchived = true
        let sameNotebook = Self.entry("run", cardID: "run", notebook: "nb")
        let otherNotebook = Self.entry("walk", cardID: "walk", notebook: "other")
        for value in [source, sameNotebook, otherNotebook] {
            value.syncStatus = 1
            context.insert(value)
        }
        try context.save()

        let activeEntries = try context.fetch(FetchDescriptor<VocabularyEntry>(
            predicate: VocabularyEntry.knowledgeListPredicate()
        ))
        #expect(!activeEntries.contains { $0.id == source.id })

        // Pre-fix input: WordDetailSheet defaulted to an empty pool.
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "run", sourceEntry: source, allEntries: []
        ) == .missing)

        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "run", sourceEntry: source, allEntries: activeEntries
        ) == .active)
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "walk", sourceEntry: source, allEntries: activeEntries
        ) == .missing)

        let candidates = AddLinkCoordinator.localCandidates(
            query: "run", sourceEntry: source, allEntries: activeEntries
        )
        #expect(candidates.map(\.id) == [sameNotebook.id])
        #expect(AddLinkCoordinator.localCandidates(
            query: "walk", sourceEntry: source, allEntries: activeEntries
        ).isEmpty)
    }

    @Test("request encodes the backend command contract")
    func requestEncoding() throws {
        let request = KGAddLinkOperationRequest(
            fromId: "source-card", targetWord: "luminous", translation: nil,
            context: "a luminous room", source: .book(title: "Book"),
            sourceLang: "en", targetLang: "zh-Hant"
        )
        let object = try #require(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any]
        )
        #expect(object["from_id"] as? String == "source-card")
        #expect(object["target_word"] as? String == "luminous")
        #expect(object["source_lang"] as? String == "en")
        #expect(object["target_lang"] as? String == "zh-Hant")
        #expect(object["translation"] == nil)
    }

    @Test("terminal warning status remains queryable")
    func statusDecoding() throws {
        let data = try #require("""
        {"operationId":"op-1","notebookId":"default","status":"succeeded_with_warnings","sequence":12,
         "steps":[{"id":"enrich","status":"warning","current":1,"total":1,"detailCode":"retryable"}],
         "targetCardId":"card-1","linkId":"link-1","warnings":["enrichment_failed"],"errorCode":null}
        """.data(using: .utf8))
        let status = try JSONDecoder().decode(KGAddLinkOperationStatus.self, from: data)
        #expect(status.isTerminal)
        #expect(status.completedWithWarnings)
        #expect(status.targetCardId == "card-1")
        #expect(status.linkId == "link-1")
    }

    private static func entry(_ word: String, cardID: String?, notebook: String) -> VocabularyEntry {
        let value = VocabularyEntry(word: word, translation: word, context: "", bookTitle: "Book")
        value.kgCardId = cardID
        value.notebookId = notebook
        return value
    }
}
