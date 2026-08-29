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

    @Test("local candidates exclude entries with an empty card id")
    func localCandidatesExcludeEmptyCardID() {
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let unresolved = Self.entry("lucid", cardID: "", notebook: "nb")

        let result = AddLinkCoordinator.localCandidates(
            query: "lucid",
            sourceEntry: source,
            allEntries: [source, unresolved]
        )

        #expect(result.isEmpty)
    }

    @Test("local candidates exclude archived, deleting, whitespace-card, and other-notebook entries")
    func localCandidatesExcludeIneligibleEntries() {
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let match = Self.entry("lucid", cardID: "target", notebook: "nb")
        let archived = Self.entry("lucid archive", cardID: "archived", notebook: "nb")
        archived.isArchived = true
        let deleting = Self.entry("lucid delete", cardID: "deleting", notebook: "nb")
        deleting.syncAction = .delete
        let whitespaceCard = Self.entry("lucid unresolved", cardID: "   ", notebook: "nb")
        let otherNotebook = Self.entry("lucid other", cardID: "other", notebook: "other")
        let linked = Self.entry("lucid linked", cardID: "linked", notebook: "nb")
        source.graphLinksByKind = ["related": [
            KGCardLinkSummary(
                id: "link", cardId: "linked", word: linked.word, kind: "related",
                label: "related", confidence: 1, reason: ""
            )
        ]]

        let result = AddLinkCoordinator.localCandidates(
            query: "lucid",
            sourceEntry: source,
            allEntries: [source, match, archived, deleting, whitespaceCard, otherNotebook, linked]
        )

        #expect(result.map(\.word) == ["lucid"])
    }

    @Test("manual link rejects an out-of-scope target before creating a link")
    @MainActor
    func manualLinkRejectsOutOfScopeTarget() async throws {
        let container = try Self.container()
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let target = Self.entry("target", cardID: "target", notebook: "other")
        let context = ModelContext(container)
        context.insert(source)
        context.insert(target)
        try context.save()

        let service = RecordingGraphService()
        let coordinator = AddLinkCoordinator()
        await coordinator.linkExisting(target: target, sourceEntry: source, using: service)

        #expect(coordinator.actionPhase == .failed)
        #expect(service.createCallCount == 0)
        #expect(source.graphLinksByKind.isEmpty)
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

    @Test("failed manual link rolls back and supports a retry")
    @MainActor
    func manualLinkFailureCanRetry() async throws {
        let container = try Self.container()
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let target = Self.entry("target", cardID: "target", notebook: "nb")
        let context = ModelContext(container)
        context.insert(source)
        context.insert(target)
        try context.save()

        let service = RetryableGraphService()
        let coordinator = AddLinkCoordinator()
        await coordinator.linkExisting(target: target, sourceEntry: source, using: service)

        #expect(coordinator.actionPhase == .failed)
        #expect(coordinator.actionError == .existingLinkFailed)
        #expect(source.graphLinksByKind.isEmpty)

        await coordinator.linkExisting(target: target, sourceEntry: source, using: service)

        #expect(coordinator.actionPhase == .succeeded)
        #expect(coordinator.actionError == nil)
        #expect(service.createCallCount == 2)
        #expect(source.graphLinksByKind.values.flatMap { $0 }.count == 1)
    }

    @Test("manual link exposes linking and cancelled outcomes without committing")
    @MainActor
    func manualLinkCanBeCancelled() async throws {
        let container = try Self.container()
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let target = Self.entry("target", cardID: "target", notebook: "nb")
        let context = ModelContext(container)
        context.insert(source)
        context.insert(target)
        try context.save()

        let service = BlockingGraphService()
        let coordinator = AddLinkCoordinator()
        #expect(coordinator.actionPhase == .idle)

        coordinator.startLinkExisting(target: target, sourceEntry: source, using: service)
        #expect(coordinator.actionPhase == .linking)
        while !service.hasStarted {
            await Task.yield()
        }

        coordinator.cancel()
        #expect(coordinator.actionPhase == .cancelled)
        service.resume()
        await Task.yield()
        await Task.yield()

        #expect(coordinator.actionPhase == .cancelled)
        #expect(source.graphLinksByKind.isEmpty)
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

@MainActor
private final class RecordingGraphService: GraphServing {
    private(set) var createCallCount = 0

    func pullGraphLinks() async throws -> [KGGraphLink] { [] }

    func pullGraphLinks(notebookId: String) async throws -> [KGGraphLink] { [] }

    func createManualLink(
        fromId: String,
        toId: String,
        notebookId: String
    ) async throws -> KGGraphLink {
        createCallCount += 1
        return KGGraphLink(
            id: "created-link",
            fromId: fromId,
            toId: toId,
            kind: "related",
            confidence: 1,
            reason: "created"
        )
    }

    func deleteLink(linkId: String, notebookId: String) async throws {}
    func hideLink(linkId: String, notebookId: String) async throws {}
    func unhideLink(linkId: String, notebookId: String) async throws {}
}

@MainActor
private final class RetryableGraphService: GraphServing {
    private(set) var createCallCount = 0

    func pullGraphLinks() async throws -> [KGGraphLink] { [] }

    func pullGraphLinks(notebookId: String) async throws -> [KGGraphLink] { [] }

    func createManualLink(
        fromId: String,
        toId: String,
        notebookId: String
    ) async throws -> KGGraphLink {
        createCallCount += 1
        if createCallCount == 1 {
            throw KGError.serverError("temporary link failure")
        }
        return KGGraphLink(
            id: "retry-link",
            fromId: fromId,
            toId: toId,
            kind: "related",
            confidence: 1,
            reason: "retry succeeded"
        )
    }

    func deleteLink(linkId: String, notebookId: String) async throws {}
    func hideLink(linkId: String, notebookId: String) async throws {}
    func unhideLink(linkId: String, notebookId: String) async throws {}
}

@MainActor
private final class BlockingGraphService: GraphServing {
    private(set) var hasStarted = false
    private var continuation: CheckedContinuation<KGGraphLink, Never>?

    func pullGraphLinks() async throws -> [KGGraphLink] { [] }

    func pullGraphLinks(notebookId: String) async throws -> [KGGraphLink] { [] }

    func createManualLink(
        fromId: String,
        toId: String,
        notebookId: String
    ) async throws -> KGGraphLink {
        hasStarted = true
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
        }
    }

    func resume() {
        continuation?.resume(returning: KGGraphLink(
            id: "cancelled-link",
            fromId: "source",
            toId: "target",
            kind: "related",
            confidence: 1,
            reason: "should not commit"
        ))
        continuation = nil
    }

    func deleteLink(linkId: String, notebookId: String) async throws {}
    func hideLink(linkId: String, notebookId: String) async throws {}
    func unhideLink(linkId: String, notebookId: String) async throws {}
}
