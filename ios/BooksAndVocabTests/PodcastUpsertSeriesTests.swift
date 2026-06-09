import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

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
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: [config])
        return ModelContext(container)
    }

    private func detail(_ id: String, episodes: [Int], title: String? = nil,
                        coverImageURL: String? = nil) -> PodcastSeriesDetail {
        let eps = episodes.map {
            PodcastEpisodeDetail(episodeNumber: $0, title: "Ep\($0)", durationSec: 60,
                                 audioAvailable: true, subtitleAvailable: true, subtitleContent: nil)
        }
        return PodcastSeriesDetail(id: id, title: title ?? id, author: nil, hostNames: nil,
                                   color: nil, coverPattern: nil, coverImageURL: coverImageURL,
                                   totalDurationSec: nil,
                                   episodes: eps, createdAt: nil, updatedAt: nil)
    }

    @Test func upsert_writes_coverImageURL() throws {
        let ctx = try makeContext()
        PodcastSyncService.upsertSeries(
            detail: detail("a", episodes: [1], coverImageURL: "/api/podcasts/a/cover"), context: ctx)
        try ctx.save()
        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>()).first
        #expect(series?.coverImageURL == "/api/podcasts/a/cover")
    }

    @Test func upsert_nil_coverImageURL_for_legacy_series() throws {
        let ctx = try makeContext()
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1]), context: ctx)
        try ctx.save()
        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>()).first
        #expect(series?.coverImageURL == nil)
    }

    @Test func upsert_nil_cover_clears_stale_cache() throws {
        let ctx = try makeContext()
        // Series with a remote cover, simulated as already downloaded to disk.
        PodcastSyncService.upsertSeries(
            detail: detail("a", episodes: [1], coverImageURL: "/api/podcasts/a/cover?v=abc123"), context: ctx)
        let series = try #require(try ctx.fetch(FetchDescriptor<PodcastSeries>()).first)
        let cacheURL = PodcastSyncService.cachedCoverURL(
            seriesId: "a", coverImageURL: "/api/podcasts/a/cover?v=abc123")
        defer { try? FileManager.default.removeItem(at: cacheURL) }
        try FileManager.default.createDirectory(
            at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([0x89, 0x50, 0x4E, 0x47]).write(to: cacheURL)
        series.coverImagePath = cacheURL.path
        try ctx.save()

        // Server retracts the cover → orphaned cache must be dropped so the card
        // degrades back to the procedural cover instead of a stale photo.
        PodcastSyncService.upsertSeries(detail: detail("a", episodes: [1]), context: ctx)
        try ctx.save()

        #expect(series.coverImagePath == nil, "stale coverImagePath must be cleared")
        #expect(!FileManager.default.fileExists(atPath: cacheURL.path),
                "orphaned cache file must be deleted")
    }

    @Test func cachedCoverURL_path_shape() {
        let url = PodcastSyncService.cachedCoverURL(seriesId: "deep_work")
        #expect(url.lastPathComponent == "deep_work.png")
        #expect(url.deletingLastPathComponent().lastPathComponent == "podcast-covers")
    }

    @Test func cachedCoverURL_uses_cover_version_when_present() {
        let url = PodcastSyncService.cachedCoverURL(
            seriesId: "deep_work",
            coverImageURL: "/api/podcasts/deep_work/cover?v=abc123_-")
        #expect(url.lastPathComponent == "deep_work_abc123_-.png")
        #expect(url.deletingLastPathComponent().lastPathComponent == "podcast-covers")
    }

    @Test func removeCachedCover_does_not_delete_prefix_collision_series() throws {
        let target = PodcastSyncService.cachedCoverURL(
            seriesId: "a",
            coverImageURL: "/api/podcasts/a/cover?v=old")
        let sibling = PodcastSyncService.cachedCoverURL(
            seriesId: "a_b",
            coverImageURL: "/api/podcasts/a_b/cover?v=live")
        defer {
            try? FileManager.default.removeItem(at: target)
            try? FileManager.default.removeItem(at: sibling)
        }
        try FileManager.default.createDirectory(
            at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([1]).write(to: target)
        try Data([2]).write(to: sibling)

        PodcastSyncService.removeCachedCover(seriesId: "a", path: target.path)

        #expect(!FileManager.default.fileExists(atPath: target.path))
        #expect(FileManager.default.fileExists(atPath: sibling.path))
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
