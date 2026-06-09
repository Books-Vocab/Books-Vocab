import Testing
@testable import BooksAndVocab

@Suite("PodcastPlayerAccessState")
struct PodcastPlayerAccessStateTests {
    @Test func missingEpisodeRemainsPlayableForBootstrap() {
        let state = PodcastPlayerAccessState.resolve(
            hasProAccess: false,
            hasToken: false,
            episodeNumber: nil,
            previewAvailable: false
        )

        #expect(state.tier == .guest)
        #expect(state.playableForTier == true)
        #expect(state.isPreviewPlayback == false)
        #expect(state.gateDestination == .login)
    }

    @Test func freePreviewEpisodeIsPlayablePreview() {
        let state = PodcastPlayerAccessState.resolve(
            hasProAccess: false,
            hasToken: true,
            episodeNumber: PodcastAccess.freePreviewEpisodeNumber,
            previewAvailable: true
        )

        #expect(state.tier == .free)
        #expect(state.playableForTier == true)
        #expect(state.isPreviewPlayback == true)
        #expect(state.gateDestination == .paywall)
    }

    @Test func freeLockedEpisodeRoutesToPaywall() {
        let state = PodcastPlayerAccessState.resolve(
            hasProAccess: false,
            hasToken: true,
            episodeNumber: PodcastAccess.freePreviewEpisodeNumber + 1,
            previewAvailable: true
        )

        #expect(state.playableForTier == false)
        #expect(state.isPreviewPlayback == false)
        #expect(state.gateDestination == .paywall)
    }

    @Test func proAlwaysPlayableAndNeverPreviewPlayback() {
        let state = PodcastPlayerAccessState.resolve(
            hasProAccess: true,
            hasToken: true,
            episodeNumber: 9,
            previewAvailable: false
        )

        #expect(state.tier == .pro)
        #expect(state.playableForTier == true)
        #expect(state.isPreviewPlayback == false)
        #expect(state.gateDestination == .paywall)
    }
}
