#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

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
        #expect(vm.visibleSentences.first?.text.contains("Hello") == true)
        #expect(vm.visibleSentences.first?.speaker == "Maya")
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

    @Test func subtitle_state_unavailable_when_content_parses_to_zero_sentences() {
        // Empty / whitespace-only SRT previously fell through to `.loaded`
        // unconditionally — the bubble layer then rendered a blank void that was
        // visually indistinguishable from `.loading` and `.unavailable`. A parse
        // that yields zero sentences must converge to `.unavailable` so the
        // explicit hint shows instead of an empty-but-"loaded" window.
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.setSubtitleLoading()
        vm.applySubtitle(content: "")
        #expect(vm.subtitleState == .unavailable)
        #expect(vm.visibleSentences.isEmpty)

        vm.applySubtitle(content: "   \n\n  \n")
        #expect(vm.subtitleState == .unavailable)
    }

    @Test func subtitle_state_unavailable_on_malformed_srt() {
        // Garbage with no parseable cue blocks → zero sentences → unavailable,
        // not a false `.loaded`.
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.applySubtitle(content: "not a valid srt at all")
        #expect(vm.subtitleState == .unavailable)
        #expect(vm.visibleSentences.isEmpty)
    }

    // MARK: - #20  Completed-episode position-0 explicit save

    // The confirmed bug: `saveProgress` had an unconditional
    // `if currentTime == 0 { return }`. When a *completed* episode is reopened,
    // `restoreProgress` deliberately skips the seek, so `currentTime` stays 0.
    // If the user pauses immediately, the explicit `.pause` write was silently
    // dropped — the pause position never recorded and the row could never leave
    // the "completed" state. The decision is hoisted to `shouldPersist`.

    @Test func position_zero_pause_persists() {
        // Completed episode reopened then paused at 0 — must persist.
        #expect(PodcastPlayerView.shouldPersist(currentTime: 0, reason: .pause))
    }

    @Test func position_zero_episode_switch_persists() {
        // Switching away at position 0 is a durable, user-visible transition.
        #expect(PodcastPlayerView.shouldPersist(currentTime: 0, reason: .episodeSwitch))
    }

    @Test func position_zero_tick_is_dropped() {
        // An automatic tick at 0 is noise (audio hasn't advanced) — drop it.
        #expect(PodcastPlayerView.shouldPersist(currentTime: 0, reason: .tick) == false)
    }

    @Test func nonzero_tick_persists() {
        // Normal mid-playback tick must continue to persist unchanged.
        #expect(PodcastPlayerView.shouldPersist(currentTime: 42, reason: .tick))
    }

    @Test func nonzero_pause_persists() {
        #expect(PodcastPlayerView.shouldPersist(currentTime: 42, reason: .pause))
    }

    // MARK: - Completed decision hoisted for deferred (post-teardown) persist

    // `onDisappear` snapshots the completed flag SYNCHRONOUSLY before tearing
    // the vm down (`shutdown()` flips `state` → `.idle`), then persists OFF the
    // teardown runloop turn — a synchronous `modelContext.save()` inside
    // `_UIHostingView.__deallocating_deinit` posts a SwiftData notification that
    // `_SwiftData_SwiftUI` observes against the deallocating `@Query` →
    // EXC_BREAKPOINT (confirmed via crash report). Hoisting the rule to a pure
    // function keeps the snapshot and the live-vm wrapper computing it identically.

    @Test func completed_when_ready_at_end() {
        #expect(PodcastPlayerView.isCompleted(currentTime: 1832, duration: 1832, isReady: true))
    }

    @Test func completed_within_one_second_of_end() {
        // Playback rarely lands exactly on duration; within 1s counts as done.
        #expect(PodcastPlayerView.isCompleted(currentTime: 1831.5, duration: 1832, isReady: true))
    }

    @Test func not_completed_mid_episode() {
        #expect(PodcastPlayerView.isCompleted(currentTime: 6, duration: 1832, isReady: true) == false)
    }

    @Test func not_completed_when_not_ready() {
        // Why the snapshot must be taken BEFORE `shutdown()`: once state flips to
        // `.idle` (isReady == false), an at-the-end position must NOT be recorded
        // as completed — that would be the deferred-save regression we guard against.
        #expect(PodcastPlayerView.isCompleted(currentTime: 1832, duration: 1832, isReady: false) == false)
    }

    @Test func not_completed_with_zero_duration() {
        // Duration unknown (load failed / pre-ready) → never mark completed.
        #expect(PodcastPlayerView.isCompleted(currentTime: 0, duration: 0, isReady: true) == false)
    }

    // MARK: - Podcast 初始定位 bootstrap

    @Test func bootstrap_initial_progress_primes_mid_episode_position() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.applySubtitle(content: """
        1
        00:00:00,000 --> 00:00:01,000
        [Maya] Hello.

        2
        00:00:01,000 --> 00:00:02,000
        [Kai] Midway.

        3
        00:00:02,000 --> 00:00:03,000
        [Maya] Finish.
        """)

        vm.bootstrapInitialPlaybackPosition(1.5)

        #expect(vm.initialPositionResolved)
        #expect(vm.currentTime == 1.5)
        #expect(vm.renderState?.sentenceId == 1)
        #expect(vm.scrollLeadSentenceId == 1, "bootstrap must pin to current sentence, not lead into the next one")
    }

    @Test func bootstrap_without_saved_progress_keeps_opening_state() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.applySubtitle(content: """
        1
        00:00:00,000 --> 00:00:01,000
        [Maya] Hello.
        """)

        vm.bootstrapInitialPlaybackPosition(nil)

        #expect(vm.initialPositionResolved)
        #expect(vm.currentTime == 0)
        #expect(vm.renderState == nil)
        #expect(vm.scrollLeadSentenceId == nil)
    }

    @Test func bootstrap_zero_progress_keeps_opening_state() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.applySubtitle(content: """
        1
        00:00:00,000 --> 00:00:01,000
        [Maya] Hello.
        """)

        vm.bootstrapInitialPlaybackPosition(0)

        #expect(vm.initialPositionResolved)
        #expect(vm.currentTime == 0)
        #expect(vm.renderState == nil)
        #expect(vm.scrollLeadSentenceId == nil)
    }
}
#endif
