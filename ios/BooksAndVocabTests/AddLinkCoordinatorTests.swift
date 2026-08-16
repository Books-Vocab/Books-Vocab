import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Graph link coordinator", .serialized)
struct AddLinkCoordinatorTests {
    @Test("local candidates stay notebook-scoped and exclude self/already-linked")
    func localCandidates() {
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let match = Self.entry("lucid", cardID: "target", notebook: "nb")
        let otherNotebook = Self.entry("lucidity", cardID: "other", notebook: "other")
        let linked = Self.entry("lucidly", cardID: "linked", notebook: "nb")
        source.graphLinksByKind = ["related": [
            KGCardLinkSummary(
                id: "link", cardId: "linked", word: "lucidly", kind: "related",
                label: "related", confidence: 1, reason: ""
            )
        ]]

        let result = AddLinkCoordinator.localCandidates(
            query: "lucid",
            sourceEntry: source,
            allEntries: [source, match, otherNotebook, linked]
        )

        #expect(result.map(\.word) == ["lucid"])
    }

    @Test("manual link validation surfaces missing source and treats duplicate as already linked")
    @MainActor
    func manualLinkValidation() async throws {
        let container = try Self.container()
        let target = Self.entry("target", cardID: "target", notebook: "nb")
        let missingSource = Self.entry("source", cardID: "source", notebook: "nb")
        missingSource.kgCardId = nil
        let duplicateSource = Self.entry("source", cardID: "source", notebook: "nb")
        let context = ModelContext(container)
        context.insert(target)
        context.insert(missingSource)
        context.insert(duplicateSource)
        try context.save()

        let missingSourceCoordinator = AddLinkCoordinator()
        await missingSourceCoordinator.linkExisting(
            target: target,
            sourceEntry: missingSource,
            using: StaleProjectionGraphService()
        )
        #expect(missingSourceCoordinator.actionPhase == .failed)
        #expect(missingSourceCoordinator.actionError == .missingSourceCard)

        duplicateSource.insertLink(
            KGCardLinkSummary(
                id: "existing-link", cardId: "target", word: target.word,
                kind: "related", label: "related", confidence: 1, reason: "existing"
            ),
            kind: "related"
        )
        let duplicateCoordinator = AddLinkCoordinator()
        await duplicateCoordinator.linkExisting(
            target: target,
            sourceEntry: duplicateSource,
            using: StaleProjectionGraphService()
        )
        #expect(duplicateCoordinator.actionPhase == .succeeded)
        #expect(duplicateCoordinator.actionError == nil)
        #expect(duplicateSource.graphLinksByKind.values.flatMap { $0 }.count == 1)
    }

    @Test("manual link 409 refreshes graph projection and converges to success")
    @MainActor
    func manualLinkConflictRefreshesProjection() async throws {
        let container = try Self.container()
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let target = Self.entry("target", cardID: "target", notebook: "nb")
        let context = ModelContext(container)
        context.insert(source)
        context.insert(target)
        try context.save()

        let service = StaleProjectionGraphService()
        let coordinator = AddLinkCoordinator()
        await coordinator.linkExisting(
            target: target,
            sourceEntry: source,
            using: service
        )

        #expect(coordinator.actionPhase == .succeeded)
        #expect(coordinator.actionError == nil)
        let link = try #require(source.graphLinksByKind["shares_usage"]?.first)
        #expect(link.id == "server-link")
        #expect(link.cardId == "target")
        #expect(await service.pullNotebookIDs == ["nb"])
    }

    @Test("manual link 409 without matching projection stays failed and rolls back")
    @MainActor
    func manualLinkConflictWithoutProjectionFailsClosed() async throws {
        let container = try Self.container()
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let target = Self.entry("target", cardID: "target", notebook: "nb")
        let context = ModelContext(container)
        context.insert(source)
        context.insert(target)
        try context.save()

        let service = StaleProjectionGraphService(links: [])
        let coordinator = AddLinkCoordinator()
        await coordinator.linkExisting(
            target: target,
            sourceEntry: source,
            using: service
        )

        #expect(coordinator.actionPhase == .failed)
        #expect(coordinator.actionError == .existingLinkRefreshFailed)
        #expect(source.graphLinksByKind.isEmpty)
        #expect(await service.pullNotebookIDs == ["nb"])
    }

    private static func entry(_ word: String, cardID: String, notebook: String) -> VocabularyEntry {
        let value = VocabularyEntry(
            word: word,
            translation: word,
            context: "",
            bookTitle: "Book"
        )
        value.kgCardId = cardID
        value.notebookId = notebook
        return value
    }

    private static func container() throws -> ModelContainer {
        let schema = Schema([VocabularyEntry.self, ReviewRecord.self])
        let configuration = ModelConfiguration(
            isStoredInMemoryOnly: true,
            cloudKitDatabase: .none
        )
        return try ModelContainer(for: schema, configurations: [configuration])
    }
}

@MainActor
private final class StaleProjectionGraphService: GraphServing {
    private let links: [KGGraphLink]
    private(set) var pullNotebookIDs: [String] = []

    init(links: [KGGraphLink]? = nil) {
        self.links = links ?? [
            KGGraphLink(
                id: "server-link",
                fromId: "source",
                toId: "target",
                kind: "shares_usage",
                confidence: 1,
                reason: "existing"
            )
        ]
    }

    func pullGraphLinks() async throws -> [KGGraphLink] { [] }

    func pullGraphLinks(notebookId: String) async throws -> [KGGraphLink] {
        pullNotebookIDs.append(notebookId)
        return links
    }

    func createManualLink(
        fromId: String,
        toId: String,
        notebookId: String
    ) async throws -> KGGraphLink {
        throw KGError.httpError(
            statusCode: 409,
            detail: "Link already exists between these cards"
        )
    }

    func deleteLink(linkId: String, notebookId: String) async throws {}
    func hideLink(linkId: String, notebookId: String) async throws {}
    func unhideLink(linkId: String, notebookId: String) async throws {}
}
