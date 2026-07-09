#if os(iOS)
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("KGVocabCoordinator banners")
struct KGVocabCoordinatorBannerTests {
    @Test func dismissBannerClearsErrorAndSuccessMessages() {
        let coordinator = KGVocabCoordinator()
        coordinator.bannerError = .refresh(message: "offline", isRetryable: true, isNetworkRelated: true)
        coordinator.refreshSuccessMessage = "updated"

        coordinator.dismissBanner()

        #expect(coordinator.bannerError == nil)
        #expect(coordinator.errorMessage == nil)  // 衍生自 bannerError
        #expect(coordinator.refreshSuccessMessage == nil)
    }
}
#endif
