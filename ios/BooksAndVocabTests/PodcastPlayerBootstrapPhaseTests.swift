import Testing
@testable import BooksAndVocab

struct PodcastPlayerBootstrapPhaseTests {
    @Test func taskNotAttemptedShowsLoading() {
        #expect(
            PodcastPlayerBootstrapPhase.phase(
                hasViewModel: false,
                loadAttempted: false,
                hasEpisode: false,
                hasSeries: false
            ) == .loading
        )
    }

    @Test func attemptedLoadWithoutEpisodeShowsRecoverableMissingState() {
        #expect(
            PodcastPlayerBootstrapPhase.phase(
                hasViewModel: false,
                loadAttempted: true,
                hasEpisode: false,
                hasSeries: false
            ) == .missingEpisode
        )
    }

    @Test func attemptedLoadWithoutSeriesShowsRecoverableMissingState() {
        #expect(
            PodcastPlayerBootstrapPhase.phase(
                hasViewModel: false,
                loadAttempted: true,
                hasEpisode: true,
                hasSeries: false
            ) == .missingEpisode
        )
    }

    @Test func hydratedEpisodeCanStillBeLoadingBeforeViewModelExists() {
        #expect(
            PodcastPlayerBootstrapPhase.phase(
                hasViewModel: false,
                loadAttempted: true,
                hasEpisode: true,
                hasSeries: true
            ) == .loading
        )
    }

    @Test func viewModelTakesPrecedence() {
        #expect(
            PodcastPlayerBootstrapPhase.phase(
                hasViewModel: true,
                loadAttempted: true,
                hasEpisode: false,
                hasSeries: false
            ) == .ready
        )
    }
}
