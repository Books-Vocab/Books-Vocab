//
//  BackgroundSyncActorTests.swift
//  Books & Vocab Tests
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
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
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

    // MARK: - Orphan cleanup safety-valve signalling
    //
    // Regression coverage for the sync-boundary leak: when a FULL sync's
    // orphan cleanup is blocked by the mass-deletion safety valve, the local
    // store still holds ghost entries. `pullCardsToLocal` must report this so
    // the caller can refuse to advance the incremental boundary (forcing a
    // full-sync retry next time) instead of permanently stranding the ghosts.

    /// Seed `count` server-synced entries that will become orphans (they are
    /// absent from any fetched-card list).
    private func seedSyncedEntries(_ container: ModelContainer, count: Int) throws {
        let context = ModelContext(container)
        for i in 0..<count {
            let entry = VocabularyEntry(
                word: "orphan-\(i)",
                translation: "meaning-\(i)",
                context: "ctx",
                bookTitle: "Book"
            )
            entry.notebookId = "default"
            entry.markSynced()
            context.insert(entry)
        }
        try context.save()
    }

    @Test func fullSync_safetyValve_blocked_reports_orphanCleanupBlocked() async throws {
        let container = try makeContainer()
        // 10 local synced entries; server returns just 1 → ratio 0.1 < 0.3.
        try seedSyncedEntries(container, count: 10)

        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(content: "survivor", sourceJSON: nil)

        let result = try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: false,
            progress: { _, _, _ in }
        )

        #expect(result.orphanCleanupBlocked == true)

        // Ghost entries must still be present — cleanup was skipped.
        let context = ModelContext(container)
        let remaining = try context.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(remaining.contains { $0.word == "orphan-0" })
    }

    @Test func fullSync_normal_reports_orphanCleanupNotBlocked() async throws {
        let container = try makeContainer()
        // 2 local synced entries; server returns both → no orphans, no block.
        let context = ModelContext(container)
        for word in ["alpha", "beta"] {
            let entry = VocabularyEntry(
                word: word,
                translation: "meaning-\(word)",
                context: "ctx",
                bookTitle: "Book"
            )
            entry.notebookId = "default"
            entry.markSynced()
            context.insert(entry)
        }
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let cards = [
            try makeCard(id: "a", content: "alpha", sourceJSON: nil),
            try makeCard(id: "b", content: "beta", sourceJSON: nil),
        ]

        let result = try await actor.pullCardsToLocal(
            fetchedCards: cards,
            isIncremental: false,
            progress: { _, _, _ in }
        )

        #expect(result.orphanCleanupBlocked == false)
    }

    @Test func incrementalSync_never_reports_orphanCleanupBlocked() async throws {
        let container = try makeContainer()
        // Many local synced entries, tiny incremental batch — orphan cleanup
        // does not run at all on incremental syncs, so it can never be blocked.
        try seedSyncedEntries(container, count: 10)

        let actor = BackgroundSyncActor(modelContainer: container)
        let card = try makeCard(content: "survivor", sourceJSON: nil)

        let result = try await actor.pullCardsToLocal(
            fetchedCards: [card],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        #expect(result.orphanCleanupBlocked == false)
    }

    // MARK: - clearUserData (logout / account-switch isolation)
    //
    // Regression coverage for the multi-account leak: the local clear path
    // deleted vocab / review / notebook but left PodcastSeries /
    // PodcastEpisode / PodcastProgress — and `Book` — behind, so account B
    // saw account A's followed series, playback progress, *and imported books
    // with reading position/progress*. `clearUserData` must wipe all eight
    // user-scoped @Model types in one pass.

    /// Seed N user-scoped books with reading position + progress set, so the
    /// test proves the leaked private state (locator / progression) is cleared.
    private func seedBooks(_ container: ModelContainer, count: Int) throws {
        let context = ModelContext(container)
        for i in 0..<count {
            let book = Book(
                title: "Book \(i)",
                author: "Author \(i)",
                fileName: "\(UUID().uuidString).epub"
            )
            book.lastReadLocatorJSON = "{\"loc\":\(i)}"
            book.progression = 0.42
            book.preferredNotebookId = "nb-\(i)"
            context.insert(book)
        }
        try context.save()
    }

    /// Seed N series (each with M cascade-owned episodes), K orphan episodes
    /// (no series), and P progress rows.
    private func seedPodcastData(
        _ container: ModelContainer,
        series seriesCount: Int,
        episodesPerSeries: Int,
        orphanEpisodes: Int,
        progress progressCount: Int
    ) throws {
        let context = ModelContext(container)
        for s in 0..<seriesCount {
            let series = PodcastSeries(remoteId: "series-\(s)", title: "Series \(s)", hostNames: ["Host"])
            series.isFollowed = true
            context.insert(series)
            for e in 0..<episodesPerSeries {
                let ep = PodcastEpisode(remoteId: "s\(s)-e\(e)", episodeNumber: e, title: "Ep \(e)", durationSec: 60)
                ep.series = series
                context.insert(ep)
            }
        }
        for o in 0..<orphanEpisodes {
            let ep = PodcastEpisode(remoteId: "orphan-ep-\(o)", episodeNumber: o, title: "Orphan \(o)", durationSec: 60)
            context.insert(ep)
        }
        for p in 0..<progressCount {
            let prog = PodcastProgress(episodeRemoteId: "prog-ep-\(p)", lastPlayedTime: 12.5, completed: false)
            context.insert(prog)
        }
        try context.save()
    }

    @Test func clearUserData_removes_all_podcast_models() async throws {
        let container = try makeContainer()
        try seedSyncedEntries(container, count: 3)
        try seedPodcastData(
            container,
            series: 2,
            episodesPerSeries: 3,   // 6 cascade-owned episodes
            orphanEpisodes: 2,      // 2 series-less orphans
            progress: 4
        )

        // Sanity: data is actually present before the clear.
        let preContext = ModelContext(container)
        #expect(try preContext.fetchCount(FetchDescriptor<PodcastSeries>()) == 2)
        #expect(try preContext.fetchCount(FetchDescriptor<PodcastEpisode>()) == 8) // 6 + 2 orphans
        #expect(try preContext.fetchCount(FetchDescriptor<PodcastProgress>()) == 4)

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.clearUserData(reason: "account-switch")

        let context = ModelContext(container)
        #expect(try context.fetchCount(FetchDescriptor<PodcastSeries>()) == 0)
        #expect(try context.fetchCount(FetchDescriptor<PodcastEpisode>()) == 0)
        #expect(try context.fetchCount(FetchDescriptor<PodcastProgress>()) == 0)
    }

    @Test func clearUserData_still_removes_vocab_review_notebook() async throws {
        let container = try makeContainer()

        let context = ModelContext(container)
        // vocab
        let entry = VocabularyEntry(word: "alpha", translation: "m", context: "ctx", bookTitle: "Book")
        entry.notebookId = "default"
        entry.markSynced()
        context.insert(entry)
        // review
        context.insert(ReviewRecord(word: "alpha", entryID: nil, feedback: 1, reviewedAt: Date()))
        // notebook
        context.insert(Notebook(remoteId: "nb1", name: "NB"))
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.clearUserData(reason: "logout")

        let after = ModelContext(container)
        #expect(try after.fetchCount(FetchDescriptor<VocabularyEntry>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<ReviewRecord>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<Notebook>()) == 0)
    }

    @Test func buildReviewEventsPushPayload_encodesLocalRecords() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let reviewedAt = Date(timeIntervalSince1970: 1_800_000_000)
        let entryID = UUID()
        let entry = VocabularyEntry(word: "alpha", translation: "m", context: "ctx", bookTitle: "Book")
        entry.id = entryID
        entry.kgCardId = "card-alpha"
        entry.markSynced()
        context.insert(entry)
        let record = ReviewRecord(
            word: "alpha",
            entryID: entryID,
            feedback: 1,
            reviewedAt: reviewedAt
        )
        record.id = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!
        record.notebookId = "nb1"
        context.insert(record)
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildReviewEventsPushPayload()

        #expect(payload.count == 1)
        let item = try #require(payload.first)
        #expect(item.event_id == "11111111-1111-1111-1111-111111111111")
        #expect(item.card_id == "card-alpha")
        #expect(item.word_snapshot == "alpha")
        #expect(item.notebook_id == "nb1")
        #expect(item.feedback == 1)
        #expect(item.reviewed_at.contains("2027"))
        #expect(item.created_at.contains("2027"))
    }

    @Test func buildReviewEventsPushPayload_usesFixatedCardIdWhenEntryGone() async throws {
        // 根因迴歸:卡離場(store 裡查無對應 entry)時,固化在 ReviewRecord 上的 kgCardId
        // 仍須讓 card_id 不退化成 nil(舊版即時三段反查到此會回 nil → 後端 card_id NULL)。
        let container = try makeContainer()
        let context = ModelContext(container)
        let record = ReviewRecord(
            word: "orphaned",
            entryID: UUID(),                       // 對應 entry 不存在於 store
            feedback: 1,
            reviewedAt: Date(timeIntervalSince1970: 1_800_000_000),
            kgCardId: "card-fixated",
            intervalBefore: 12.0,
            intervalAfter: 22.8,
            nextReviewBefore: Date(timeIntervalSince1970: 1_800_000_000),
            nextReviewAfter: Date(timeIntervalSince1970: 1_800_082_080),
            reviewCountAfter: 3,
            streakAfter: 2,
            lapseAfter: 1
        )
        record.id = UUID(uuidString: "44444444-4444-4444-4444-444444444444")!
        context.insert(record)
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let item = try #require(try await actor.buildReviewEventsPushPayload().first)
        #expect(item.card_id == "card-fixated")        // 不再退化
        #expect(item.interval_before == 12.0)
        #expect(item.interval_after == 22.8)
        #expect(item.review_count_after == 3)
        #expect(item.streak_after == 2)
        #expect(item.lapse_after == 1)
        #expect(item.next_review_before != nil)
        #expect(item.next_review_after != nil)
    }

    @Test func buildReviewEventsPushPayload_legacyRecordFallsBackToLookup() async throws {
        // legacy 紀錄(kgCardId 未固化)且 entry 仍在:回退舊三段反查仍能解出 card_id。
        let container = try makeContainer()
        let context = ModelContext(container)
        let entryID = UUID()
        let entry = VocabularyEntry(word: "legacy", translation: "m", context: "ctx", bookTitle: "Book")
        entry.id = entryID
        entry.kgCardId = "card-legacy"
        entry.markSynced()
        context.insert(entry)
        let record = ReviewRecord(word: "legacy", entryID: entryID, feedback: 0)  // kgCardId nil
        record.id = UUID(uuidString: "55555555-5555-5555-5555-555555555555")!
        context.insert(record)
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let item = try #require(try await actor.buildReviewEventsPushPayload().first)
        #expect(item.card_id == "card-legacy")          // fallback 反查解出
        #expect(item.interval_after == nil)             // legacy 無 SRS 快照
    }

    @Test func mergeReviewEvents_fixatesRemoteCardIdAndSRS() async throws {
        // 拉回的遠端事件即使本機查無對應 entry,也固化 card_id + SRS,不退化。
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        let remote = [KGReviewEventPayload(
            event_id: "66666666-6666-6666-6666-666666666666",
            card_id: "card-remote",
            word_snapshot: "delta",
            notebook_id: "default",
            feedback: 1,
            reviewed_at: "2026-06-04T10:00:00+00:00",
            created_at: "2026-06-04T10:00:00+00:00",
            interval_before: 12.0,
            interval_after: 22.8,
            next_review_before: "2026-06-04T10:00:00+00:00",
            next_review_after: "2026-06-05T08:48:00+00:00",
            review_count_after: 4,
            streak_after: 3,
            lapse_after: 0
        )]
        try await actor.mergeReviewEvents(remote)

        let context = ModelContext(container)
        let record = try #require(try context.fetch(FetchDescriptor<ReviewRecord>()).first)
        #expect(record.kgCardId == "card-remote")
        #expect(record.intervalAfter == 22.8)
        #expect(record.reviewCountAfter == 4)
        #expect(record.streakAfter == 3)
    }

    @Test func mergeReviewEvents_insertsMissingAndSkipsDuplicates() async throws {
        let container = try makeContainer()
        let seedContext = ModelContext(container)
        let linkedEntry = VocabularyEntry(word: "beta", translation: "m", context: "ctx", bookTitle: "Book")
        linkedEntry.kgCardId = "card-beta"
        linkedEntry.markSynced()
        seedContext.insert(linkedEntry)
        try seedContext.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let eventID = "22222222-2222-2222-2222-222222222222"
        let remote = [KGReviewEventPayload(
            event_id: eventID,
            card_id: "card-beta",
            word_snapshot: "beta",
            notebook_id: "nb2",
            feedback: 0,
            reviewed_at: "2026-06-02T10:00:00+00:00",
            created_at: "2026-06-02T10:00:03+00:00"
        )]

        try await actor.mergeReviewEvents(remote)
        try await actor.mergeReviewEvents(remote)

        let context = ModelContext(container)
        let records = try context.fetch(FetchDescriptor<ReviewRecord>())
        let record = try #require(records.first)
        #expect(records.count == 1)
        #expect(record.id.uuidString == eventID.uppercased())
        #expect(record.entryID == linkedEntry.id)
        #expect(record.word == "beta")
        #expect(record.notebookId == "nb2")
        #expect(record.feedback == 0)
    }

    @Test func mergeReviewEvents_restoresAfterLocalClear() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        let remote = [KGReviewEventPayload(
            event_id: "33333333-3333-3333-3333-333333333333",
            card_id: nil,
            word_snapshot: "gamma",
            notebook_id: "default",
            feedback: 1,
            reviewed_at: "2026-06-03T10:00:00+00:00",
            created_at: "2026-06-03T10:00:03+00:00"
        )]

        try await actor.mergeReviewEvents(remote)
        try await actor.clearUserData(reason: "test-clear")
        try await actor.mergeReviewEvents(remote)

        let context = ModelContext(container)
        let records = try context.fetch(FetchDescriptor<ReviewRecord>())
        #expect(records.count == 1)
        #expect(records.first?.word == "gamma")
    }

    @Test func clearUserData_removes_all_books() async throws {
        let container = try makeContainer()
        try seedBooks(container, count: 3)

        // Sanity: books (with private reading state) are present pre-clear.
        let preContext = ModelContext(container)
        #expect(try preContext.fetchCount(FetchDescriptor<Book>()) == 3)

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.clearUserData(reason: "account-switch")

        let after = ModelContext(container)
        #expect(try after.fetchCount(FetchDescriptor<Book>()) == 0)
    }

    @Test func clearUserData_wipes_books_alongside_other_models() async throws {
        let container = try makeContainer()
        try seedSyncedEntries(container, count: 2)
        try seedPodcastData(
            container,
            series: 1,
            episodesPerSeries: 2,
            orphanEpisodes: 1,
            progress: 1
        )
        try seedBooks(container, count: 2)

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.clearUserData(reason: "account-switch")

        // All user-scoped models gone in one pass — no model type stranded.
        let after = ModelContext(container)
        #expect(try after.fetchCount(FetchDescriptor<VocabularyEntry>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<PodcastSeries>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<PodcastEpisode>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<PodcastProgress>()) == 0)
        #expect(try after.fetchCount(FetchDescriptor<Book>()) == 0)
    }
}
