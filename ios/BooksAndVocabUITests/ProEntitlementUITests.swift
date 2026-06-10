import XCTest

final class ProEntitlementUITests: UITestCase {
    private static let episode2RowID = "podcast.episode.ui-auth-series_ep_02"
    private static let podcastFixtureRoot =
        "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts"

    private static let fixtureEnvironment: [String: String] = [
        "KG_UI_TEST_PODCAST_AUDIO": "\(podcastFixtureRoot)/ep_1_flash.m4a",
        "KG_UI_TEST_PODCAST_SUBTITLE": "\(podcastFixtureRoot)/ep_1_flash.srt",
        "KG_UI_TEST_PODCAST_DURATION": "1034.6",
        "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
    ]

    @MainActor
    func testProEntitlementUnlocksGatedPodcastEpisode() throws {
        let app = launchIsolatedApp(
            fixtures: [.authTieredCatalog, .authSignedIn, .entitlementsProAccess],
            extraEnvironment: Self.fixtureEnvironment,
            perfLog: "pro-entitlement"
        )
        captureStep("pro-launch", app: app)

        let podcast = PodcastPage(app: app)

        try step("pro-podcast-catalog", app: app) {
            AppPage(app: app).goToPodcasts()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard podcast.seriesCard(id: "ui-auth-series").waitUntilExists(timeout: 15) else {
                captureStep("no-series-card", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 series")
                return
            }
        }

        try step("pro-episode-list", app: app) {
            podcast.seriesCard(id: "ui-auth-series").tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard episodeRow(Self.episode2RowID, in: app).waitUntilExists(timeout: 10) else {
                captureStep("no-gated-episode-row", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 gated ep2")
                return
            }
        }

        try step("pro-episode2-opens-player", app: app) {
            episodeRow(Self.episode2RowID, in: app).tapWhenReady(timeout: 10)
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

    private func episodeRow(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
