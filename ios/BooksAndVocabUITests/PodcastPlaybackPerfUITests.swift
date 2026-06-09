import XCTest

final class PodcastPlaybackPerfUITests: UITestCase {
    @MainActor
    func testPodcastPlaybackProbeReachesPlayerAndTapsPlay() throws {
        let app = launchApp(perfLog: "audio")
        captureStep("launch", app: app)

        let podcast = AppPage(app: app).goToPodcasts()
        XCTAssertTrue(app.waitForNavigationToSettle())
        captureStep("podcast-tab", app: app)

        guard podcast.anySeriesCard.waitUntilExists(timeout: 15) else {
            captureStep("no-series-card", app: app)
            throw XCTSkip("無 podcast series 測試資料，跳過播放手感 probe")
        }
        podcast.tapFirstSeries()
        XCTAssertTrue(app.waitForNavigationToSettle())
        captureStep("series-detail", app: app)

        guard podcast.anyEpisodeRow.waitUntilExists(timeout: 10) else {
            captureStep("no-episode-row", app: app)
            throw XCTSkip("podcast series 無可見 episode row，跳過播放手感 probe")
        }
        podcast.tapFirstEpisode()
        XCTAssertTrue(app.waitForNavigationToSettle())
        captureStep("episode-tapped", app: app)

        if podcast.loginSheet.waitUntilExists(timeout: 3) {
            captureStep("login-sheet", app: app)
            return
        }

        if podcast.playerLoginGate.waitUntilExists(timeout: 3) {
            captureStep("player-login-gate", app: app)
            podcast.playerLoginButton.tap()
            XCTAssertTrue(podcast.loginSheet.waitUntilExists(timeout: 3))
            captureStep("login-sheet", app: app)
            return
        }

        guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
            captureStep("player-not-playable", app: app)
            throw XCTSkip("未進入可播放 player（可能是鎖定/無音訊 episode），跳過播放手感 probe")
        }
        captureStep("player-ready", app: app)
        podcast.playPauseButton.tap()
        captureStep("play-tapped", app: app)

        XCTAssertTrue(
            podcast.playPauseButton.waitUntilExists(timeout: 3),
            "播放按鈕應維持可操作，供 ops logs 斷言 podcast.player.* audio metrics"
        )
        captureStep("play-verified", app: app)
    }
}
