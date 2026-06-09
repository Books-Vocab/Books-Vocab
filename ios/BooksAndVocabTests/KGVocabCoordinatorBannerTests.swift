#if os(iOS)
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("KGVocabCoordinator banners")
struct KGVocabCoordinatorBannerTests {
    @Test func dismissBannerClearsErrorAndSuccessMessages() {
        let coordinator = KGVocabCoordinator()
        coordinator.errorMessage = "offline"
        coordinator.refreshSuccessMessage = "updated"

        coordinator.dismissBanner()

        #expect(coordinator.errorMessage == nil)
        #expect(coordinator.refreshSuccessMessage == nil)
    }
}
#endif
