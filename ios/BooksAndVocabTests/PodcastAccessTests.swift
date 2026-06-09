import Foundation
import Testing
@testable import BooksAndVocab

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
        #expect(PodcastAccess.canPlay(tier: .guest, episodeNumber: 1, previewAvailable: true) == false)
        #expect(PodcastAccess.canPlay(tier: .guest, episodeNumber: 2, previewAvailable: true) == false)
    }

    @Test func freeCanPlayOnlyEpisodeOneWithPreviewAsset() {
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 1, previewAvailable: true) == true)
        // ep1 of a legacy series with no preview asset → not playable (would
        // otherwise dead-end on a backend 404). This is the gap previewAvailable closes.
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 1, previewAvailable: false) == false)
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 2, previewAvailable: true) == false)
        #expect(PodcastAccess.canPlay(tier: .free, episodeNumber: 5, previewAvailable: true) == false)
    }

    @Test func proCanPlayEverythingRegardlessOfPreview() {
        #expect(PodcastAccess.canPlay(tier: .pro, episodeNumber: 1, previewAvailable: false) == true)
        #expect(PodcastAccess.canPlay(tier: .pro, episodeNumber: 9, previewAvailable: false) == true)
    }

    @Test func previewPlaybackOnlyForFreeEpisodeOneWithAsset() {
        #expect(PodcastAccess.isPreviewPlayback(tier: .free, episodeNumber: 1, previewAvailable: true) == true)
        #expect(PodcastAccess.isPreviewPlayback(tier: .free, episodeNumber: 1, previewAvailable: false) == false)
        #expect(PodcastAccess.isPreviewPlayback(tier: .free, episodeNumber: 2, previewAvailable: true) == false)
        // pro plays the full asset on ep1 — never a preview.
        #expect(PodcastAccess.isPreviewPlayback(tier: .pro, episodeNumber: 1, previewAvailable: true) == false)
        #expect(PodcastAccess.isPreviewPlayback(tier: .guest, episodeNumber: 1, previewAvailable: true) == false)
    }

    @Test func proLockShownWhenFullPlaybackUnavailable() {
        // pro: never locked
        #expect(PodcastAccess.showsProLock(tier: .pro, episodeNumber: 1, previewAvailable: false) == false)
        #expect(PodcastAccess.showsProLock(tier: .pro, episodeNumber: 3, previewAvailable: false) == false)
        // free: ep1 with a preview asset → not hard-locked (player shows a preview
        // banner + upgrade CTA instead); ep1 without asset & ep2+ fully locked
        #expect(PodcastAccess.showsProLock(tier: .free, episodeNumber: 1, previewAvailable: true) == false)
        #expect(PodcastAccess.showsProLock(tier: .free, episodeNumber: 1, previewAvailable: false) == true)
        #expect(PodcastAccess.showsProLock(tier: .free, episodeNumber: 2, previewAvailable: true) == true)
        // guest: everything locked
        #expect(PodcastAccess.showsProLock(tier: .guest, episodeNumber: 1, previewAvailable: true) == true)
    }
}
