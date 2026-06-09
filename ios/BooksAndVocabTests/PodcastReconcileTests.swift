import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct PodcastReconcileTests {

    // MARK: - Helpers

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

    private func makeProgress(_ epId: String, _ updatedAt: Date, _ played: Double) -> PodcastProgress {
        let p = PodcastProgress(episodeRemoteId: epId, lastPlayedTime: played, completed: false)
        p.updatedAt = updatedAt
        return p
    }

    private func makeSeries(_ id: String) -> PodcastSeries {
        PodcastSeries(remoteId: id, title: id, hostNames: ["A", "B"])
    }

    private func makeEpisode(_ remoteId: String, episodeNumber: Int = 1, in series: PodcastSeries) -> PodcastEpisode {
        let ep = PodcastEpisode(remoteId: remoteId, episodeNumber: episodeNumber, title: "T", durationSec: 100)
        ep.series = series
        return ep
    }

    private func summary(_ id: String) -> PodcastSeriesSummary {
        PodcastSeriesSummary(id: id, title: id, author: nil, hostNames: nil, color: nil, coverPattern: nil, coverImageURL: nil, totalDurationSec: nil, episodeCount: nil)
    }

    private func detail(_ id: String, episodes: [Int]) -> PodcastSeriesDetail {
        let eps = episodes.map {
            PodcastEpisodeDetail(
                episodeNumber: $0,
                title: "Ep\($0)",
                durationSec: 60,
                audioAvailable: true,
                subtitleAvailable: true,
                subtitleContent: nil
            )
        }
        return PodcastSeriesDetail(id: id, title: id, author: nil, hostNames: nil, color: nil, coverPattern: nil, coverImageURL: nil, totalDurationSec: nil, episodes: eps, createdAt: nil, updatedAt: nil)
    }

    // MARK: - Sanitize

    @Test func sanitize_collapses_duplicates_to_newest() throws {
        let ctx = try makeContext()
        let now = Date()
        let oldest = makeProgress("ep1", now.addingTimeInterval(-30), 10)
        let middle = makeProgress("ep1", now.addingTimeInterval(-20), 20)
        let newest = makeProgress("ep1", now.addingTimeInterval(-10), 30)
        ctx.insert(oldest); ctx.insert(middle); ctx.insert(newest)
        try ctx.save()

        let winner = PodcastSyncService.sanitizeProgressDuplicates(for: "ep1", context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(winner?.lastPlayedTime == 30)
        #expect(all.first?.lastPlayedTime == 30)
    }

    @Test func sanitize_tie_breaker_picks_larger_played_time() throws {
        let ctx = try makeContext()
        let same = Date()
        let a = makeProgress("ep1", same, 10)
        let b = makeProgress("ep1", same, 50)
        let c = makeProgress("ep1", same, 30)
        ctx.insert(a); ctx.insert(b); ctx.insert(c)
        try ctx.save()

        _ = PodcastSyncService.sanitizeProgressDuplicates(for: "ep1", context: ctx)
        try ctx.save()
        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(all.first?.lastPlayedTime == 50)
    }

    @Test func sanitize_no_rows_returns_nil() throws {
        let ctx = try makeContext()
        let winner = PodcastSyncService.sanitizeProgressDuplicates(for: "missing", context: ctx)
        #expect(winner == nil)
    }

    // MARK: - Reconcile

    @Test func reconcile_tombstones_missing_series() throws {
        let ctx = try makeContext()
        let s1 = makeSeries("a")
        let s2 = makeSeries("b")
        ctx.insert(s1); ctx.insert(s2)
        try ctx.save()

        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a")],
            fetchedDetails: [:],
            context: ctx
        )
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        let aliveA = all.first { $0.remoteId == "a" }
        let tombB = all.first { $0.remoteId == "b" }
        #expect(aliveA?.isSoftDeleted == false)
        #expect(tombB?.isSoftDeleted == true)
    }

    @Test func reconcile_empty_server_list_does_not_tombstone() throws {
        // 根因回歸網：/api/podcasts 在 S3 index.json 短暫讀不到時回 `[]`（HTTP 200），
        // fetchSeriesList 不拋例外 → summaries 為空。空 list 必須當非權威跳過 tombstone，
        // 否則整個本地 catalog 被 soft-delete，書架 podcast 區塊整片消失。
        let ctx = try makeContext()
        let s1 = makeSeries("a")
        let s2 = makeSeries("b")
        ctx.insert(s1); ctx.insert(s2)
        try ctx.save()

        PodcastSyncService.reconcileLocalState(
            serverSummaries: [],
            fetchedDetails: [:],
            context: ctx
        )
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        #expect(all.allSatisfy { $0.isSoftDeleted == false }, "空 server list 不可 tombstone 任何 series")
    }

    @Test func reconcile_resurrects_returned_series() throws {
        let ctx = try makeContext()
        let s = makeSeries("a")
        s.isSoftDeleted = true
        ctx.insert(s)
        try ctx.save()

        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a")],
            fetchedDetails: [:],
            context: ctx
        )
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<PodcastSeries>()).first
        #expect(fetched?.isSoftDeleted == false)
    }

    @Test func reconcile_deletes_orphan_progress() throws {
        let ctx = try makeContext()
        let s = makeSeries("a")
        ctx.insert(s)
        let livingEp = makeEpisode("a_ep_01", episodeNumber: 1, in: s)
        ctx.insert(livingEp)
        let livingProg = makeProgress("a_ep_01", Date(), 10)
        let orphanProg = makeProgress("a_ep_99", Date(), 20)
        ctx.insert(livingProg); ctx.insert(orphanProg)
        try ctx.save()

        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a")],
            fetchedDetails: ["a": detail("a", episodes: [1])],
            context: ctx
        )
        try ctx.save()

        let progs = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(progs.count == 1, "orphan progress should be the only one removed")
        #expect(progs.first?.episodeRemoteId == "a_ep_01")
        let eps = try ctx.fetch(FetchDescriptor<PodcastEpisode>())
        #expect(eps.count == 1, "living episode must not be collateral-deleted")
    }

    @Test func reconcile_deletes_episodes_removed_by_server() throws {
        let ctx = try makeContext()
        let s = makeSeries("a")
        ctx.insert(s)
        let ep1 = makeEpisode("a_ep_01", episodeNumber: 1, in: s)
        let ep2 = makeEpisode("a_ep_02", episodeNumber: 2, in: s)
        ctx.insert(ep1); ctx.insert(ep2)
        try ctx.save()

        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a")],
            fetchedDetails: ["a": detail("a", episodes: [1])],
            context: ctx
        )
        try ctx.save()

        let eps = try ctx.fetch(FetchDescriptor<PodcastEpisode>())
        #expect(eps.count == 1, "ep_02 should be deleted, ep_01 kept")
        #expect(eps.first?.remoteId == "a_ep_01")
        let series = try ctx.fetch(FetchDescriptor<PodcastSeries>())
        #expect(series.first?.isSoftDeleted == false, "series must remain alive")
    }

    @Test func reconcile_skips_episodes_when_detail_fetch_failed() throws {
        let ctx = try makeContext()
        let sA = makeSeries("a"); ctx.insert(sA)
        let sB = makeSeries("b"); ctx.insert(sB)
        let epA = makeEpisode("a_ep_01", episodeNumber: 1, in: sA)
        let epB1 = makeEpisode("b_ep_01", episodeNumber: 1, in: sB)
        let epB2 = makeEpisode("b_ep_02", episodeNumber: 2, in: sB)
        ctx.insert(epA); ctx.insert(epB1); ctx.insert(epB2)
        try ctx.save()

        // Server returns both summaries; only A's detail succeeded.
        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a"), summary("b")],
            fetchedDetails: ["a": detail("a", episodes: [1])],
            context: ctx
        )
        try ctx.save()

        let aEps = try ctx.fetch(FetchDescriptor<PodcastEpisode>(predicate: #Predicate { $0.series?.remoteId == "a" }))
        let bEps = try ctx.fetch(FetchDescriptor<PodcastEpisode>(predicate: #Predicate { $0.series?.remoteId == "b" }))
        #expect(aEps.count == 1, "A's reconcile path executed")
        #expect(bEps.count == 2, "B's episodes must NOT be touched when detail fetch failed")
    }

    @Test func reconcile_empty_episodes_in_detail_treated_as_transient() throws {
        let ctx = try makeContext()
        let s = makeSeries("a"); ctx.insert(s)
        let ep1 = makeEpisode("a_ep_01", episodeNumber: 1, in: s)
        let ep2 = makeEpisode("a_ep_02", episodeNumber: 2, in: s)
        ctx.insert(ep1); ctx.insert(ep2)
        let prog = makeProgress("a_ep_01", Date(), 50)
        ctx.insert(prog)
        try ctx.save()

        // Server returned detail with empty episodes — treat as transient,
        // do NOT mass-delete episodes/progress.
        PodcastSyncService.reconcileLocalState(
            serverSummaries: [summary("a")],
            fetchedDetails: ["a": detail("a", episodes: [])],
            context: ctx
        )
        try ctx.save()

        let eps = try ctx.fetch(FetchDescriptor<PodcastEpisode>())
        #expect(eps.count == 2, "empty server episodes must not nuke local episodes")
        let progs = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(progs.count == 1, "progress must survive transient empty detail")
    }
}
