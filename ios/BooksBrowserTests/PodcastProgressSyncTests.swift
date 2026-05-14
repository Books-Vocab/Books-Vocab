import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

@MainActor
struct PodcastProgressSyncTests {

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
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [config])
        return ModelContext(container)
    }

    private func makeProgress(_ epId: String, _ updatedAt: Date, _ played: Double) -> PodcastProgress {
        let p = PodcastProgress(episodeRemoteId: epId, lastPlayedTime: played, completed: false)
        p.updatedAt = updatedAt
        return p
    }

    private func remote(_ series: String, _ ep: Int, _ pos: Double, _ dur: Double, _ updatedAt: String)
        -> PodcastRemoteProgressItem
    {
        PodcastRemoteProgressItem(
            seriesId: series, epNum: ep,
            positionSec: pos, durationSec: dur,
            updatedAt: updatedAt
        )
    }

    // MARK: - Remote ID parsing

    @Test func parse_episode_remote_id_basic() {
        let parsed = PodcastSyncService.parseEpisodeRemoteId("flow_950f1a7d_ep_01")
        #expect(parsed?.seriesId == "flow_950f1a7d")
        #expect(parsed?.episodeNumber == 1)
    }

    @Test func parse_episode_remote_id_two_digit() {
        let parsed = PodcastSyncService.parseEpisodeRemoteId("flow_x_ep_42")
        #expect(parsed?.seriesId == "flow_x")
        #expect(parsed?.episodeNumber == 42)
    }

    @Test func parse_episode_remote_id_rejects_missing_marker() {
        #expect(PodcastSyncService.parseEpisodeRemoteId("flow_no_marker") == nil)
        #expect(PodcastSyncService.parseEpisodeRemoteId("") == nil)
    }

    @Test func parse_episode_remote_id_rejects_non_numeric_ep() {
        #expect(PodcastSyncService.parseEpisodeRemoteId("flow_ep_abc") == nil)
    }

    @Test func parse_episode_remote_id_round_trips_with_builder() {
        let id = PodcastSyncService.episodeRemoteId(seriesId: "abc_xyz", episodeNumber: 7)
        let parsed = PodcastSyncService.parseEpisodeRemoteId(id)
        #expect(parsed?.seriesId == "abc_xyz")
        #expect(parsed?.episodeNumber == 7)
    }

    // MARK: - Throttle decision

    @Test func throttle_first_write_always_runs() {
        var state = PodcastProgressPushState()
        let decision = state.shouldPush(
            position: 0.0, duration: 100.0, now: Date(), reason: .tick
        )
        #expect(decision == true)
    }

    @Test func throttle_skips_writes_within_10_seconds_and_under_5_percent() {
        var state = PodcastProgressPushState()
        let t0 = Date()
        _ = state.shouldPush(position: 10.0, duration: 100.0, now: t0, reason: .tick)
        let later = t0.addingTimeInterval(5)
        let again = state.shouldPush(position: 12.0, duration: 100.0, now: later, reason: .tick)
        #expect(again == false)
    }

    @Test func throttle_passes_after_10_seconds() {
        var state = PodcastProgressPushState()
        let t0 = Date()
        _ = state.shouldPush(position: 10.0, duration: 100.0, now: t0, reason: .tick)
        let later = t0.addingTimeInterval(11)
        let again = state.shouldPush(position: 11.0, duration: 100.0, now: later, reason: .tick)
        #expect(again == true)
    }

    @Test func throttle_passes_when_position_jumps_5_percent_even_within_window() {
        var state = PodcastProgressPushState()
        let t0 = Date()
        _ = state.shouldPush(position: 10.0, duration: 100.0, now: t0, reason: .tick)
        let later = t0.addingTimeInterval(2)
        let again = state.shouldPush(position: 16.0, duration: 100.0, now: later, reason: .tick)
        #expect(again == true)
    }

    @Test func throttle_pause_reason_always_bypasses_gates() {
        var state = PodcastProgressPushState()
        let t0 = Date()
        _ = state.shouldPush(position: 10.0, duration: 100.0, now: t0, reason: .tick)
        let later = t0.addingTimeInterval(1)
        let again = state.shouldPush(position: 10.5, duration: 100.0, now: later, reason: .pause)
        #expect(again == true)
    }

    @Test func throttle_episode_switch_reason_bypasses() {
        var state = PodcastProgressPushState()
        let t0 = Date()
        _ = state.shouldPush(position: 10.0, duration: 100.0, now: t0, reason: .tick)
        let again = state.shouldPush(
            position: 10.1, duration: 100.0,
            now: t0.addingTimeInterval(1), reason: .episodeSwitch
        )
        #expect(again == true)
    }

    @Test func throttle_zero_duration_never_pushes_on_tick() {
        var state = PodcastProgressPushState()
        let decision = state.shouldPush(
            position: 5.0, duration: 0.0, now: Date(), reason: .tick
        )
        #expect(decision == false)
    }

    // MARK: - Merge (remote → local SwiftData)

    @Test func merge_inserts_when_local_missing() throws {
        let ctx = try makeContext()
        let item = remote("flow", 1, 42.0, 300.0, "2026-05-14T12:00:00+00:00")
        PodcastSyncService.mergeRemoteProgress(remote: [item], context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(all.first?.episodeRemoteId == "flow_ep_01")
        #expect(all.first?.lastPlayedTime == 42.0)
    }

    @Test func merge_overwrites_when_remote_is_newer() throws {
        let ctx = try makeContext()
        let oldDate = ISO8601DateFormatter().date(from: "2026-05-14T11:00:00Z")!
        let stale = makeProgress("flow_ep_01", oldDate, 10.0)
        ctx.insert(stale)
        try ctx.save()

        let item = remote("flow", 1, 80.0, 300.0, "2026-05-14T12:00:00+00:00")
        PodcastSyncService.mergeRemoteProgress(remote: [item], context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(all.first?.lastPlayedTime == 80.0)
    }

    @Test func merge_keeps_local_when_local_is_newer() throws {
        let ctx = try makeContext()
        let newerDate = ISO8601DateFormatter().date(from: "2026-05-14T13:00:00Z")!
        let fresh = makeProgress("flow_ep_01", newerDate, 250.0)
        ctx.insert(fresh)
        try ctx.save()

        let item = remote("flow", 1, 10.0, 300.0, "2026-05-14T12:00:00+00:00")
        PodcastSyncService.mergeRemoteProgress(remote: [item], context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(all.first?.lastPlayedTime == 250.0)
    }

    @Test func merge_ignores_malformed_updated_at() throws {
        let ctx = try makeContext()
        let item = remote("flow", 1, 80.0, 300.0, "not-a-date")
        PodcastSyncService.mergeRemoteProgress(remote: [item], context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 0)
    }

    @Test func merge_collapses_duplicate_local_rows_before_compare() throws {
        // CloudKit drift can leave two local rows for the same episode. Merge
        // must converge to a single row whose value reflects the LWW outcome.
        let ctx = try makeContext()
        let base = ISO8601DateFormatter().date(from: "2026-05-14T10:00:00Z")!
        ctx.insert(makeProgress("flow_ep_01", base, 5.0))
        ctx.insert(makeProgress("flow_ep_01", base.addingTimeInterval(60), 25.0))
        try ctx.save()

        let item = remote("flow", 1, 120.0, 300.0, "2026-05-14T12:00:00+00:00")
        PodcastSyncService.mergeRemoteProgress(remote: [item], context: ctx)
        try ctx.save()

        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 1)
        #expect(all.first?.lastPlayedTime == 120.0)
    }

    @Test func merge_skips_unparseable_remote_id() throws {
        let ctx = try makeContext()
        let bad = PodcastRemoteProgressItem(
            seriesId: "", epNum: 0,
            positionSec: 10.0, durationSec: 100.0,
            updatedAt: "2026-05-14T12:00:00+00:00"
        )
        PodcastSyncService.mergeRemoteProgress(remote: [bad], context: ctx)
        try ctx.save()
        let all = try ctx.fetch(FetchDescriptor<PodcastProgress>())
        #expect(all.count == 0)
    }
}
