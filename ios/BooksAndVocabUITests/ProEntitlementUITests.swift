import XCTest

final class ProEntitlementUITests: UITestCase {
    @MainActor
    func testProEntitlementUnlocksGatedPodcastEpisode() throws {
        let app = launchPodcastAccessScenario(.pro)
        captureStep("pro-launch", app: app)

        let podcast = PodcastPage(app: app)

        try step("pro-podcast-catalog", app: app) {
            AppPage(app: app).goToPodcasts()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard podcast.seriesCard(id: PodcastFixture.seriesID).waitUntilExists(timeout: 15) else {
                captureStep("no-series-card", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 series")
                return
            }
        }

        try step("pro-episode-list", app: app) {
            podcast.seriesCard(id: PodcastFixture.seriesID).tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard podcast.episodeRow(PodcastFixture.episode2RowID).waitUntilExists(timeout: 10) else {
                captureStep("no-gated-episode-row", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 gated ep2")
                return
            }
        }

        try step("pro-episode2-opens-player", app: app) {
            podcast.episodeRow(PodcastFixture.episode2RowID).tapWhenReady(timeout: 10)
            XCTAssertTrue(app.waitForNavigationToSettle())
            if podcast.loginSheet.waitUntilExists(timeout: 1) {
                captureStep("unexpected-login-sheet", app: app)
                XCTFail("Pro entitlement fixture 不得彈出 LoginSheet")
                return
            }
            guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
                captureStep("player-not-playable", app: app)
                XCTFail("Pro entitlement fixture 應直接解鎖 gated ep2 並進入 player")
                return
            }
        }
    }
}
