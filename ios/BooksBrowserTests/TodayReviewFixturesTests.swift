#if DEBUG
import Testing
@testable import BooksBrowser

@Suite struct TodayReviewFixturesTests {
    @Test func todayReviewFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = TodayReviewFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = TodayReviewFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "today_review.front",
            "today_review.back",
            "today_review.completed",
            "today_review.autoplay",
            "today_review.longContent",
        ])

        #expect(catalogKeys == previewKeys)
    }
}
#endif
