#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Regression net for PR #400 — the `vocabularyContext = nil` race that fired
/// when the user tapped a word before `.task` had populated the player state.
/// The fix collapsed `loadedEpisode` / `loadedSeries` / `resolvedNotebookId`
/// into synchronous SwiftData lookups. These tests exercise the resolver
/// directly so the contract is pinned outside the SwiftUI runtime.
@MainActor
struct PodcastVocabContextTests {

    private func makeContext() throws -> ModelContext {
        let schema = Schema([
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self,
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            Book.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: [config])
        return ModelContext(container)
    }

    @discardableResult
    private func attachSeriesAndEpisode(
        epId: String,
        seriesId: String = "S1",
        in ctx: ModelContext
    ) -> (PodcastSeries, PodcastEpisode) {
        let series = PodcastSeries(remoteId: seriesId, title: seriesId, hostNames: ["A", "B"])
        ctx.insert(series)
        let ep = PodcastEpisode(remoteId: epId, episodeNumber: 1, title: "Ep1", durationSec: 60)
        ep.series = series
        ctx.insert(ep)
        return (series, ep)
    }

    private func makeVocabularyContext(
        ctx: ModelContext,
        vocabulary: [VocabularyEntry] = [],
        notebookId: String = "default"
    ) -> PodcastVocabularyContext {
        let (series, episode) = attachSeriesAndEpisode(epId: UUID().uuidString, in: ctx)
        return PodcastVocabularyContext(
            vocabulary: vocabulary,
            modelContext: ctx,
            series: series,
            episode: episode,
            notebookId: notebookId,
            toastCoordinator: AppToastCoordinator()
        )
    }

    private func makeEntry(
        word: String,
        notebookId: String = "default",
        rootForm: String? = nil,
        inflections: [String] = [],
        syncStatus: Int = 0,
        actionType: String = "add"
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: "t",
            context: "ctx",
            explanation: nil,
            partOfSpeech: nil,
            bookTitle: "Series",
            chapterTitle: "Episode"
        )
        entry.notebookId = notebookId
        entry.rootForm = rootForm
        entry.inflections = inflections
        entry.syncStatus = syncStatus
        entry.actionType = actionType
        return entry
    }

    // MARK: - Race regression (PR #400)

    @Test func resolveVocabularyContext_returnsNilWhenEpisodeRowMissing() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()
        let result = PodcastPlayerView.resolveVocabularyContext(
            episodeId: "missing",
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(result == nil, "cold-start mid-sync: no episode row → context must stay nil rather than crash or fabricate")
    }

    @Test func resolveVocabularyContext_becomesNonNilAsSoonAsEpisodeHydrated() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()
        let epId = "S1_ep_01"

        let before = PodcastPlayerView.resolveVocabularyContext(
            episodeId: epId,
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(before == nil)

        attachSeriesAndEpisode(epId: epId, in: ctx)
        // Pre-existing vocabulary entry to prove the resolver wires the array
        // through verbatim (PR #400 path uses `allVocabulary` for fast
        // `existingEntry` lookup in the player tap handler).
        let priorEntry = VocabularyEntry(
            word: "alpha",
            translation: "α",
            context: "",
            explanation: nil,
            partOfSpeech: nil,
            bookTitle: "B",
            chapterTitle: "C"
        )
        ctx.insert(priorEntry)
        try ctx.save()

        // Same frame — no `await`/`Task` between `save()` and re-resolve. The
        // PR #400 contract is precisely that this synchronous call returns
        // non-nil. Do not async-ify this path without rewriting the contract.
        let after = PodcastPlayerView.resolveVocabularyContext(
            episodeId: epId,
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: [priorEntry]
        )
        #expect(after != nil, "PR #400 contract — synchronous resolver must produce a context the instant the SwiftData row exists, with no `.task` hydration required")
        #expect(after?.episode.remoteId == epId)
        #expect(after?.series.remoteId == "S1")
        #expect(after?.notebookId == "default")
        #expect(after?.vocabulary.count == 1, "resolver must wire the vocabulary array through to the context verbatim")
        #expect(after?.vocabulary.first?.word == "alpha")
    }

    @Test func resolveVocabularyContext_returnsNilWhenSeriesDetached() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()
        let epId = "orphan_ep"

        // Episode without parent series — should not crash, must stay nil so
        // the tap silently no-ops rather than building a half-initialized context.
        let ep = PodcastEpisode(remoteId: epId, episodeNumber: 1, title: "T", durationSec: 60)
        ctx.insert(ep)
        try ctx.save()

        let result = PodcastPlayerView.resolveVocabularyContext(
            episodeId: epId,
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(result == nil)
    }

    @Test func resolveVocabularyContext_recomputesOnEpisodeSwitch() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()

