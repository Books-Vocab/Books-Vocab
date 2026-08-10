import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("VocabularySyncEngine")
struct VocabularySyncEngineTests {
    @Test("successful add converges by the server card id")
    func successfulAddConverges() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let entry = makeEntry(word: "chateau,")
        context.insert(entry)
        try context.save()

        let service = FakeVocabularySyncService()
        service.addResponse = KGAddResponse(
            created: 1,
            skipped: 0,
            duplicates: [],
            cardIds: [entry.word: "card-1"]
        )

        let result = await VocabularySyncEngine().execute(
            pendingEntries: [entry],
            modelContext: context,
            service: service,
            emit: { _ in }
        )

        #expect(result.terminalOutcome == .completed)
        #expect(entry.kgCardId == "card-1")
        #expect(entry.isSynced)
        #expect(service.calls == ["add", "trigger", "pushStates", "pushEvents", "pull", "pullReviewEvents"])
    }

    @Test("trigger failure is partial and does not prevent the remaining sync stages")
    func partialFailureContinues() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let entry = makeEntry(word: "partial")
        context.insert(entry)
        try context.save()

        let service = FakeVocabularySyncService()
        service.triggerError = TestError.expected

        let result = await VocabularySyncEngine().execute(
            pendingEntries: [entry],
            modelContext: context,
            service: service,
            emit: { _ in }
        )

        #expect(result.terminalOutcome == .partial)
        #expect(service.calls.contains("pull"))
    }

    @Test("batch delete failure falls back to per-card delete")
    func deleteFallback() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let entry = makeEntry(word: "fallback")
        entry.queueDelete()
        context.insert(entry)
        try context.save()

        let service = FakeVocabularySyncService()
        service.batchDeleteError = TestError.expected

        let result = await VocabularySyncEngine().execute(
            pendingEntries: [entry],
            modelContext: context,
            service: service,
            emit: { _ in }
        )

        #expect(result.terminalOutcome == .completed)
        #expect(service.calls.contains("batchDelete"))
        #expect(service.calls.contains("delete"))
        #expect(try context.fetch(FetchDescriptor<VocabularyEntry>()).isEmpty)
    }

    @Test("cancellation keeps the user-cancelled terminal outcome")
    func cancellationWins() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let entry = makeEntry(word: "cancel")
        context.insert(entry)
        try context.save()

        let service = FakeVocabularySyncService()
        service.blockAdd = true
        let task = Task { @MainActor in
            await VocabularySyncEngine().execute(
                pendingEntries: [entry],
                modelContext: context,
                service: service,
                emit: { _ in }
            )
        }
        await service.waitUntilAddStarted()
        task.cancel()
        let result = await task.value

        #expect(result.terminalOutcome == .keepCancelled)
        #expect(!entry.isFailed)
    }

    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([VocabularyEntry.self, Notebook.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    private func makeEntry(word: String) -> VocabularyEntry {
        VocabularyEntry(
            word: word,
            translation: "translation",
            context: "context",
            bookTitle: "book"
        )
    }
}

private enum TestError: Error {
    case expected
}

@MainActor
private final class FakeVocabularySyncService: VocabularySyncEngineServing {
    var addResponse = KGAddResponse(created: 0, skipped: 0, duplicates: [], cardIds: [:])
    var triggerError: Error?
    var batchDeleteError: Error?
    var blockAdd = false
    private(set) var calls: [String] = []
    private var addStarted = false

    func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse {
        calls.append("add")
        addStarted = true
        if blockAdd {
            try await Task.sleep(for: .seconds(60))
        }
        return addResponse
    }

    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse {
        calls.append("batchDelete")
        if let batchDeleteError { throw batchDeleteError }
        return KGBatchDeleteResponse(deleted: words.count, deleted_words: words, not_found: [])
    }

    func deleteCard(word: String, notebookId: String) async throws {
        calls.append("delete")
    }

    func deleteDictionaryCard(cardId: String, notebookId: String) async throws -> KGCard {
        fatalError("not used")
    }

    func triggerPipeline(notebookId: String) async throws {
        calls.append("trigger")
        if let triggerError { throw triggerError }
    }

    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) {
        calls.append("pushStates")
        return (0, 0)
    }

    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) {
        calls.append("pushEvents")
        return (0, 0)
    }

    func pullCardsToLocal(
        container: ModelContainer,
        progress: ((String, Int, Int) -> Void)?,
        notebookId: String?
    ) async throws -> KGPullOutcome {
        calls.append("pull")
        return .unchanged
    }

    func pullReviewEvents(container: ModelContainer) async throws {
        calls.append("pullReviewEvents")
    }

    func waitUntilAddStarted() async {
        while !addStarted {
            await Task.yield()
        }
    }
}
