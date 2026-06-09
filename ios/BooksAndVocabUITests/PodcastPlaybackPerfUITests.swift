import XCTest

final class PodcastPlaybackPerfUITests: UITestCase {
    @MainActor
    func testPodcastPlaybackProbeReachesPlayerAndTapsPlay() throws {
        let podcastFixtureRoot = "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts"
        let app = launchApp(
            extraArgs: [
                "-appLaunchProfile", "ui-smoke",
                "-isolatedAuthSession",
                "-seedFixture:podcast:playablePreview"
            ],
            extraEnvironment: [
                "KG_UI_TEST_PODCAST_AUDIO": "\(podcastFixtureRoot)/ep_1_flash.m4a",
                "KG_UI_TEST_PODCAST_SUBTITLE": "\(podcastFixtureRoot)/ep_1_flash.srt",
                "KG_UI_TEST_PODCAST_DURATION": "1034.6",
                "KG_UI_TEST_PODCAST_SERIES_TITLE": "Atomic Habits",
                "KG_UI_TEST_PODCAST_EPISODE_TITLE": "Actual Lab Episode",
                "KG_UI_TEST_PODCAST_HOST": "Lab Podcast"
            ],
            perfLog: "audio"
        )
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

        if podcast.loginSheet.waitUntilExists(timeout: 1) {
            captureStep("unexpected-login-sheet", app: app)
            XCTFail("lab podcast fixture should be authenticated; login sheet means this probe is not testing playback")
            return
        }

        if podcast.playerLoginGate.waitUntilExists(timeout: 1) {
            captureStep("unexpected-player-login-gate", app: app)
            XCTFail("lab podcast fixture should satisfy podcast access; login gate means this probe is not testing playback")
            return
        }

        guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
            captureStep("player-not-playable", app: app)
            XCTFail("lab podcast fixture should reach a playable player")
            return
        }
        captureStep("player-ready", app: app)
        podcast.playPauseButton.tap()
        captureStep("play-tapped", app: app)

        XCTAssertTrue(
            podcast.pauseButton.waitUntilExists(timeout: 3),
            "播放後 control 必須切成 pauseButton，證明 PodcastPlayerViewModel.state == .playing"
        )
        captureStep("play-verified", app: app)
    }
}
