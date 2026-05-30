import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

/// Locks the dedup/reuse contract of `upsertSeries`. The method was rewritten to
/// replace an N+1 per-episode `context.fetch` (one fetch per episode, painful at
/// 1000+ episodes on @MainActor) with a single fetch + in-memory
/// `[remoteId: PodcastEpisode]` index. These tests guarantee the optimization did
/// not change behaviour: existing episodes are reused (not duplicated) and new
/// ones inserted.
@MainActor
struct PodcastUpsertSeriesTests {

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
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [config])
        return ModelContext(container)
    }

    private func detail(_ id: String, episodes: [Int], title: String? = nil) -> PodcastSeriesDetail {
        let eps = episodes.map {
            PodcastEpisodeDetail(episodeNumber: $0, title: "Ep\($0)", durationSec: 60,
                                 audioAvailable: true, subtitleAvailable: true)
        }
        return PodcastSeriesDetail(id: id, title: title ?? id, author: nil, hostNames: nil,
                                   color: nil, coverPattern: nil, totalDurationSec: nil,
                                   episodes: eps, createdAt: nil, updatedAt: nil)
    }

    @Test func upsert_inserts_new_series_and_episodes() throws {
        let ctx = try makeContext()
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1, 2]), context: ctx)
        try ctx.save()

        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        #expect(series.count == 1)
        #expect(series.first?.episodeCount == 2)
        let eps = try ctx.fetch(FetchDescriptor<PodcastEpisode>()).sorted { $0.episodeNumber < $1.episodeNumber }
        #expect(eps.count == 2)
        #expect(eps.map(\.remoteId) == ["a_ep_01", "a_ep_02"])
        #expect(eps.allSatisfy { $0.series?.remoteId == "a" })
    }

    @Test func upsert_reuses_existing_episodes_no_duplicates() throws {
        let ctx = try makeContext()
        // Seed series + ep_01 already present.
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1]), context: ctx)
        try ctx.save()
        let firstEp = try ctx.fetch(FetchDescriptor<PodcastEpisode>()).first
        let firstEpPersistentID = firstEp?.persistentModelID

        // Server now reports eps [1, 2]: ep_01 must be REUSED (same row), ep_02 new.
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1, 2]), context: ctx)
        try ctx.save()

        let eps = try ctx.fetch(FetchDescriptor<PodcastEpisode>())
        #expect(eps.count == 2, "ep_01 must be reused, not duplicated")
        let ep01 = eps.first { $0.remoteId == "a_ep_01" }
        #expect(ep01?.persistentModelID == firstEpPersistentID, "ep_01 must be the same persisted row")
        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        #expect(series.count == 1, "series must not be duplicated either")
    }

    @Test func upsert_updates_mutable_fields_in_place() throws {
        let ctx = try makeContext()
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1], title: "Old"), context: ctx)
        try ctx.save()

        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1], title: "New"), context: ctx)
        try ctx.save()

        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        #expect(series.count == 1)
        #expect(series.first?.title == "New", "series title must update in place")
    }
}
