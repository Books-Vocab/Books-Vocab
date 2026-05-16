//
//  BackgroundSyncActorTests.swift
//  BooksBrowserTests
//
//  Regression coverage for the PR #533 sync-down gap: `KGCard.source`
//  was decoded but never consumed by `BackgroundSyncActor`, so cards
//  pulled from the backend permanently lost their book title / chapter
//  and displayed the hard-coded "Knowledge Graph" placeholder.
//

import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

@MainActor
struct BackgroundSyncActorTests {

    // MARK: - Helpers

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
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        return try ModelContainer(for: schema, configurations: [config])
    }

    /// Build a `KGCard` from JSON so the test exercises the same decoding
    /// path production uses (plain `JSONDecoder`, camelCase keys, no
    /// snake-case strategy). `sourceJSON` is spliced in verbatim or omitted.
    private func makeCard(
        id: String = "c1",
        content: String,
        sourceJSON: String?
    ) throws -> KGCard {
        let sourceFragment = sourceJSON.map { ",\"source\":\($0)" } ?? ""
        let json = """
        {"id":"\(id)","content":"\(content)","meaning":"meaning-\(content)",
         "pos":null,"difficulty":null,"difficultyTier":null,"note":null,
         "collocations":[],"examples":["an example"],"mode":"recognition",
         "isDeleted":false,"notebookId":"default"\(sourceFragment)}
        """.data(using: .utf8)!
        return try JSONDecoder().decode(KGCard.self, from: json)
    }

    private func fetchEntry(_ container: ModelContainer, word: String) throws -> VocabularyEntry? {
        let context = ModelContext(container)
        let entries = try context.fetch(FetchDescriptor<VocabularyEntry>())
        return entries.first { $0.word == word }
    }

    // MARK: - resolveSource (pure-function fallback semantics)

    @Test func resolveSource_book_with_title_and_chapter() throws {
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"book","title":"Moby Dick","url":null,"chapter":"Loomings"}"#
        )
        let resolved = BackgroundSyncActor.resolveSource(from: card)
        #expect(resolved.bookTitle == "Moby Dick")
        #expect(resolved.chapterTitle == "Loomings")
    }

    @Test func resolveSource_book_without_chapter_yields_nil_chapter() throws {
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"book","title":"Moby Dick","url":null}"#
        )
        let resolved = BackgroundSyncActor.resolveSource(from: card)
        #expect(resolved.bookTitle == "Moby Dick")
        #expect(resolved.chapterTitle == nil)
    }

    @Test func resolveSource_nil_source_falls_back_to_placeholder() throws {
        let card = try makeCard(content: "ephemeral", sourceJSON: nil)
        let resolved = BackgroundSyncActor.resolveSource(from: card)
        #expect(resolved.bookTitle == BackgroundSyncActor.fallbackBookTitle)
        #expect(resolved.chapterTitle == nil)
    }

    @Test func resolveSource_empty_title_falls_back_to_placeholder() throws {
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"book","title":"   ","url":null,"chapter":"Loomings"}"#
        )
        let resolved = BackgroundSyncActor.resolveSource(from: card)
        #expect(resolved.bookTitle == BackgroundSyncActor.fallbackBookTitle)
        // No usable book title means no chapter either.
        #expect(resolved.chapterTitle == nil)
    }

    @Test func resolveSource_non_book_type_falls_back_to_placeholder() throws {
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"web","title":"Wikipedia","url":"https://x"}"#
        )
        let resolved = BackgroundSyncActor.resolveSource(from: card)
        #expect(resolved.bookTitle == BackgroundSyncActor.fallbackBookTitle)
        #expect(resolved.chapterTitle == nil)
    }

    // MARK: - pullCardsToLocal (end-to-end sync-down)

    @Test func syncDown_newEntry_reflects_book_source() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"book","title":"Pride and Prejudice","url":null,"chapter":"Chapter 3"}"#
        )

        try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        let entry = try fetchEntry(container, word: "ephemeral")
        #expect(entry?.bookTitle == "Pride and Prejudice")
        #expect(entry?.chapterTitle == "Chapter 3")
    }

    @Test func syncDown_newEntry_without_source_falls_back_to_placeholder() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(content: "transient", sourceJSON: nil)

        try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        let entry = try fetchEntry(container, word: "transient")
        #expect(entry?.bookTitle == BackgroundSyncActor.fallbackBookTitle)
        #expect(entry?.chapterTitle == nil)
    }

    @Test func syncDown_existingEntry_backfills_book_source() async throws {
        let container = try makeContainer()

        // Seed a synced entry that previously lost its source (placeholder title).
        let seedContext = ModelContext(container)
        let stale = VocabularyEntry(
            word: "ephemeral",
            translation: "meaning-ephemeral",
            context: "an example",
            bookTitle: BackgroundSyncActor.fallbackBookTitle
        )
        stale.notebookId = "default"
        stale.markSynced()
        seedContext.insert(stale)
        try seedContext.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(
            content: "ephemeral",
            sourceJSON: #"{"type":"book","title":"Moby Dick","url":null,"chapter":"Loomings"}"#
        )

        try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        let entry = try fetchEntry(container, word: "ephemeral")
        #expect(entry?.bookTitle == "Moby Dick")
        #expect(entry?.chapterTitle == "Loomings")
    }

    @Test func syncDown_existingEntry_keeps_local_title_when_server_source_missing() async throws {
        let container = try makeContainer()

        // A locally-known book title must not be clobbered by a card that
        // carries no usable server source.
        let seedContext = ModelContext(container)
        let local = VocabularyEntry(
            word: "ephemeral",
            translation: "meaning-ephemeral",
            context: "an example",
            bookTitle: "Locally Known Book",
            chapterTitle: "Local Chapter"
        )
        local.notebookId = "default"
        local.markSynced()
        seedContext.insert(local)
        try seedContext.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(content: "ephemeral", sourceJSON: nil)

        try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        let entry = try fetchEntry(container, word: "ephemeral")
        #expect(entry?.bookTitle == "Locally Known Book")
        #expect(entry?.chapterTitle == "Local Chapter")
    }
}
