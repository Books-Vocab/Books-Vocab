import Testing
@testable import BooksAndVocab

@Suite("PodcastHomePhase")
struct PodcastHomePhaseTests {
    @Test func signedOutCatalogCanStillShowInitialLoading() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: false,
            isSyncing: true,
            syncFailed: false,
            seriesCount: 0
        )

        #expect(phase == .loading)
    }

    @Test func signedOutSuccessfulEmptyCatalogUsesEmptyStateNotLoginGate() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: false,
            isSyncing: false,
            syncFailed: false,
            seriesCount: 0
        )

        #expect(phase == .empty)
    }

    @Test func initialSyncWithNoCatalogShowsLoading() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: true,
            syncFailed: false,
            seriesCount: 0
        )

        #expect(phase == .loading)
    }

    @Test func failedSyncWithNoCatalogShowsRetryableError() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: false,
            syncFailed: true,
            seriesCount: 0
        )

        #expect(phase == .error)
    }

    @Test func existingCatalogKeepsContentEvenWhileRefreshing() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: true,
            syncFailed: true,
            seriesCount: 3
        )

        #expect(phase == .content)
    }
}
