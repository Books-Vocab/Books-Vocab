#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

/// Track-D silent-failure regression net.
///
/// Two confirmed `try?`-swallowed silent failures put the user in a
/// "looks-fine-actually-broken" state:
///   • #5b — `toggleFollow` optimistically flips `isFollowed` in memory (with
///     animation) before persisting; a failed `save()` only logged a warning,
///     so the star showed "followed" yet the state was lost on relaunch.
///   • #3  — subtitle download failure left `subtitleContent == nil`; the
///     player kept playing audio with subtitles permanently missing, no
///     prompt, no retry.
///
/// These tests pin the corrected behaviour: follow-toggle rolls back on save
/// failure, and the player exposes an explicit subtitle load state that can
/// reach `.failed` and recover via reload.
@MainActor
struct PodcastSilentFailureTests {

    private func makeSeries(followed: Bool) -> PodcastSeries {
        let s = PodcastSeries(remoteId: "flow_x", title: "Flow", hostNames: ["Maya", "Kai"])
        s.isFollowed = followed
        return s
    }

    // MARK: - #5b  Follow toggle rollback

    @Test func follow_toggle_persists_on_save_success() {
        let series = makeSeries(followed: false)
        let before = series.updatedAt
        let outcome = PodcastFollowToggle.perform(series: series) { true }
        #expect(outcome == .saved)
        #expect(series.isFollowed == true)
        #expect(series.updatedAt >= before)
    }

    @Test func follow_toggle_rolls_back_on_save_failure() {
        // The optimistic flip must NOT survive a failed save — otherwise the
        // UI keeps showing "followed" while nothing was persisted.
        let series = makeSeries(followed: false)
        let originalUpdatedAt = series.updatedAt
        let outcome = PodcastFollowToggle.perform(series: series) { false }
        #expect(outcome == .rolledBack)
        #expect(series.isFollowed == false, "isFollowed must revert when save fails")
        #expect(series.updatedAt == originalUpdatedAt, "updatedAt must revert when save fails")
    }

    @Test func follow_toggle_rollback_is_symmetric_for_unfollow() {
        // Same guarantee in the other direction: un-following must revert too.
        let series = makeSeries(followed: true)
        let outcome = PodcastFollowToggle.perform(series: series) { false }
        #expect(outcome == .rolledBack)
        #expect(series.isFollowed == true, "un-follow must revert to followed when save fails")
    }

    // MARK: - #3  Subtitle load state

    @Test func subtitle_state_starts_idle() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        #expect(vm.subtitleState == .idle)
    }

    @Test func subtitle_state_reaches_loaded_with_content() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.setSubtitleLoading()
        #expect(vm.subtitleState == .loading)
        let srt = "1\n00:00:00,000 --> 00:00:00,400\n[Maya] Hello\n"
        vm.applySubtitle(content: srt)
        #expect(vm.subtitleState == .loaded)
        #expect(vm.visibleSentences.isEmpty == false)
    }

    @Test func subtitle_state_reaches_failed_on_fetch_failure() {
        // The confirmed bug: a failed subtitle fetch left state silent. The VM
        // must now expose `.failed` so the View can show an inline retry.
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.setSubtitleLoading()
        vm.markSubtitleFailed()
        #expect(vm.subtitleState == .failed)
        #expect(vm.visibleSentences.isEmpty, "no subtitles parsed on failure")
    }

    @Test func subtitle_state_recovers_after_failed_then_retry() {
        // Retry path: a failed load can transition back through loading to
        // loaded once the fetch succeeds.
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.setSubtitleLoading()
        vm.markSubtitleFailed()
        #expect(vm.subtitleState == .failed)

        vm.setSubtitleLoading()
        #expect(vm.subtitleState == .loading)
        let srt = "1\n00:00:00,000 --> 00:00:00,400\n[Maya] Hi\n"
        vm.applySubtitle(content: srt)
        #expect(vm.subtitleState == .loaded)
        #expect(vm.visibleSentences.isEmpty == false)
    }

    @Test func subtitle_state_unavailable_when_episode_has_no_subtitle_url() {
        // An episode that genuinely ships no subtitle URL must surface
        // `.unavailable` so the player view can render an explicit
        // "此集無逐句字幕" hint — distinct from both `.loading` (which
        // previously looked identical) and `.failed` (which would falsely
        // prompt a retry). See state_matrix L410 + track-3.
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.markSubtitleUnavailable()
        #expect(vm.subtitleState == .unavailable)
    }
}
#endif
