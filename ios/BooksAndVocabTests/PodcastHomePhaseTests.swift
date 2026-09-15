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

    @Test func backgroundSyncRunningWithNoCatalogShowsLoading() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: false,
            syncFailed: false,
            seriesCount: 0,
            backgroundSyncStatus: .running
        )

        #expect(phase == .loading)
    }

    @Test func backgroundSyncRunningKeepsExistingCatalogVisible() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: false,
            syncFailed: false,
            seriesCount: 3,
            backgroundSyncStatus: .running
        )

        #expect(phase == .content)
    }

    @Test func backgroundSyncWarningWithNoCatalogShowsRetryableError() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: false,
            syncFailed: false,
            seriesCount: 0,
            backgroundSyncStatus: .warning(L10n.string("目錄讀取失敗"))
        )

        #expect(phase == .error)
    }

    @Test func backgroundSyncWarningKeepsExistingCatalogVisible() {
        let phase = PodcastHomePhase.resolve(
            isLoggedIn: true,
            isSyncing: false,
            syncFailed: false,
            seriesCount: 3,
            backgroundSyncStatus: .warning(L10n.string("目錄讀取失敗"))
        )

        #expect(phase == .content)
    }
}