        let series = PodcastSeries(remoteId: "S1", title: "Series 1", hostNames: ["A"])
        ctx.insert(series)
        let epA = PodcastEpisode(remoteId: "epA", episodeNumber: 1, title: "A", durationSec: 60)
        epA.series = series
        let epB = PodcastEpisode(remoteId: "epB", episodeNumber: 2, title: "B", durationSec: 60)
        epB.series = series
        ctx.insert(epA); ctx.insert(epB)
        try ctx.save()

        let ctxA = PodcastPlayerView.resolveVocabularyContext(
            episodeId: "epA",
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: []
        )
        let ctxB = PodcastPlayerView.resolveVocabularyContext(
            episodeId: "epB",
            modelContext: ctx,
            rawNotebookId: "default",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(ctxA?.episode.remoteId == "epA")
        #expect(ctxB?.episode.remoteId == "epB")
        #expect(ctxA?.series.remoteId == ctxB?.series.remoteId,
                "both episodes belong to the same series — resolver must wire the right one without leaking state across `episodeId`")
    }

    // MARK: - Notebook resolution edge cases

    @Test func resolveVocabularyContext_fallsBackToDefaultWhenCandidateNotebookMissing() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()
        attachSeriesAndEpisode(epId: "S1_ep_01", in: ctx)
        // Insert a live (unrelated) notebook so the cold-start guard does not bail.
        let nb = Notebook(remoteId: "other", name: "Other")
        ctx.insert(nb)
        try ctx.save()

        let result = PodcastPlayerView.resolveVocabularyContext(
            episodeId: "S1_ep_01",
            modelContext: ctx,
            rawNotebookId: "ghost_notebook",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(result?.notebookId == "default",
                "candidate that does not match any live Notebook (and table is non-empty) → fall back to `default` sentinel")
    }

    @Test func resolveVocabularyContext_keepsCandidateOnColdStartWithEmptyNotebookTable() throws {
        let ctx = try makeContext()
        let toast = AppToastCoordinator()
        attachSeriesAndEpisode(epId: "S1_ep_01", in: ctx)
        try ctx.save()

        // Notebook table is empty → resolveNotebookId's cold-start guard
        // keeps the candidate as-is rather than silently rewriting to `default`,
        // which would permanently mis-bind first-login outbox entries.
        let result = PodcastPlayerView.resolveVocabularyContext(
            episodeId: "S1_ep_01",
            modelContext: ctx,
            rawNotebookId: "candidate_nb",
            toastCoordinator: toast,
            vocabulary: []
        )
        #expect(result?.notebookId == "candidate_nb",
                "cold-start (empty Notebook table) must preserve the candidate notebook id — see `VocabularyEntry.resolveNotebookId` cold-start guard")
    }

    // MARK: - Capture parity with reader

    @Test func existingEntry_matchesByRootFormAndInflectionLowercase() throws {
        let ctx = try makeContext()
        let entry = makeEntry(
            word: "lay",
            notebookId: "default",
            rootForm: "lie",
            inflections: ["lays", "laid", "laying"]
        )
        let capture = makeVocabularyContext(ctx: ctx, vocabulary: [entry])

        #expect(capture.existingEntry(matching: "Lay") != nil)
        #expect(capture.existingEntry(matching: "Lie") != nil)
        #expect(capture.existingEntry(matching: "LAID") != nil)
        #expect(capture.existingEntry(matching: "unrelated") == nil)
    }

    @Test func saveEntry_restoresEntryQueuedForDeleteAndUpdatesTranslation() throws {
        let ctx = try makeContext()
        let queued = makeEntry(word: "ghost", notebookId: "default", actionType: "delete")
        queued.syncStatus = 0
        ctx.insert(queued)
        try ctx.save()
        let originalId = queued.persistentModelID

        let capture = makeVocabularyContext(ctx: ctx, vocabulary: [queued])
        let inserted = capture.saveEntry(
            selection: WordSelection(word: "ghost", context: "ctx", position: .zero),
            translation: "new translation",
            rootForm: "ghost"
        )

        #expect(inserted == true)
        let all = try ctx.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(all.count == 1)
        let restored = try #require(all.first)
        #expect(restored.persistentModelID == originalId)
        #expect(restored.syncAction == .add)
        #expect(restored.translation == "new translation")
        #expect(restored.rootForm == "ghost")
    }

    @Test func deleteEntry_queuesSyncedEntryAndRemovesUnsyncedEntry() throws {
        let ctx = try makeContext()
        let synced = makeEntry(word: "anchor", notebookId: "default", syncStatus: 1)
        let pending = makeEntry(word: "draft", notebookId: "default", syncStatus: 0)
        ctx.insert(synced)
        ctx.insert(pending)
        try ctx.save()

        let capture = makeVocabularyContext(ctx: ctx, vocabulary: [synced, pending])
        capture.deleteEntry(matching: "anchor")
        capture.deleteEntry(matching: "draft")

        let all = try ctx.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(all.count == 1)
        let surviving = try #require(all.first)
        #expect(surviving.word == "anchor")
        #expect(surviving.syncAction == .delete)
        #expect(surviving.syncState == .pending)
    }
}
#endif
