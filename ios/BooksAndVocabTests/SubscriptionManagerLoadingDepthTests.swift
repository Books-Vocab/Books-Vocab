import Testing
@testable import BooksAndVocab

/// Overlapping StoreKit/network ops must not clear each other's loading state.
@MainActor
struct SubscriptionManagerLoadingDepthTests {
    @Test func isLoadingStaysTrueUntilLastOverlappingOpEnds() {
        let manager = SubscriptionManager.shared
        let baseline = manager.loadingDepth
        manager.beginLoading() // purchasePro
        manager.beginLoading() // overlapping Settings refresh
        #expect(manager.isLoading)
        manager.endLoading()
        #expect(manager.isLoading, "shorter op finishing must not re-enable Buy/Restore")
        manager.endLoading()
        #expect(manager.loadingDepth == baseline)
    }
}
