import Foundation
import Testing
@testable import BooksAndVocab

/// The series-hero primary action is a pure projection of (tier × preview ×
/// availability × progress). It drives the hero CTA label/icon AND whether the
/// tap navigates into the player or routes to the login/paywall gate, so it
/// must stay in lock-step with `PodcastAccess` tier predicates.
@Suite("PodcastHeroAction")
struct PodcastHeroActionTests {
    private func action(
        tier: PodcastTier,
        episodeNumber: Int = 1,
        previewAvailable: Bool = true,
        audioAvailable: Bool = true,
        hasProgress: Bool = false,
        allCompleted: Bool = false
    ) -> PodcastHeroAction {
        PodcastAccess.heroAction(
            tier: tier,
            episodeNumber: episodeNumber,
            previewAvailable: previewAvailable,
            audioAvailable: audioAvailable,
            hasProgress: hasProgress,
            allCompleted: allCompleted
        )
    }

    @Test func guestAlwaysSignsIn() {
        #expect(action(tier: .guest) == .signIn)
        // even a previewable ep1 — guests can't play anything.
        #expect(action(tier: .guest, episodeNumber: 1, hasProgress: true) == .signIn)
    }

    @Test func freeLockedEpisodeUpgrades() {
        // ep2+ for free → locked → upgrade
        #expect(action(tier: .free, episodeNumber: 2) == .upgrade)
        // ep1 with no preview asset → locked → upgrade (mirrors showsProLock)
        #expect(action(tier: .free, episodeNumber: 1, previewAvailable: false) == .upgrade)
    }

    @Test func freePreviewableEpisodeIsPreview() {
        // free ep1 with a preview asset → preview CTA, regardless of progress.
        #expect(action(tier: .free, episodeNumber: 1, previewAvailable: true) == .preview)
        #expect(action(tier: .free, episodeNumber: 1, previewAvailable: true, hasProgress: true) == .preview)
    }

    @Test func unavailableAudioWinsOverPlayButNotOverLock() {
        // pro on an episode whose audio isn't ready → unavailable
        #expect(action(tier: .pro, audioAvailable: false) == .unavailable)
        // but a locked (guest) episode shows the gate even if audio is missing —
        // lock is evaluated before availability.
        #expect(action(tier: .guest, audioAvailable: false) == .signIn)
    }

    @Test func proProgressionPlayResumeReplay() {
        // fresh, never played → play
        #expect(action(tier: .pro, hasProgress: false, allCompleted: false) == .play)
        // mid-episode → resume
        #expect(action(tier: .pro, hasProgress: true, allCompleted: false) == .resume)
        // whole series done → replay (takes priority over resume)
        #expect(action(tier: .pro, hasProgress: true, allCompleted: true) == .replay)
    }

    @Test func navigationIntentSplitsGateFromPlay() {
        // signIn / upgrade route to the gate (no navigation); the rest navigate.
        #expect(PodcastHeroAction.signIn.navigatesToPlayer == false)
        #expect(PodcastHeroAction.upgrade.navigatesToPlayer == false)
        #expect(PodcastHeroAction.unavailable.navigatesToPlayer == false)
        #expect(PodcastHeroAction.preview.navigatesToPlayer == true)
        #expect(PodcastHeroAction.play.navigatesToPlayer == true)
        #expect(PodcastHeroAction.resume.navigatesToPlayer == true)
        #expect(PodcastHeroAction.replay.navigatesToPlayer == true)
    }
}
