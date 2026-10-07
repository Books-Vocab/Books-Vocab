//
//  QueryPicksUpBackgroundSaveTests.swift
//  Books & Vocab Tests
//
//  Issue #2051 evidence: after a `BackgroundSyncActor` save, a live `@Query`
//  (and a plain mainContext fetch) observes the new rows WITHOUT any
//  `mainContext.save()` "poke". The poke that used to follow every sync in
//  `BooksAndVocabApp` was therefore a no-op for visibility; its only real
//  effect was flushing unrelated half-edited UI state and swallowing errors.
//

import SwiftData
import SwiftUI
import Testing
import UIKit
@testable import BooksAndVocab

@MainActor
struct QueryPicksUpBackgroundSaveTests {

    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            Book.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    private func makeCard(id: String, content: String) throws -> KGCard {
        let json = """
        {"id":"\(id)","content":"\(content)","meaning":"meaning-\(content)",
         "pos":null,"difficulty":null,"difficultyTier":null,"note":null,
         "collocations":[],"examples":["an example"],"mode":"recognition",
         "isDeleted":false,"notebookId":"default"}
        """.data(using: .utf8)!
        return try JSONDecoder().decode(KGCard.self, from: json)
    }

    /// Records what the live `@Query` last rendered.
    @MainActor
    final class QuerySink {
        var words: [String] = []
        var renderCount = 0
    }

    struct QueryProbeView: View {
        @Query(sort: \VocabularyEntry.word) private var entries: [VocabularyEntry]
        let sink: QuerySink

        var body: some View {
            sink.words = entries.map(\.word)
            sink.renderCount += 1
            return Color.clear.frame(width: 1, height: 1)
        }
    }

    /// Spin the main run loop (letting SwiftUI/SwiftData deliver updates)
    /// until `condition` holds or `timeout` elapses.
    private func waitUntil(
        timeout: Duration = .seconds(5),
        _ condition: () -> Bool
    ) async throws -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while clock.now < deadline {
            if condition() { return true }
            try await Task.sleep(for: .milliseconds(50))
        }
        return condition()
    }

    @Test func liveQuery_seesBackgroundActorSave_withoutMainContextSave() async throws {
        let container = try makeContainer()
        let sink = QuerySink()

        let host = UIHostingController(
            rootView: QueryProbeView(sink: sink).modelContainer(container)
        )
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 100, height: 100))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer { window.isHidden = true }

        // Baseline: the query has rendered once with an empty store.
        #expect(try await waitUntil { sink.renderCount > 0 })
        #expect(sink.words.isEmpty)

        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(id: "c1", content: "ephemeral")
        try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        // No mainContext.save() anywhere in this test.
        #expect(container.mainContext.hasChanges == false)
        #expect(try await waitUntil { sink.words == ["ephemeral"] })
        #expect(container.mainContext.hasChanges == false)

        // The main context's own fetch agrees.
        let fetched = try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(fetched.map(\.word) == ["ephemeral"])
    }
}
