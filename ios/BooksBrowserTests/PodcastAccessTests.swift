import Foundation
import Testing
@testable import BooksBrowser

/// Client-side tier policy — must stay in lock-step with the backend
/// `podcast_access.py` (guest browses but can't play; free gets ep1 preview
/// only; pro full). These are the predicates that drive lock badges, the
/// preview banner, and the login/paywall routing.
@Suite("PodcastAccess")
struct PodcastAccessTests {
    @Test func proWinsRegardlessOfToken() {
        #expect(PodcastAccess.tier(hasProAccess: true, hasToken: true) == .pro)
        // pro entitlement implies a token in practice, but the predicate must
        // not depend on token presence once pro is true.
        #expect(PodcastAccess.tier(hasProAccess: true, hasToken: false) == .pro)
    }

    @Test func tokenWithoutProIsFree() {
        #expect(PodcastAccess.tier(hasProAccess: false, hasToken: true) == .free)
    }

    @Test func noTokenIsGuest() {
        #expect(PodcastAccess.tier(hasProAccess: false, hasToken: false) == .guest)
    }

    @Test func guestCanPlayNothing() {
        #expect(PodcastAccess.canPlay(tier: .guest, episodeNumber: 1) == false)
        #expect(PodcastAccess.canPlay(tier: .guest, episodeNumber: 2) == false)
    }

    @Test func freeCanPlayOnlyEpisodeOne() {
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 1) == true)
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 2) == false)
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 5) == false)
    }

    @Test func proCanPlayEverything() {
        #expect(PodcastAccess.canPlay(tier: .pro, episodeNumber: 1) == true)
        #expect(PodcastAccess.canPlay(tier: .pro, episodeNumber: 9) == true)
    }

    @Test func previewPlaybackOnlyForFreeEpisodeOne() {
        #expect(PodcastAccess.isPreviewPlayback(tier: .free, episodeNumber: 1) == true)
        #expect(PodcastAccess.isPreviewPlayback(tier: .free, episodeNumber: 2) == false)
        // pro plays the full asset on ep1 — never a preview.
        #expect(PodcastAccess.isPreviewPlayback(tier: .pro, episodeNumber: 1) == false)
        #expect(PodcastAccess.isPreviewPlayback(tier: .guest, episodeNumber: 1) == false)
    }

    @Test func proLockShownWhenFullPlaybackUnavailable() {
        // pro: never locked
        #expect(PodcastAccess.showsProLock(tier: .pro, episodeNumber: 1) == false)
        #expect(PodcastAccess.showsProLock(tier: .pro, episodeNumber: 3) == false)
        // free: ep1 is previewable → not hard-locked (player shows a preview
        // banner + upgrade CTA instead); ep2+ fully locked
        #expect(PodcastAccess.showsProLock(tier: .free, episodeNumber: 1) == false)
        #expect(PodcastAccess.showsProLock(tier: .free, episodeNumber: 2) == true)
        // guest: everything locked
        #expect(PodcastAccess.showsProLock(tier: .guest, episodeNumber: 1) == true)
    }
}
